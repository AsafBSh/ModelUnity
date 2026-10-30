"""Global installation queue, independent of asset projects and inference jobs."""
from __future__ import annotations
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from dataclasses import asdict
from fnmatch import fnmatchcase
from pathlib import Path
from threading import Event, Thread, RLock
from urllib.parse import quote
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
import zipfile

from filelock import FileLock, Timeout
from .catalog import catalog, required_models
from .downloads import Cancelled, hash_file, read_json, safe_relative, target_path, transfer, valid

ACTIVE = ('queued', 'resolving', 'downloading', 'verifying', 'installing', 'cancelling')
TERMINAL = ('completed', 'failed', 'cancelled', 'interrupted')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    os.replace(temporary, path)


class Manager:
    def __init__(self, root, config, *, state=None, models=None, runtime_probe=None):
        self.root, self.config = Path(root).resolve(), deepcopy(config)
        options = config.get('model_manager', {})
        self.state = Path(state or self.root / options.get('state_dir', '.runtime/model_manager')).resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / 'leases').mkdir(exist_ok=True)
        (self.state / 'logs').mkdir(exist_ok=True)
        self.options_path = self.state / 'settings.json'
        default = (self.root / options.get('models_dir', 'pretrained_weights/managed')).resolve()
        self.options = json.loads(self.options_path.read_text(encoding='utf-8')) if self.options_path.exists() else {'models_dir': str(default)}
        self.models = models or catalog(config)
        self.reserve = int(options.get('reserve_bytes', 512 * 1024 * 1024))
        self.runtime_probe = runtime_probe
        self.stop, self.wake = Event(), Event()
        self.thread, self.owner = None, None
        self.token = None  # Session memory only; never written to jobs or logs.
        check_file=self.state/'runtime-checks.json'
        self.runtime_checks=json.loads(check_file.read_text(encoding='utf-8')) if check_file.exists() else {}
        self._runtime_cache, self._inventory_cache = {}, {}
        self._lock = RLock()
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS installations (model TEXT PRIMARY KEY, manifest TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, model TEXT, action TEXT, state TEXT, message TEXT,
                done INTEGER, total INTEGER, speed REAL, created REAL, updated REAL,
                request TEXT, cancel INTEGER DEFAULT 0)''')

    @property
    def models_dir(self): return Path(self.options['models_dir']).resolve()

    @property
    def token(self):return getattr(self,'_token',None)

    @token.setter
    def token(self,value):
        if not hasattr(self,'_secrets'):self._secrets=set()
        if value:self._secrets.add(value)
        self._token=value

    def redact(self,value):
        text=str(value)
        for secret in self._secrets:text=text.replace(secret,'[token]')
        return text

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.state / 'models.sqlite3', timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def record(self, key):
        with self.db() as db:
            row = db.execute('SELECT manifest FROM installations WHERE model=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_record(self, key, value):
        old=self.record(key)
        if old and (old.get('directory')!=value.get('directory') or old.get('revision')!=value.get('revision') or
                    {f['path'] for f in old.get('files',[])}!={f['path'] for f in value.get('files',[])}):
            previous=list(old.get('previous',[]))
            snapshot={k:v for k,v in old.items() if k!='previous'}
            if snapshot.get('owned'):previous.append(snapshot)
            value['previous']=previous
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO installations VALUES (?,?)', (key,json.dumps(value)))
        self._inventory_cache.clear()

    def closure(self, keys):
        result = []
        def visit(key, trail=()):
            if key in trail: raise ValueError('Circular model dependency.')
            if key not in self.models: raise ValueError('Unknown model selection.')
            if key in result: return
            for dependency in self.models[key].dependencies: visit(dependency, (*trail,key))
            result.append(key)
        for key in keys: visit(key)
        return result

    def lease(self, key): return FileLock(str(self.state / 'leases' / (key + '.lock')), timeout=0)

    def in_use(self, key):
        try:
            with self.lease(key): return False
        except Timeout: return True

    def start(self):
        if self.thread: return
        owner = FileLock(str(self.state / 'queue.lock'), timeout=0)
        try: owner.acquire()
        except Timeout: return  # Another local server owns the same durable queue.
        self.owner = owner
        with self.db() as db:
            db.execute("UPDATE jobs SET state='interrupted',message='Application stopped. Use Retry to continue retained partial files.' WHERE state IN ('resolving','downloading','verifying','installing','cancelling')")
        self.thread = Thread(target=self._loop, daemon=True, name='ModelUnifyModels')
        self.thread.start()

    def close(self):
        self.stop.set(); self.wake.set()
        if self.thread: self.thread.join(timeout=20)
        if self.owner and (not self.thread or not self.thread.is_alive()): self.owner.release()

    def jobs(self):
        with self.db() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY CASE WHEN state IN ('resolving','downloading','verifying','installing','cancelling') THEN 0 WHEN state='queued' THEN 1 ELSE 2 END,created DESC LIMIT 80").fetchall()
        return [dict(row) for row in rows]

    def job(self, job_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row: raise ValueError('Select an installation job.')
        return dict(row)

    def update(self, job_id, **values):
        allowed = {'state','message','done','total','speed','cancel'}
        if set(values) - allowed: raise ValueError('Invalid installation progress field.')
        if 'message' in values:values['message']=self.redact(values['message'])
        values['updated'] = time.time()
        with self.db() as db:
            db.execute('UPDATE jobs SET '+','.join(k+'=?' for k in values)+' WHERE id=?', (*values.values(),job_id))
        if 'message' in values:
            line = self.redact(values['message'])
            with (self.state / 'logs' / (job_id+'.log')).open('a',encoding='utf-8') as log:
                log.write(line + '\n')

    def submit(self, key, action='install', payload=None):
        if key not in self.models and key != 'runtime': raise ValueError('Unknown model selection.')
        if action not in ('install','update','verify','register','repair','runtime','runtime-check','paint-build','paint-check','host-start','host-stop','host-check'):
            raise ValueError('Unknown model action.')
        if action in ('install','update','verify','register','repair') and key == 'runtime': raise ValueError('Select a model first.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id FROM jobs WHERE model=? AND state IN ('+','.join('?' for _ in ACTIVE)+')', (key,*ACTIVE)).fetchone()
            if row: return row[0]
            job_id, now = uuid.uuid4().hex, time.time()
            data = dict(payload or {})
            data.setdefault('models_dir',str(self.models_dir))  # Retry keeps its original destination and revision.
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,0)',
                       (job_id,key,action,'queued','Queued',0,0,0,now,now,json.dumps(data)))
        self.wake.set()
        return job_id

    def cancel(self, job_id):
        row = self.job(job_id)
        if row['state'] not in ACTIVE: return
        self.update(job_id, cancel=1, state='cancelled' if row['state']=='queued' else 'cancelling',
                    message='Cancellation requested; waiting for the current read or installation boundary.')

    def retry(self, job_id):
        row = self.job(job_id)
        if row['state'] not in ('failed','cancelled','interrupted'): raise ValueError('Only failed, cancelled or interrupted jobs can be retried.')
        return self.submit(row['model'], row['action'], json.loads(row['request']))

    def cancelled(self, job_id): return self.stop.is_set() or bool(self.job(job_id)['cancel'])

    def set_directory(self, directory):
        path = Path(directory).expanduser()
        if not path.is_absolute(): path = self.root / path
        path = path.resolve()
        if path == Path(path.anchor) or path in (self.root,Path.home().resolve()) or any(p.lower() in ('.git','windows','system32') for p in path.parts):
            raise ValueError('Choose a dedicated model folder, not a drive root, project root, home or system directory.')
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ('.modelunify-write-' + uuid.uuid4().hex)
        probe.write_bytes(b''); probe.unlink()
        if path.is_relative_to(self.root) and not (path/'.gitignore').exists():
            (path/'.gitignore').write_text('# Local model storage.\n*\n',encoding='utf-8')
        with self._lock:
            self.options['models_dir'] = str(path)
            atomic_json(self.options_path,self.options)
        return 'New Install / repair actions will use this folder. Existing installations and Retry keep their recorded locations; start a new installation to switch drives.'

    def runtime_status(self, kind, key=None):
        if self.runtime_probe: return self.runtime_probe(kind)
        if kind == 'none': return []
        cached = self._runtime_cache.get((kind,key))
        if cached and time.monotonic()-cached[0] < 10: return cached[1]
        errors = []
        if kind in ('shape','paint','comfy'):
            import torch
            configured_cpu = self.config.get('model',{}).get('hunyuan' if key=='hunyuan' else 'triposg',{}).get('device') == 'cpu'
            if not torch.cuda.is_available() and (kind != 'shape' or not configured_cpu):
                errors.append('NVIDIA CUDA is unavailable. AMD/Intel GPU inference is not integrated; native shape CPU fallback must be configured explicitly.')
        if kind == 'onnx':
            import importlib.util
            if importlib.util.find_spec('onnxruntime') is None: errors.append('ONNX Runtime is missing from the main environment.')
        if kind == 'paint':
            check=self.runtime_checks.get('paint',{})
            if not check.get('ready') or check.get('fingerprint')!=self.runtime_fingerprint('paint'):
                errors.append('Paint runtime requires verification. Use Verify paint runtime; build extensions first if they are missing.')
        if kind == 'comfy':
            cfg = self.config.get('model',{}).get('comfyui',{})
            python = self.root / cfg.get('python_exe','.runtime/comfyui/python/Scripts/python.exe')
            host = self.root / cfg.get('server_dir','.runtime/comfyui/ComfyUI')
            if not python.is_file() or not (host/'main.py').is_file(): errors.append('Isolated ComfyUI runtime is missing. Use Install / repair ComfyUI runtime.')
            else:
                check=self.runtime_checks.get('comfy',{})
                if not check.get('ready') or check.get('fingerprint')!=self.runtime_fingerprint('comfy'):
                    errors.append('ComfyUI environment found; use Verify ComfyUI runtime to check its actual Torch/CUDA stack.')
        self._runtime_cache[(kind,key)] = (time.monotonic(),errors)
        return errors

    def runtime_fingerprint(self, kind):
        if kind=='comfy':
            cfg=self.config.get('model',{}).get('comfyui',{})
            executable=self.root/cfg.get('python_exe','.runtime/comfyui/python/Scripts/python.exe')
            paths=[executable,executable.parent.parent/'Lib/site-packages/torch/lib/torch_cuda.dll',self.root/cfg.get('server_dir','.runtime/comfyui/ComfyUI')/'main.py']
        else:
            import importlib.util
            spec=importlib.util.find_spec('custom_rasterizer_kernel')
            paths=[Path(sys.executable),Path(spec.origin)] if spec and spec.origin else [Path(sys.executable)]
        state=[(str(p.resolve()),p.stat().st_mtime_ns if p.exists() else None) for p in paths]
        return hashlib.sha256(json.dumps(state).encode()).hexdigest()

    def discover(self, key):
        model, candidates = self.models[key], []
        paths = self.config.get('model',{})
        if key in ('triposg','rmbg'):
            candidates.append(self.root / paths.get('triposg',{}).get('weights_dir' if key=='triposg' else 'rmbg_dir', 'pretrained_weights/'+('TripoSG' if key=='triposg' else 'RMBG-1.4')))
        if key == 'realesrgan': candidates.append(self.root / 'vendor/Hunyuan3D-2.1/hy3dpaint/ckpt')
        if key.startswith('rembg-'): candidates.append(Path(os.environ.get('U2NET_HOME', str(Path.home()/'.u2net'))))
        if model.source == 'hf' and not key.startswith('comfy-'):
            home = Path(os.environ.get('HF_HUB_CACHE', str(Path(os.environ.get('HF_HOME',str(Path.home()/'.cache/huggingface')))/'hub')))
            repository = home / ('models--'+model.repo.replace('/','--'))
            for repository in (repository,self.models_dir/'hub'/('models--'+model.repo.replace('/','--'))):
                ref = repository / 'refs/main'
                if ref.is_file():
                    revision = ref.read_text(encoding='utf-8').strip()
                    if re.fullmatch('[0-9a-f]{40}',revision): candidates.append(repository / 'snapshots' / revision)
        if key=='hunyuan':
            candidates.append(Path(os.path.expanduser(os.environ.get('HY3DGEN_MODELS','~/.cache/hy3dgen')))/model.repo)
        if key.startswith('comfy-'):
            candidates.append(self.root / paths.get('comfyui',{}).get('server_dir','.runtime/comfyui/ComfyUI') / 'models')
        for directory in candidates:
            if directory.is_dir() and all(any(p.is_file() and p.stat().st_size for p in directory.glob(pattern)) for pattern in model.required):
                return directory.resolve()
        return None

    def status(self, key, trail=()):
        if key in trail: raise ValueError('Circular model dependency.')
        model, record = self.models[key], self.record(key)
        complete = bool(record and record.get('verified') and record.get('files'))
        if complete:
            for entry in record['files']:
                p = Path(entry['path'])
                try:present=p.is_file() and p.stat().st_size == entry['size']
                except OSError:present=False
                if not present:
                    complete = False; break
        dependencies = [self.status(k, (*trail,key)) for k in model.dependencies]
        missing = [d['name'] for d in dependencies if not d['ready']]
        errors = self.runtime_status(model.runtime,key)
        external = self.discover(key) if not record else None
        state = 'Ready' if complete and not missing and not errors else 'Downloaded · prerequisites missing' if complete else 'Found existing · verify' if external else 'Missing / incomplete'
        return {'key':key,'name':model.name,'group':model.group,'state':state,'downloaded':complete,'ready':complete and not missing and not errors,
                'verified':complete,'dependencies':model.dependencies,'missing_dependencies':missing,'runtime_errors':errors,
                'in_use':self.in_use(key),'location':record.get('directory') if record else str(external) if external else None,
                'owned':bool(record and record.get('owned')),'revision':record.get('revision') if record else None,
                'bytes':sum(f['size'] for f in record['files']) if complete else model.estimated_bytes,
                'description':model.description,'source':model.license_url}

    def inventory(self):
        # File status only: polling never hashes multi-GB files or calls the network.
        cache=dict(self._inventory_cache)
        if cache and time.monotonic()-cache['time'] < 2:
            return cache['value']
        value = [self.status(key) for key in self.models]
        self._inventory_cache = {'time':time.monotonic(),'value':value}
        return value

    def readiness(self, keys):
        return [self.status(key) for key in self.closure(keys)]

    def assert_ready(self, keys):
        details = self.readiness(keys)
        blocked = [v for v in details if not v['ready']]
        if blocked:
            names = ', '.join(v['name'] for v in blocked)
            raise ValueError('Models are not ready: '+names+'. Open Models and install/verify the missing components. No download was started.')
        return details

    def resolve(self, key, action, revision_override=None):
        model, previous = self.models[key], self.record(key)
        revision = previous.get('revision') if previous and action not in ('update',) else model.revision
        if revision_override:revision=revision_override
        if model.source == 'hf':
            if not model.repo or Path(model.repo).is_absolute(): raise ValueError('A custom local model repository must be configured as an existing installation, not downloaded as a Hub ID.')
            url = 'https://huggingface.co/api/models/'+quote(model.repo,safe='/')+'/revision/'+quote(revision or model.revision,safe='')+'?blobs=true'
            info = read_json(url,self.token)
            revision = info['sha']
            if not re.fullmatch('[a-f0-9]{40}', revision): raise ValueError('Hub metadata did not return an immutable revision.')
            files = []
            for sibling in info.get('siblings',[]):
                name = sibling['rfilename']
                if not model.includes(name): continue
                safe_relative(name)
                lfs = sibling.get('lfs') or {}
                item = {'relative':name,'url':'https://huggingface.co/'+quote(model.repo,safe='/')+'/resolve/'+revision+'/'+quote(name,safe='/'),
                        'size':sibling.get('size',lfs.get('size'))}
                if lfs.get('sha256'): item['sha256'] = lfs['sha256']
                elif sibling.get('blobId'): item['git_sha1'] = sibling['blobId']
                files.append(item)
            names = [f['relative'] for f in files]
            if not files or any(not any(fnmatchcase(n,p) for n in names) for p in model.required):
                raise ValueError('The upstream file listing does not satisfy this model recipe. Check the configured filenames/revision.')
            return revision,files
        if model.source == 'github':
            return model.revision,[{'relative':'source.zip','url':f'https://github.com/{model.repo}/archive/{model.revision}.zip','size':None,'max_size':512*1024*1024,'format':'zip'}]
        item = {'relative':model.filename,'url':model.url,'size':model.download_bytes}
        if previous and previous.get('revision')==model.revision:
            old=next((f for f in previous.get('files',[]) if f['relative']==model.filename),None)
            if old:item.update(size=old['size'],sha256=old['sha256'])
        if model.checksum:
            algorithm,digest = model.checksum.split(':',1)
            if algorithm not in ('md5','sha256'): raise ValueError('Unsupported checksum algorithm.')
            item[algorithm] = digest
        return model.revision,[item]

    def _destination(self, key, model, revision, base):
        if key.startswith('comfy-'):
            return base / 'comfy_models'  # Each file receives an immutable subdirectory below.
        if key == 'stablenormal': return base / 'stablenormal' / revision / 'yoso-normal-v0-3'
        if model.source == 'hf': return base / 'hub' / ('models--'+model.repo.replace('/','--')) / 'snapshots' / revision
        return base / key / revision

    def _file_path(self, key, revision, directory, item):
        relative = item['relative']
        if key.startswith('comfy-'):
            folder, name = relative.split('/',1)
            relative = folder + '/modelunify/' + revision + '/' + name
        return target_path(directory,relative)

    def _verify(self, key, job_id, existing_dir=None):
        model, record = self.models[key], self.record(key)
        if record and existing_dir is None:
            record['verified'] = False
            self.save_record(key,record)
            entries = record['files']
            total = sum(f['size'] for f in entries)
            base = 0
            for entry in entries:
                path = Path(entry['path'])
                if not path.is_file(): raise ValueError('An installed file is missing. Use Repair to restore it.')
                self.update(job_id,state='verifying',message='Verifying '+entry['relative'],done=base,total=total,speed=0)
                actual = hash_file(path,lambda:self.cancelled(job_id),lambda count:self._throttled(job_id,base+count,total,0))
                if not valid(actual,entry): raise ValueError('A checkpoint changed or is corrupt. Use Repair to restore it.')
                base += actual['size']
            record['verified'] = True
            record['verified_at'] = time.time()
            self.save_record(key,record)
            return
        directory = Path(existing_dir).expanduser().resolve() if existing_dir else self.discover(key)
        if not directory: raise ValueError('No complete existing installation was found. Use Install / repair.')
        if not directory.is_dir():raise ValueError('Select an existing folder containing the model repository files.')
        if key=='stablenormal' and directory.name!='yoso-normal-v0-3':
            raise ValueError('StableNormal requires a folder named yoso-normal-v0-3. Use Install / repair for the managed layout.')
        self.update(job_id,state='resolving',message='Checking existing files against upstream metadata',total=0)
        revision,expected = self.resolve(key,'verify',revision_override=directory.name) if re.fullmatch('[a-f0-9]{40}',directory.name) else self.resolve(key,'verify')
        if model.source == 'github': raise ValueError('Install the pinned StableNormal source through Models first.')
        entries, base = [],0
        total = sum(item.get('size') or 0 for item in expected)
        for item in expected:
            if not any(item.get(algorithm) for algorithm in ('sha256','md5','git_sha1')):
                raise ValueError('This source has no published digest for verifying an external copy. Use Install / repair to fetch its pinned official artifact.')
            # Existing HF caches may legitimately use links into shared blobs.
            # This path is read-only, hash checked, and never manager-owned.
            path = directory.joinpath(*safe_relative(item['relative']).parts)
            if not path.is_file(): raise ValueError('The existing installation is incomplete. Use Install / repair for an owned copy.')
            self.update(job_id,state='verifying',message='Verifying existing '+item['relative'],done=base,total=total)
            actual = hash_file(path,lambda:self.cancelled(job_id),lambda count:self._throttled(job_id,base+count,total,0))
            if not valid(actual,item): raise ValueError('Existing files do not match the selected upstream revision. Use Install / repair.')
            entries.append({'relative':item['relative'],'path':str(path),'size':actual['size'],'sha256':actual['sha256']})
            base += actual['size']
        registered={'directory':str(directory),'owned':False,'revision':revision,'verified':True,'files':entries,'root':None}
        if key.startswith('comfy-'):registered['comfy_name']=expected[0]['relative'].split('/',1)[1]
        self.save_record(key,registered)

    def _throttled(self, job_id, done, total, speed):
        now = time.monotonic()
        if now-getattr(self,'_last_progress',0) >= .2:
            self.update(job_id,done=done,total=total or 0,speed=speed)
            self._last_progress = now

    def _install(self, key, action, job_id, base):
        model = self.models[key]
        if action == 'install' and self.status(key)['downloaded']: return
        self.update(job_id,state='resolving',message='Reading model revision and file sizes',done=0,total=0,speed=0)
        request_data=json.loads(self.job(job_id)['request'])
        resolution=request_data.get('resolutions',{}).get(key)
        if resolution:
            revision,files=resolution['revision'],resolution['files']
        else:
            revision, files = self.resolve(key,action)
            request_data.setdefault('resolutions',{})[key]={'revision':revision,'files':files}
            with self.db() as db:db.execute('UPDATE jobs SET request=? WHERE id=?',(json.dumps(request_data),job_id))
        directory = self._destination(key,model,revision,base)
        directory.mkdir(parents=True,exist_ok=True)
        plan = {'model':key,'revision':revision,'files':files,'directory':str(directory)}
        atomic_json(self.state / ('plan-'+job_id+'.json'),plan)
        total = sum(item.get('size') or 0 for item in files)
        missing = 0
        for item in files:
            path = self._file_path(key,revision,directory,item)
            part = path.with_name(path.name+'.part')
            missing += max(0,(item.get('size') or model.estimated_bytes//max(1,len(files)))-(part.stat().st_size if part.exists() else 0)) if not path.exists() else 0
        if shutil.disk_usage(directory).free < missing + self.reserve:
            raise ValueError('Insufficient free space on the selected model drive, including installation headroom.')
        entries, done = [],0
        for item in files:
            if self.cancelled(job_id): raise Cancelled('Installation cancelled; verified files and partial downloads were retained.')
            path = self._file_path(key,revision,directory,item)
            checked = None
            if path.is_file():
                self.update(job_id,state='verifying',message='Verifying cached '+item['relative'],done=done,total=total,speed=0)
                actual = hash_file(path,lambda:self.cancelled(job_id))
                if valid(actual,item) and (item.get('format')!='zip' or zipfile.is_zipfile(path)): checked = actual
            if checked is None:
                self.update(job_id,state='downloading',message='Downloading '+item['relative'],done=done,total=total,speed=0)
                last_verify=[0]
                def verification(count,file_total):
                    current=time.monotonic()
                    if count==0 or count==file_total or current-last_verify[0]>.25:
                        self.update(job_id,state='verifying',speed=0,message=f"Verifying {item['relative']} · {count}/{file_total} bytes hashed")
                        last_verify[0]=current
                checked = transfer(item,path,token=self.token,cancelled=lambda:self.cancelled(job_id),reserve=self.reserve,
                    progress=lambda count,file_total,speed:self._throttled(job_id,done+count,total or file_total or 0,speed),verifying=verification)
            entries.append({'relative':item['relative'],'path':str(path),'size':checked['size'],'sha256':checked['sha256']})
            done += checked['size']
            self.update(job_id,done=done,total=total or done,speed=0)
        if model.source == 'github':
            self.update(job_id,state='installing',message='Unpacking pinned StableNormal source',speed=0)
            archive = directory / 'source.zip'
            extracted = directory / 'code'
            entries = []
            with zipfile.ZipFile(archive) as bundle:
                if sum(info.file_size for info in bundle.infolist()) > 512*1024*1024: raise ValueError('Source archive is too large.')
                for info in bundle.infolist():
                    parts = safe_relative(info.filename.rstrip('/')).parts
                    if parts[0] != model.repo.split('/')[-1]+'-'+revision:raise ValueError('Source archive root does not match its pinned revision.')
                    if len(parts) < 2 or info.is_dir(): continue
                    if (info.external_attr >> 16) & 0o170000 == 0o120000: raise ValueError('Source archive contains a link.')
                    relative = '/'.join(parts[1:])
                    target = target_path(extracted,relative)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with bundle.open(info) as source, target.open('wb') as output: shutil.copyfileobj(source,output,1024*1024)
                    actual = hash_file(target,lambda:self.cancelled(job_id))
                    entries.append({'relative':relative,'path':str(target),'size':actual['size'],'sha256':actual['sha256']})
            directory = extracted
            archive.unlink()
        names=[entry['relative'] for entry in entries]
        if any(not any(fnmatchcase(name,pattern) for name in names) for pattern in model.required):
            raise ValueError('The installed files do not satisfy this model recipe. No installation was published.')
        record = {'directory':str(directory),'owned':True,'root':str(base.resolve()),'revision':revision,'verified':True,'verified_at':time.time(),'files':entries}
        if key.startswith('comfy-'):
            record['comfy_name'] = 'modelunify/'+revision+'/'+files[0]['relative'].split('/',1)[1]
        self.save_record(key,record)
        if model.source == 'hf' and not key.startswith('comfy-') and key != 'stablenormal':
            ref = directory.parent.parent / 'refs/main'
            ref.parent.mkdir(parents=True,exist_ok=True)
            temporary = ref.with_name('main.'+uuid.uuid4().hex+'.tmp')
            temporary.write_text(revision,encoding='utf-8'); temporary.replace(ref)

    def _plan_space(self, keys, action, job_id, base):
        """Resolve the entire dependency group before transferring its first file."""
        self.update(job_id,state='resolving',message='Planning all selected model dependencies and destination space',done=0,total=0,speed=0)
        data=json.loads(self.job(job_id)['request'])
        missing=0
        for key in keys:
            if action=='install' and self.status(key)['downloaded']:continue
            if self.cancelled(job_id):raise Cancelled('Planning cancelled; no checkpoint was downloaded.')
            resolution=data.get('resolutions',{}).get(key)
            if not resolution:
                revision,files=self.resolve(key,action)
                resolution={'revision':revision,'files':files}
                data.setdefault('resolutions',{})[key]=resolution
                with self.db() as db:db.execute('UPDATE jobs SET request=? WHERE id=?',(json.dumps(data),job_id))
            model=self.models[key]
            directory=self._destination(key,model,resolution['revision'],base)
            record=self.record(key)
            known={f['path']:f for f in record['files']} if record and record.get('verified') else {}
            for entry in resolution['files']:
                path=self._file_path(key,resolution['revision'],directory,entry)
                if str(path) in known and path.is_file() and path.stat().st_size==known[str(path)]['size']:continue
                part=path.with_name(path.name+'.part')
                expected=entry.get('size') or max(1,model.estimated_bytes//len(resolution['files']))
                missing+=max(0,expected-(part.stat().st_size if part.exists() else 0))
        drive=base
        while not drive.exists() and drive.parent!=drive:drive=drive.parent
        if shutil.disk_usage(drive).free < missing+self.reserve:
            raise ValueError(f'Insufficient free space for this dependency group: approximately {missing/1024**3:.2f} GiB plus {self.reserve/1024**3:.2f} GiB headroom is required. Choose another model folder or free space. No transfer was started.')

    def _loop(self):
        while not self.stop.is_set():
            with self.db() as db:
                row = db.execute("SELECT * FROM jobs WHERE state='queued' AND cancel=0 ORDER BY created LIMIT 1").fetchone()
            if not row:
                self.wake.wait(.5); self.wake.clear(); continue
            self.run(dict(row))

    def run(self, row):
        job_id, key, action = row['id'],row['model'],row['action']
        try:
            if self.cancelled(job_id): raise Cancelled('Cancelled before execution.')
            if action in ('runtime','runtime-check','paint-build','paint-check','host-start','host-stop','host-check'):
                self._runtime_job(job_id,action)
            else:
                base = Path(json.loads(row['request'])['models_dir']).resolve()
                keys = self.closure([key]) if action not in ('verify','register') else [key]
                with ExitStack() as stack:
                    # Never rewrite/remove weights while a worker uses them.
                    for current in sorted(keys):
                        try: stack.enter_context(self.lease(current))
                        except Timeout: raise ValueError('A required model is in use. Wait for the operation to finish, then Retry.') from None
                    if action not in ('verify','register'):self._plan_space(keys,action,job_id,base)
                    for current in keys:
                        if action in ('verify','register'): self._verify(current,job_id,json.loads(row['request']).get('existing_dir') if action=='register' else None)
                        else: self._install(current,action,job_id,base)
            self._runtime_cache.clear(); self._inventory_cache.clear()
            self.update(job_id,state='completed',speed=0,message='Completed. Readiness includes separate runtime and dependency checks.')
        except Cancelled as exc:
            self.update(job_id,state='interrupted' if self.stop.is_set() else 'cancelled',message=str(exc),speed=0)
        except Exception as exc:
            message = self.redact(exc)
            # Signed URLs and HTTP response bodies must never enter UI logs.
            message = re.sub(r'https?://\S+', '[download endpoint]', message)
            self.update(job_id,state='failed',message=type(exc).__name__+': '+message[:1500],speed=0)

    def _runtime_job(self, job_id, action):
        from scripts.engine_comfyui import config_from_dict, start_host, stop_host, ComfyEngine
        from scripts.comfyui_workflows import ComfyRequest
        cfg = self.runtime_configuration(self.config)
        comfy = config_from_dict(cfg)
        self.update(job_id,state='installing',message='Running '+action+'; this stage reports logs rather than a byte percentage.',done=0,total=0,speed=0)
        if action == 'host-start': start_host(comfy,lambda message,progress:self._host_progress(job_id,message)); return
        if action == 'host-stop': self.update(job_id,message=stop_host(comfy)); return
        if action == 'host-check':
            result = ComfyEngine(comfy).readiness(ComfyRequest())
            self.update(job_id,message=json.dumps(result))
            if not result.get('ready'): raise ValueError('Host is not ready; inspect the node/checkpoint findings in the log.')
            return
        # Avoid pip/native builds against a live Comfy host or active inference.
        report_path=self.state/('runtime-probe-'+job_id+'.json')
        if action in ('runtime','runtime-check','paint-build','paint-check'):
            kind='comfy' if action in ('runtime','runtime-check') else 'paint'
            self.runtime_checks[kind]={'ready':False,'message':'Runtime installation/verification is pending.'}
            atomic_json(self.state/'runtime-checks.json',self.runtime_checks)
            self._runtime_cache.clear()
        if action in ('runtime-check','paint-check'):
            kind='comfy' if action=='runtime-check' else 'paint'
            python=comfy.path(comfy.python_exe) if kind=='comfy' else Path(sys.executable)
            if not python.is_file():raise ValueError('Install this runtime before verifying it.')
            args=[str(python),'-u','-m','scripts.model_manager.probe_runtime',kind,str(report_path)]
        elif action == 'runtime':
            from scripts.engine_comfyui import _owned_process, ComfyClient
            if _owned_process(comfy): raise ValueError('Stop the owned ComfyUI host before repairing its environment.')
            try: ComfyClient(comfy).stats()
            except Exception: pass
            else: raise ValueError('A ComfyUI host is running. Stop it before changing its runtime.')
            args = [sys.executable,'-u','-m','scripts.comfyui_host','setup','--skip-models']
        else:
            args = [os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(self.root/'build_paint_extensions.bat')]
        with ExitStack() as stack:
            for key in sorted(self.models):
                try: stack.enter_context(self.lease(key))
                except Timeout: raise ValueError('Wait for active inference before changing a runtime.') from None
            options = {'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
            path = self.state / 'logs' / (job_id+'.installer.log')
            environment = {**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8','PYTHONUNBUFFERED':'1','PIP_PROGRESS_BAR':'off'}
            # Runtime provisioning is explicit; model downloads remain separate jobs.
            with path.open('wb') as output:
                process = subprocess.Popen(args,cwd=self.root,stdout=output,stderr=subprocess.STDOUT,env=environment,**options)
                while process.poll() is None:
                    if self.cancelled(job_id):
                        import psutil
                        parent = psutil.Process(process.pid)
                        for child in reversed(parent.children(recursive=True)):
                            try: child.terminate()
                            except psutil.NoSuchProcess: pass
                        process.terminate(); process.wait(timeout=20)
                        raise Cancelled('Installation cancelled. Runtime may be incomplete; use Install / repair before inference.')
                    self.stop.wait(.3)
            if process.returncode: raise RuntimeError('Installation failed. Open the installation log for the missing prerequisite and retry.')
        if action in ('runtime-check','paint-check'):
            result=json.loads(report_path.read_text(encoding='utf-8'))
            if not result.get('ready'):raise ValueError('Runtime probe did not pass.')
            result['fingerprint']=self.runtime_fingerprint(result['kind'])
            self.runtime_checks[result['kind']]=result
            atomic_json(self.state/'runtime-checks.json',self.runtime_checks)
        elif action in ('runtime','paint-build'):
            self._runtime_job(job_id,'runtime-check' if action=='runtime' else 'paint-check')

    def _host_progress(self, job_id, message):
        if self.cancelled(job_id): raise Cancelled('Host action cancelled at a safe boundary.')
        self.update(job_id,message=message)

    def runtime_configuration(self, config):
        cfg = deepcopy(config)
        roots = {str(self.models_dir/'comfy_models')}
        for key in self.models:
            record = self.record(key)
            if record and key.startswith('comfy-'):
                for version in [record,*record.get('previous',[])]:
                    roots.add(str(Path(version['root'])/'comfy_models') if version.get('root') else version['directory'])
        import yaml
        paths = {}
        for index,root in enumerate(sorted(roots)):
            paths['modelunify_'+str(index)] = {'base_path':str(Path(root)),
                **{folder:folder+'/' for folder in ('diffusion_models','vae','clip_vision','geometry_estimation')}}
        extra = self.state / 'comfy-model-paths.yaml'
        content = yaml.safe_dump(paths,sort_keys=False)
        if not extra.exists() or extra.read_text(encoding='utf-8') != content:
            temporary = extra.with_name(extra.name+'.'+uuid.uuid4().hex+'.tmp')
            temporary.write_text(content,encoding='utf-8'); temporary.replace(extra)
        comfy = cfg.setdefault('model',{}).setdefault('comfyui',{})
        comfy['extra_model_paths'] = str(extra)
        weights = comfy.setdefault('weights',{})
        for key in self.models:
            record = self.record(key)
            if key.startswith('comfy-') and record and record.get('verified') and record.get('comfy_name'):
                weights[key[6:]] = record['comfy_name']
        return cfg

    def freeze(self, stage, settings, images=None):
        keys = self.closure(required_models(stage,settings,images))
        if keys:
            for job in self.jobs():
                if job['state'] in ACTIVE and (job['model']=='runtime' or set(keys).intersection(self.closure([job['model']]))):
                    raise ValueError('A selected model or runtime is being installed/verified. Wait for its Models job to finish before queuing inference.')
        self.assert_ready(keys)
        cfg = self.runtime_configuration(self.config) if any(k.startswith('comfy-') for k in keys) else deepcopy(self.config)
        resources = {key:self.record(key) for key in keys}
        model = cfg.setdefault('model',{})
        if 'triposg' in resources: model.setdefault('triposg',{})['weights_dir'] = resources['triposg']['directory']
        if 'rmbg' in resources: model.setdefault('triposg',{})['rmbg_dir'] = resources['rmbg']['directory']
        if 'hunyuan' in resources: model.setdefault('hunyuan',{})['model_repo'] = resources['hunyuan']['directory']
        return {'configuration':cfg,'model_resources':resources,'model_manager_state':str(self.state),'offline':True}

    def validate_frozen(self, request, stage):
        """Reruns must still refer to verified catalog records, including old revisions.

        A user can register the same bytes at another location without rewriting
        old project provenance. Match immutable content, then bind current paths.
        """
        frozen=request.get('model_resources',{})
        required=self.closure(required_models(stage,request['settings'],request.get('images',{})))
        if set(required)-set(frozen):raise ValueError('The recorded job lacks required model bindings. Queue a new operation after checking Models.')
        rebound={}
        def identity(record):return sorted((f['relative'],f['size'],f['sha256']) for f in record['files'])
        for key,wanted in frozen.items():
            if key not in self.models:raise ValueError('The recorded job uses an unsupported model.')
            record=self.record(key)
            candidates=[record,*record.get('previous',[])] if record else []
            candidate=next((v for v in candidates if v.get('verified') and v['revision']==wanted['revision'] and identity(v)==identity(wanted)),None)
            if not candidate:raise ValueError('A recorded model revision is not registered and verified. Open Models to restore/register the matching files before rerunning.')
            errors=self.runtime_status(self.models[key].runtime,key)
            if errors:raise ValueError('Model runtime is not ready: '+' '.join(errors))
            rebound[key]=candidate
        for job in self.jobs():
            if required and job['state'] in ACTIVE and (job['model']=='runtime' or set(required).intersection(self.closure([job['model']]))):
                raise ValueError('Models is changing a required component. Wait for that installation job before rerunning.')
        cfg=deepcopy(request.get('configuration',self.config))
        if any(key.startswith('comfy-') for key in rebound):
            cfg=self.runtime_configuration(cfg)
            for key,record in rebound.items():
                if key.startswith('comfy-') and record.get('comfy_name'):cfg['model']['comfyui']['weights'][key[6:]]=record['comfy_name']
        model=cfg.setdefault('model',{})
        for key,engine,field in (('triposg','triposg','weights_dir'),('rmbg','triposg','rmbg_dir'),('hunyuan','hunyuan','model_repo')):
            if key in rebound:model.setdefault(engine,{})[field]=rebound[key]['directory']
        request.update(configuration=cfg,model_resources=rebound,model_manager_state=str(self.state),offline=True)
        return request

    def removal_plan(self, key, *, locked=False):
        record = self.record(key)
        versions=[version for version in ([record,*record.get('previous',[])] if record else []) if version.get('owned')]
        if not versions: raise ValueError('Only manager-owned installations can be removed. External caches stay untouched.')
        dependents = [m.name for m in self.models.values() if key in self.closure(m.dependencies) and self.record(m.key)]
        if dependents: raise ValueError('Shared component is required by installed models: '+', '.join(dependents))
        if not locked and self.in_use(key): raise ValueError('Model is in use; wait for the operation to finish.')
        if any(j['state'] in ACTIVE and (j['model']=='runtime' or key in self.closure([j['model']])) for j in self.jobs()):
            raise ValueError('Cancel or finish the installation that uses this component first.')
        files = []
        seen=set()
        for version in versions:
            base = Path(version['root']).resolve()
            for entry in version['files']:
                path = Path(entry['path'])
                if not path.resolve().is_relative_to(base): raise ValueError('Recorded model file escapes its owned model root.')
                try:relative=path.relative_to(base).as_posix()
                except ValueError:relative=path.resolve().relative_to(base).as_posix()  # Windows 8.3 aliases
                checked=target_path(base,relative)
                if str(checked) not in seen:
                    files.append({'path':str(checked),'root':str(base),'bytes':checked.stat().st_size if checked.is_file() else 0})
                    seen.add(str(checked))
        signature = hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()
        return {'model':key,'files':files,'bytes':sum(f['bytes'] for f in files),'signature':signature,
                'note':'Removes recorded owned revisions for this model. Dependencies, external/shared caches and partial downloads are retained.'}

    def remove(self, key, signature):
        with self.lease(key):
            plan = self.removal_plan(key,locked=True)
            if plan['signature'] != signature: raise ValueError('Installation changed; review a fresh removal preview.')
            for item in plan['files']:
                base=Path(item['root'])
                target_path(base,Path(item['path']).relative_to(base).as_posix()).unlink(missing_ok=True)
            record=self.record(key)
            if record.get('owned'):
                with self.db() as db: db.execute('DELETE FROM installations WHERE model=?',(key,))
            else:
                record['previous']=[];self.save_record(key,record)
        self._inventory_cache.clear()
        return f"Removed {len(plan['files'])} owned files. Shared dependencies and external caches were preserved."

    def partial_plan(self, job_id, *, locked=False):
        row=self.job(job_id)
        if row['state'] not in TERMINAL:raise ValueError('Cancel or finish this job before discarding its partial files.')
        data=json.loads(row['request']);base=Path(data['models_dir']).resolve();files=[]
        published=set()
        for model_key in self.models:
            record=self.record(model_key)
            if record:
                for version in [record,*record.get('previous',[])]:
                    published.update(str(Path(f['path']).resolve()) for f in version['files'])
        for key,resolution in data.get('resolutions',{}).items():
            for other in self.jobs():
                if other['state'] in ACTIVE and (other['model']=='runtime' or key in self.closure([other['model']])):
                    raise ValueError('Another installation uses these partial files. Cancel or finish it first.')
            if not locked and self.in_use(key):raise ValueError('The component is busy; wait before discarding partial files.')
            directory=self._destination(key,self.models[key],resolution['revision'],base)
            for entry in resolution['files']:
                final=self._file_path(key,resolution['revision'],directory,entry)
                candidates=[final.with_name(final.name+'.part'),final.with_name(final.name+'.part.json')]
                if str(final.resolve()) not in published:candidates.append(final)
                if self.models[key].source=='github' and final.is_file():
                    try:
                        with zipfile.ZipFile(final) as bundle:
                            for member in bundle.infolist():
                                parts=safe_relative(member.filename.rstrip('/')).parts
                                if len(parts)>1 and not member.is_dir():
                                    path=target_path(directory/'code','/'.join(parts[1:]))
                                    if str(path.resolve()) not in published:candidates.append(path)
                    except zipfile.BadZipFile:pass
                for path in candidates:
                    path=target_path(base,path.relative_to(base).as_posix())
                    if path.is_file():files.append({'path':str(path),'bytes':path.stat().st_size,'mtime':path.stat().st_mtime_ns})
        signature=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
        return {'job':job_id,'files':files,'bytes':sum(f['bytes'] for f in files),'signature':signature,
                'note':'Removes retained temporary files and known uninstalled download files. Published models, unrelated files and external caches stay intact.'}

    def discard_partial(self, job_id, signature):
        row=self.job(job_id);data=json.loads(row['request'])
        with ExitStack() as stack:
            for key in sorted(data.get('resolutions',{})):stack.enter_context(self.lease(key))
            plan=self.partial_plan(job_id,locked=True)
            if plan['signature']!=signature:
                raise ValueError('Partial files changed; review a fresh discard preview.')
            base=Path(data['models_dir']).resolve()
            for item in plan['files']:target_path(base,Path(item['path']).relative_to(base).as_posix()).unlink()
        return 'Discarded retained download files. Published model checkpoints were preserved.'


_MANAGERS = {}
_MANAGERS_LOCK = RLock()

def get_manager(root=None, config=None):
    root = Path(root or Path(__file__).resolve().parents[2]).resolve()
    if config is None:
        import yaml
        config = yaml.safe_load((root/'config.yaml').read_text(encoding='utf-8'))
    state = str((root/config.get('model_manager',{}).get('state_dir','.runtime/model_manager')).resolve())
    with _MANAGERS_LOCK:
        if state not in _MANAGERS: _MANAGERS[state] = Manager(root,config)
        return _MANAGERS[state]
