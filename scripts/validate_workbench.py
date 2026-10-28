"""Repeat real workbench jobs through isolated workers; outputs must be fresh.

Example: python -m scripts.validate_workbench --front photo.png --output .runtime/gpu-check --repeat 2 --paint --backend all --offline
This uses diagnostic settings, not a production quality benchmark. Keep other GPU jobs idle.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import os
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--front",type=Path,required=True)
    for direction in ("left","back","right"):
        parser.add_argument("--"+direction,type=Path,help="Optional named Hunyuan view; TripoSG still uses front only")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--repeat",type=int,default=2)
    parser.add_argument("--steps",type=int,default=15)
    parser.add_argument("--paint",action="store_true")
    parser.add_argument("--background",choices=("none","rmbg","rembg"),default="none",help="Real shared preparation provider for the supplied views")
    parser.add_argument("--backend",choices=("multiview","triposg","all"),default="multiview")
    parser.add_argument("--offline",action="store_true")
    parser.add_argument("--weights-root",type=Path,help="Explicit existing weights directory for relocated TripoSG diagnostics; no weights are copied")
    args=parser.parse_args()
    if args.repeat<1 or not 15<=args.steps<=75:parser.error("Use positive --repeat and 15–75 steps.")
    if not args.front.is_file():parser.error("The reference image does not exist.")
    view_paths={direction:getattr(args,direction) for direction in ("front","left","back","right") if getattr(args,direction)}
    if any(not path.is_file() for path in view_paths.values()):parser.error("A supplied view image does not exist.")
    if args.output.exists():parser.error("--output must be a fresh directory; existing results are preserved.")
    if args.offline:
        os.environ["HF_HUB_OFFLINE"]="1"
        os.environ["TRANSFORMERS_OFFLINE"]="1"
    from PIL import Image
    from scripts.workbench.jobs import JobQueue
    from scripts.workbench.projects import ProjectStore,atomic_json
    from scripts.workbench import runtime
    from scripts._version import MODELUNIFY_VERSION
    if args.weights_root:
        weights=args.weights_root.resolve()
        if not (weights/"TripoSG").is_dir():parser.error("--weights-root must contain TripoSG/.")
        runtime.CFG["model"]["triposg"]["weights_dir"]=str(weights/"TripoSG")
        runtime.CFG["model"]["triposg"]["rmbg_dir"]=str(weights/"RMBG-1.4")
    output=args.output.resolve()
    store=ProjectStore(output/"projects")
    queue=JobQueue(output/"jobs.sqlite3",store)
    settings=dict(t_steps=args.steps,t_guidance=7.,t_octree=8,t_dense=7,t_bounds=1.25,t_bg="none",
        t_seed=42,t_faces=5000,t_planar=True,m_steps=args.steps,m_octree=256,m_guidance=5.,m_chunks=10000,
        m_level=0.,m_seed=42,m_faces=5000,m_bake="front",m_paint=False,m_box=1.01,
        p_views=4,p_resolution=512,p_render="512",p_texture="1024",p_exponent=4,p_merge="fast",
        p_remesh=True,p_maps=True,p_low=True,normal="off",preparation={"provider":args.background,"size":512,"margin":.05})
    report={"version":MODELUNIFY_VERSION,"diagnostic_settings":True,"executable":sys.executable,
            "source_root":str(ROOT),"external_weights_root":str(args.weights_root.resolve()) if args.weights_root else None,
            "input":str(args.front.resolve()),
            "input_sha256":hashlib.sha256(args.front.read_bytes()).hexdigest(),
            "views":{name:{"path":str(path.resolve()),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
                     for name,path in view_paths.items()},"runs":[]}
    backends=(["Hunyuan3D-2mv"] if args.backend=="multiview" else ["TripoSG 1.5B"] if args.backend=="triposg" else ["Hunyuan3D-2mv","TripoSG 1.5B"])
    for index in range(args.repeat):
        for backend in backends:
            settings["backend"]=backend
            project=store.create(f"validation_{index}_{backend}")
            pixels={}
            for direction,path in view_paths.items():
                if backend=="TripoSG 1.5B" and direction!="front":continue
                with Image.open(path) as image:pixels[direction]=image.copy()
            pixels["reference"]=pixels["front"]
            manifest=store.snapshot(project,settings,pixels)
            images={k:str(store.resolve(project,v["original"])) for k,v in manifest["inputs"].items()}
            mesh=None
            for stage in (["Generate","Texture"] if args.paint else ["Generate"]):
                job=queue.submit(project,stage,{"settings":settings,"images":images,"mesh":mesh})
                started=time.monotonic()
                print(f"{index+1}/{args.repeat}: {backend} / {stage} / {job}",flush=True)
                queue.run(queue.get(job))
                row=queue.get(job)
                row["elapsed_seconds"]=time.monotonic()-started
                report["runs"].append(row)
                atomic_json(output/"validation.json",report)
                print(row["state"]+": "+row["message"],flush=True)
                if row["state"]!="completed":return 1
                mesh=row["result"]
    print(f"Validation report: {output/'validation.json'}")
    return 0

if __name__=="__main__":raise SystemExit(main())
