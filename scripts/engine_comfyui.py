"""Local ComfyUI transport and owned Windows hosting; no Comfy imports in the UI.

Uses the native core 3D nodes. Only loopback endpoints are accepted. Server
processes, checkpoint environments and cached weights stay separate from ours.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path, PurePosixPath
from urllib import request as http, parse, error
from io import BytesIO
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid

from scripts.comfyui_workflows import BACKENDS, WEIGHTS, ComfyRequest, build_workflow, check_graph

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ComfyConfig:
    url: str = "http://127.0.0.1:8188"
    server_dir: str = ".runtime/comfyui/ComfyUI"
    python_exe: str = ".runtime/comfyui/python/Scripts/python.exe"
    autostart: bool = True
    startup_timeout: float = 180.
    job_timeout: float = 7200.
    request_timeout: float = 30.
    poll_interval: float = 1.
    memory_mode: str = "auto"
    unload_after_job: bool = True
    weights: dict = field(default_factory=dict)

    def __post_init__(self):
        url = parse.urlsplit(self.url)
        if (url.scheme != "http" or url.hostname not in ("127.0.0.1","localhost","::1")
                or url.username or url.password or url.path not in ("", "/") or url.query or url.fragment):
            raise ValueError("ComfyUI URL must be a local http://127.0.0.1:PORT endpoint.")
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError("Invalid ComfyUI port.")
        self.url = self.url.rstrip("/")
        if self.memory_mode not in ("auto","lowvram","normalvram","highvram"):
            raise ValueError("Unsupported ComfyUI memory mode.")
        for key in ("startup_timeout","job_timeout","request_timeout","poll_interval"):
            from scripts.workbench.schema import checked_number
            setattr(self,key,checked_number(getattr(self,key),.05,86400,key))
        if set(self.weights) - set(WEIGHTS):
            raise ValueError("Unknown ComfyUI weight configuration key.")

    def path(self, value):
        return (ROOT / value).resolve()


def config_from_dict(config):
    return ComfyConfig(**config.get("model",{}).get("comfyui",{}))


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, config):
        self.cfg = config
        # A user's global HTTP proxy must never receive local images or jobs.
        self.opener = http.build_opener(http.ProxyHandler({}))

    def call(self, route, data=None, *, method=None, content_type="application/json"):
        payload = json.dumps(data).encode() if data is not None and not isinstance(data,bytes) else data
        req = http.Request(self.cfg.url+route,data=payload,method=method,
                           headers={"Content-Type":content_type,"Accept":"application/json"})
        try:
            with self.opener.open(req,timeout=self.cfg.request_timeout) as response:
                payload = response.read()
                return json.loads(payload) if payload.strip() else {}
        except error.HTTPError as exc:
            detail = exc.read(16384).decode("utf-8",errors="replace")
            raise ComfyError(f"ComfyUI {route}: HTTP {exc.code}: {detail}") from exc
        except (OSError,ValueError) as exc:
            raise ComfyError(f"ComfyUI unavailable at {self.cfg.url}: {exc}") from exc

    def stats(self):
        result = self.call("/system_stats")
        if not isinstance(result,dict) or "system" not in result or "devices" not in result:
            raise ComfyError("Endpoint is not a compatible ComfyUI server.")
        return result

    def upload(self, image, name):
        stream = BytesIO()
        image.save(stream,format="PNG")
        data = stream.getvalue()
        boundary = "ModelUnify"+uuid.uuid4().hex
        payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}.png"\r\n'
                   'Content-Type: image/png\r\n\r\n').encode()+data
        for key,value in (("type","input"),("subfolder","modelunify"),("overwrite","false")):
            payload += f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}'.encode()
        payload += f"\r\n--{boundary}--\r\n".encode()
        result = self.call("/upload/image",payload,content_type="multipart/form-data; boundary="+boundary)
        path = PurePosixPath(result.get("subfolder", ""))/result["name"]
        if path.is_absolute() or ".." in path.parts or "\\" in str(path) or ":" in str(path):
            raise ComfyError("ComfyUI returned an invalid upload path.")
        return path.as_posix(), hashlib.sha256(data).hexdigest()

    def cancel(self, prompt_id):
        """Never send an unscoped global interrupt to somebody else's workflow."""
        try:
            return self.call("/api/jobs/"+parse.quote(prompt_id,safe="")+"/cancel",{})
        except ComfyError:
            # Old releases cannot atomically cancel an executing prompt. Remove
            # our pending item only; an executing result is discarded locally.
            self.call("/queue",{"delete":[prompt_id]})
            return {"cancelled":False,"note":"No targeted cancellation API; running result will be ignored."}

    def download(self, record, output, prefix):
        filename = record.get("filename", "")
        subfolder = record.get("subfolder", "").replace("\\", "/")
        remote = PurePosixPath(subfolder)/filename
        if (not filename or PurePosixPath(filename).name != filename or "\\" in filename or ":" in str(remote)
                or remote.is_absolute() or ".." in remote.parts or record.get("type") != "output"
                or remote.suffix.lower() != ".glb" or not remote.is_relative_to(PurePosixPath(prefix))):
            raise ComfyError("ComfyUI returned an unsafe or unrelated GLB artifact.")
        url = self.cfg.url+"/view?"+parse.urlencode({"filename":filename,"subfolder":subfolder,"type":"output"})
        output = Path(output)
        temporary = output.with_suffix(".glb.part")
        try:
            with self.opener.open(url,timeout=self.cfg.request_timeout) as response, temporary.open("wb") as stream:
                total = 0
                while chunk := response.read(1024*1024):
                    total += len(chunk)
                    if total > 2*1024**3:
                        raise ComfyError("ComfyUI GLB exceeds the 2 GiB transfer limit.")
                    stream.write(chunk)
            import struct
            with temporary.open("rb") as stream:
                header = stream.read(12)
            if len(header)!=12 or header[:4]!=b"glTF" or struct.unpack("<II",header[4:]) != (2,temporary.stat().st_size):
                raise ComfyError("ComfyUI artifact is not a complete GLB 2 file.")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        return output

    def execute(self, graph, outputs, folder, prefix, checkpoint):
        from scripts.workbench.projects import atomic_json
        prompt_id = None
        folder = Path(folder)
        atomic_json(folder/"comfy_workflow.json",graph)
        from scripts.comfyui_progress import LiveProgress
        client_id=uuid.uuid4().hex;live=LiveProgress(self.cfg.url,client_id,graph).connect()
        try:
            checkpoint("Submitting native ComfyUI workflow",.2)
            result = self.call("/prompt",{"prompt":graph,"client_id":client_id})
            if result.get("error") or result.get("node_errors") or not result.get("prompt_id"):
                raise ComfyError("ComfyUI rejected the workflow: "+json.dumps(result))
            prompt_id = result["prompt_id"]
            live.prompt_id=prompt_id
            atomic_json(folder/"comfy_prompt.json",{"prompt_id":prompt_id,"url":self.cfg.url})
            started = time.monotonic()
            sampled=0.
            while True:
                label,progress=live.poll()
                checkpoint(f"ComfyUI processing · {label.removeprefix('ComfyUI · ')} · {int(time.monotonic()-started)}s",progress)
                if time.monotonic()-sampled>=5:
                    try:live.sample_memory(self.stats())
                    except ComfyError:pass
                    atomic_json(folder/"comfy_live.json",live.snapshot());sampled=time.monotonic()
                history = self.call("/history/"+parse.quote(prompt_id,safe=""))
                item = history.get(prompt_id)
                if item:
                    atomic_json(folder/"comfy_history.json",item)
                    status = item.get("status",{})
                    failures = [m for m in status.get("messages",[]) if isinstance(m,list) and m and m[0] in ("execution_error","execution_interrupted")]
                    if status.get("status_str") == "error" or failures:
                        raise ComfyError("ComfyUI execution failed: "+json.dumps(failures or status,ensure_ascii=False)[-6000:])
                    if status.get("completed"):
                        break
                if time.monotonic()-started > self.cfg.job_timeout:
                    raise TimeoutError("ComfyUI job exceeded its configured timeout.")
                time.sleep(self.cfg.poll_interval)
            checkpoint("Downloading generated GLBs",.85)
            saved = {}
            for role,node_id in outputs.items():
                records = item.get("outputs",{}).get(node_id,{}).get("3d",[])
                if len(records)!=1:
                    raise ComfyError(f"Expected exactly one {role} GLB from {node_id}; found {len(records)}.")
                path = folder/("master.glb" if role=="master" else "asset.glb")
                self.download(records[0],path,prefix)
                saved[role] = path
            return saved,{"prompt_id":prompt_id,"server":self.cfg.url,"duration_seconds":time.monotonic()-started,"live_progress":live.snapshot()}
        except BaseException:
            if prompt_id:
                try:
                    result = self.cancel(prompt_id)
                    atomic_json(folder/"comfy_cancellation.json",result)
                except Exception as exc:
                    atomic_json(folder/"comfy_cancellation.json",{"error":str(exc),"prompt_id":prompt_id})
            raise
        finally:
            live.close()


def _state_paths(config):
    root = ROOT/".runtime"/"comfyui"/"hosts"
    key = hashlib.sha256(config.url.encode()).hexdigest()[:16]
    return root/(key+".json"),root/(key+".log")


def _owned_process(config):
    import psutil
    path,_ = _state_paths(config)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        process = psutil.Process(state["pid"])
        args = process.cmdline()
        expected = str(config.path(config.server_dir)/"main.py")
        if (abs(process.create_time()-state["created"]) > .1 or expected not in args
                or process.cwd() != str(config.path(config.server_dir))):
            return None
        return process
    except (psutil.Error,OSError,ValueError,KeyError):
        return None


def start_host(config, checkpoint=lambda message,progress:None):
    """Attach a compatible server or launch one hidden, without modifying packages."""
    client = ComfyClient(config)
    try:
        return client.stats()
    except ComfyError:
        pass
    from filelock import FileLock
    from scripts.workbench.projects import atomic_json
    state,log = _state_paths(config)
    state.parent.mkdir(parents=True,exist_ok=True)
    with FileLock(str(state)+".lock",timeout=10):
        try:
            return client.stats()
        except ComfyError:
            pass
        process = _owned_process(config)
        if process is None:
            script = config.path(config.server_dir)/"main.py"
            python = config.path(config.python_exe)
            if not script.is_file() or not python.is_file():
                raise ComfyError("ComfyUI runtime is not installed. Run scripts/comfyui_host.py setup or configure its directory and Python in config.yaml.")
            url = parse.urlsplit(config.url)
            args = [str(python),"-u",str(script),"--listen",url.hostname,"--port",str(url.port or 80),"--disable-auto-launch"]
            if config.memory_mode != "auto":
                args.append("--"+config.memory_mode)
            options = {"creationflags":subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {}
            with log.open("ab") as stream:
                child = subprocess.Popen(args,cwd=script.parent,stdout=stream,stderr=subprocess.STDOUT,
                                         env={**os.environ,"PYTHONUTF8":"1","PYTHONIOENCODING":"utf-8"},**options)
            import psutil
            process = psutil.Process(child.pid)
            atomic_json(state,{"pid":child.pid,"created":process.create_time(),"url":config.url,"script":str(script),"log":str(log)})
        started = time.monotonic()
        while time.monotonic()-started < config.startup_timeout:
            checkpoint("Starting isolated ComfyUI host",.04)
            if not process.is_running():
                raise ComfyError(f"ComfyUI stopped during startup. Inspect {log}")
            try:
                return client.stats()
            except ComfyError:
                time.sleep(.5)
        raise ComfyError(f"ComfyUI did not become ready. Inspect {log}")


def stop_host(config):
    process = _owned_process(config)
    if process is None:
        return "No ModelUnify-owned ComfyUI process to stop. External servers remain running."
    queue = ComfyClient(config).call("/queue")
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise ComfyError("ComfyUI still has jobs. Cancel/wait before stopping its host.")
    # Windows venv python.exe may be a redirector whose actual interpreter is
    # a child. Terminate the verified host's process tree, not just the wrapper.
    import psutil
    owned = process.children(recursive=True)
    for child in reversed(owned):
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    process.terminate()
    _,alive = psutil.wait_procs([*owned,process],timeout=15)
    if alive:
        raise ComfyError("Owned ComfyUI processes did not finish stopping; inspect the host log.")
    return "ModelUnify-owned ComfyUI host stopped."


class ComfyEngine:
    def __init__(self, config):
        self.cfg = config
        self.client = ComfyClient(config)

    def readiness(self, request):
        result = {"server":self.cfg.url,"backend":request.backend,"ready":False,
                  "requested_memory_policy":self.cfg.memory_mode,
                  "active_offload_status":"Not exposed by the native host API; inspect host logs. Memory values are measured separately.",
                  "weights_downloaded_automatically":False,"runtime_installed":self.cfg.path(self.cfg.python_exe).is_file(),
                  "managed_by_modelunify":bool(_owned_process(self.cfg))}
        try:
            result["system"] = self.client.stats()
            info = self.client.call("/object_info")
            images = {"front":"modelunify/readiness.png"}
            if request.multiview:
                images.update(left="modelunify/left.png",back="modelunify/back.png",right="modelunify/right.png")
            graph,_ = build_workflow(request,images,"modelunify/readiness",self.cfg.weights)
            # Input filenames do not exist yet during a read-only readiness check.
            check_graph({k:v for k,v in graph.items() if v["class_type"]!="LoadImage"},info)
            result["ready"] = True
            result["note"] = "Nodes and checkpoint selections available; inference not yet validated."
        except (ComfyError,ValueError) as exc:
            result["message"] = str(exc)
        return result

    def generate(self, images, request, folder, checkpoint):
        try:
            output,report = self._generate(images,request,folder,checkpoint)
        except BaseException:
            # Failed/cancelled jobs must not leave our idle host occupying the GPU
            # when the next job uses a native ModelUnify engine.
            try:
                self._release_idle()
            except Exception:
                pass
            raise
        try:
            report["unload_requested"] = self._release_idle()
        except ComfyError as exc:
            report.setdefault("warnings",[]).append(f"Generation completed, but host unload failed: {exc}")
        return output,report

    def _release_idle(self):
        if self.cfg.unload_after_job and _owned_process(self.cfg):
            q = self.client.call("/queue")
            if not q.get("queue_running") and not q.get("queue_pending"):
                self.client.call("/free",{"unload_models":True,"free_memory":True})
                return True
        return False

    def _generate(self, images, request, folder, checkpoint):
        from scripts.workbench.projects import atomic_json, digest
        folder = Path(folder)
        if self.cfg.autostart:
            stats = start_host(self.cfg,checkpoint)
        else:
            stats = self.client.stats()
        info = self.client.call("/object_info")
        prefix = "modelunify/"+uuid.uuid4().hex
        uploads, hashes = {},{}
        for direction,image in images.items():
            checkpoint(f"Uploading {direction} to local ComfyUI",.1)
            uploads[direction],hashes[direction] = self.client.upload(image,uuid.uuid4().hex+"_"+direction)
        graph,outputs = build_workflow(request,uploads,prefix,self.cfg.weights)
        check_graph(graph,info)
        schema = {key:info[key] for key in sorted({n["class_type"] for n in graph.values()})}
        atomic_json(folder/"comfy_node_schemas.json",schema)
        paths,report = self.client.execute(graph,outputs,folder,prefix,checkpoint)
        # Master bytes are retained; only inspect, never silently flatten/repaint.
        from scripts.export_contracts import load_static_master, mesh_status
        import numpy as np
        master = load_static_master(paths["master"])
        if not len(master.faces) or not np.isfinite(master.vertices).all():
            raise ComfyError("ComfyUI returned empty or nonfinite geometry; no preview published.")
        report["master_inspection"] = mesh_status(master)
        report.update(requested=asdict(request),input_sha256=hashes,master_sha256=digest(paths["master"]),
                      server_system=stats,workflow_sha256=digest(folder/"comfy_workflow.json"),
                      checkpoint_names={**WEIGHTS,**self.cfg.weights},unload_requested=False)
        if request.multiview:
            report["camera_contract"] = "Fixed orbit: front/left/back/right, 90 degrees apart, equal scale/framing, supplied horizontal FOV; not arbitrary camera calibration."
        return paths["result"],report


def engine_from_config(config):
    return ComfyEngine(config_from_dict(config))
