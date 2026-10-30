"""Freeze checked resources for workers; loading models never installs them."""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import json
import os
from filelock import FileLock, Timeout
from functools import wraps
from .service import get_manager


def directory(key, *, root=None, config=None):
    frozen = json.loads(os.environ.get('MODELUNIFY_RESOURCES','{}'))
    if key in frozen: return Path(frozen[key])
    manager = get_manager(root,config)
    status = manager.status(key)
    if not status['downloaded']:
        raise ValueError(f"{status['name']} is not installed and verified. Open Models to install it; no download was started.")
    return Path(status['location'])


@contextmanager
def use_resources(frozen):
    """Worker-only environment. Locks protect active inference against removal."""
    resources = frozen.get('model_resources',{})
    state = Path(frozen['model_manager_state'])
    with ExitStack() as stack:
        for key in sorted(resources):
            try: stack.enter_context(FileLock(str(state/'leases'/(key+'.lock')),timeout=0))
            except Timeout: raise RuntimeError('A required model is being changed. Wait for installation to finish, then rerun.') from None
            record = resources[key]
            for item in record['files']:
                path = Path(item['path'])
                if not path.is_file() or path.stat().st_size != item['size']:
                    raise RuntimeError('A queued model installation changed. Open Models to verify/repair it before rerunning.')
        environment = {'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
                       'MODELUNIFY_RESOURCES':json.dumps({k:v['directory'] for k,v in resources.items()})}
        for key,variable in (('paint','MODELUNIFY_PAINT_PATH'),('dinov2','MODELUNIFY_DINO_PATH'),('marigold','MODELUNIFY_MARIGOLD_PATH'),
                             ('stablenormal','MODELUNIFY_STABLE_WEIGHTS'),('stablenormal-code','MODELUNIFY_STABLE_CODE')):
            if key in resources: environment[variable] = resources[key]['directory']
        if 'realesrgan' in resources:
            environment['MODELUNIFY_REALESRGAN_PATH'] = str(Path(resources['realesrgan']['directory'])/'RealESRGAN_x4plus.pth')
        previous = {key:os.environ.get(key) for key in environment}
        os.environ.update(environment)
        try: yield
        finally:
            for key,value in previous.items():
                if value is None: os.environ.pop(key,None)
                else: os.environ[key] = value


def onnx_session(name, providers, root, config):
    """Use rembg's installed session class without its implicit pooch download."""
    import onnxruntime as ort
    from rembg.sessions import sessions_class
    manager = get_manager(root,config)
    key = 'rembg-'+name
    manager.assert_ready([key])
    path = directory(key,root=root,config=config)/(name+'.onnx')
    original = next((cls for cls in sessions_class if cls.name()==name),None)
    if original is None: raise ValueError('The installed rembg version does not support the selected model.')
    class InstalledSession(original):
        @classmethod
        def download_models(cls,*args,**kwargs): return str(path)
    return InstalledSession(name,ort.SessionOptions(),providers=providers)


def preparation_resources(fn):
    @wraps(fn)
    def run(image,options,root,config):
        from .catalog import required_models
        manager=get_manager(root,config)
        keys=manager.closure(required_models('Prepare',{'preparation':options.to_dict()},{'front':image}))
        held=json.loads(os.environ.get('MODELUNIFY_RESOURCES','{}'))
        with ExitStack() as locks:
            for key in sorted(keys):
                if key in held:continue
                try:locks.enter_context(manager.lease(key))
                except Timeout:raise ValueError('Background model is busy. Wait for its installation to finish.') from None
            manager.assert_ready(keys)
            return fn(image,options,root,config)
    return run
