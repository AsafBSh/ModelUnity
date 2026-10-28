"""Private subprocess entry point: native CUDA failures cannot take down the UI."""
from pathlib import Path
import json
import os
import sys
import traceback
from threading import Event,Thread
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

def main():
    request_path,stage,output,status_path,cancel_path,result_path=sys.argv[1:]
    frozen=json.loads(Path(request_path).read_text(encoding="utf-8"))
    if frozen.get("offline"):
        os.environ["HF_HUB_OFFLINE"]="1";os.environ["TRANSFORMERS_OFFLINE"]="1"
    from scripts.workbench.projects import atomic_json,now
    from scripts.workbench.pipelines import execute
    from scripts.workbench.jobs import Cancelled
    output_folder=Path(output)
    stop=Event()
    memory_path=Path(status_path).with_name(Path(status_path).name.replace(".progress.json",".memory.json"))
    def memory_sample():
        import torch
        import psutil
        while not stop.is_set():
            try:
                sample={"time":now(),"worker_pid":os.getpid(),"host_rss_bytes":psutil.Process().memory_info().rss}
                live=output_folder/"comfy_live.json"
                if live.is_file():sample["comfy_host"]=json.loads(live.read_text(encoding="utf-8"))
                if torch.cuda.is_available():
                    free,total=torch.cuda.mem_get_info()
                    sample.update(device_free_bytes=free,device_total_bytes=total,
                        torch_allocated_bytes=torch.cuda.memory_allocated(),torch_reserved_bytes=torch.cuda.memory_reserved(),
                        torch_peak_allocated_bytes=torch.cuda.max_memory_allocated())
                atomic_json(memory_path,sample)
            except Exception:pass
            stop.wait(1)
    sampler=Thread(target=memory_sample,daemon=True)
    sampler.start()
    def checkpoint(message,progress):
        if Path(cancel_path).exists():
            raise Cancelled("Cancelled at a safe boundary; output was not published.")
        sample={"time":now(),"message":message,"progress":progress,"pid":os.getpid()}
        import torch
        if torch.cuda.is_available():
            free,total=torch.cuda.mem_get_info()
            sample["gpu"]={"device_free_bytes":free,"device_total_bytes":total,
                           "torch_allocated_bytes":torch.cuda.memory_allocated(),"torch_reserved_bytes":torch.cuda.memory_reserved()}
        atomic_json(status_path,sample)
        print(f"[{progress:.0%}] {message}",flush=True)
    try:
        request=json.loads(Path(request_path).read_text(encoding="utf-8"))
        if request.get("configuration"):
            from scripts.workbench import runtime
            runtime.CFG=request["configuration"]
        output,report=execute(stage,request,output,checkpoint)
        import torch
        if torch.cuda.is_available():
            report["worker_peak_torch_allocated_bytes"]=torch.cuda.max_memory_allocated()
            atomic_json(Path(output).parent/"worker_memory.json",{"peak_torch_allocated_bytes":torch.cuda.max_memory_allocated()})
        atomic_json(output_folder/"operation.json",report)
        atomic_json(result_path,{"state":"completed","output":str(output),"report":report})
        return 0
    except Cancelled as exc:
        atomic_json(result_path,{"state":"cancelled","message":str(exc)})
        return 0
    except Exception as exc:
        traceback.print_exc()
        atomic_json(result_path,{"state":"failed","message":f"{type(exc).__name__}: {exc}"})
        return 1
    finally:
        stop.set()
        sampler.join(timeout=2)

if __name__=="__main__":raise SystemExit(main())
