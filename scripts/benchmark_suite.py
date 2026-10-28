"""Benchmark all four generators through the real workbench queue and frozen inputs."""
from pathlib import Path
import argparse
import json
import os
import shutil
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.workbench.benchmarking import MODELS,benchmark_settings
from scripts.workbench.projects import ProjectStore,atomic_json,digest
from scripts.workbench.input_readiness import check_inputs


def load_cases(path,selected=None):
    document=json.loads(Path(path).read_text(encoding="utf-8"));cases=[]
    if selected and selected-{c["name"] for c in document["cases"]}:raise ValueError("Unknown benchmark case selection.")
    for case in document["cases"]:
        if selected and case["name"] not in selected:continue
        if not case.get("views") or set(case["views"])-{"front","left","back","right"}:raise ValueError("Invalid benchmark views.")
        case={**case,"views":{k:str((ROOT/v).resolve()) for k,v in case["views"].items()}}
        for value in case["views"].values():
            if not Path(value).is_file():raise ValueError(f"Benchmark reference missing: {value}")
        cases.append(case)
    if not cases:raise ValueError("No matching benchmark cases.")
    return cases


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite",type=Path,default=ROOT/"benchmarks/objects.json")
    parser.add_argument("--cases",help="Comma-separated case names; default: all")
    parser.add_argument("--models",default=",".join(MODELS))
    parser.add_argument("--profile",choices=["quick","quality"],default="quick")
    parser.add_argument("--faces",type=int,default=20000)
    parser.add_argument("--repeat",type=int,default=1)
    parser.add_argument("--seed",type=int,default=42)
    parser.add_argument("--bg",choices=["none","rembg","rmbg"],default="rembg")
    parser.add_argument("--offline",action="store_true")
    parser.add_argument("--plan",action="store_true",help="Validate cases/settings without inference or output writes")
    parser.add_argument("--timeout",type=float,default=14400)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args();models=args.models.split(",")
    if any(m not in MODELS for m in models) or len(set(models))!=len(models):parser.error("Choose unique triposg,hunyuan,trellis,pixal models.")
    if args.repeat<1 or args.repeat>100:parser.error("Repeat must be 1–100.")
    if args.timeout<=0 or not 0<=args.seed<=2147483647:parser.error("Timeout must be positive and seed must be 0–2147483647.")
    cases=load_cases(args.suite,set(args.cases.split(",")) if args.cases else None)
    rows=[]
    for case in cases:
        for model in models:
            settings=benchmark_settings(model,args.profile,args.faces,{"provider":args.bg,"size":1024})
            for key in ("t_seed","m_seed","c_seed"):settings[key]=args.seed
            readiness=check_inputs(settings,case["views"])
            if readiness["errors"]:raise ValueError(f"{case['name']}/{model}: "+" ".join(readiness["errors"]))
            for repeat in range(args.repeat):rows.append({"case":case["name"],"category":case.get("category"),"model":model,"iteration":repeat,
                "settings":settings,"images":case["views"],"input_sha256":{k:digest(v) for k,v in case["views"].items()},"input_checks":readiness,
                "quality_review":{"silhouette":None,"symmetry":None,"thin_parts":None,"dimensions":None,"notes":"Manual 1–5 scores pending; normalized dimensions are not real-world accuracy."}})
    if args.plan:
        print(json.dumps({"planned_runs":len(rows),"cases":[c["name"] for c in cases],"models":models,"profile":args.profile},indent=2));return 0
    if args.output is None:parser.error("A fresh --output directory is required.")
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    from scripts.workbench import runtime
    from scripts.workbench.jobs import JobQueue
    from PIL import Image
    store=ProjectStore(ROOT/runtime.CFG.get("paths",{}).get("workbench_projects_dir","projects"))
    queue=JobQueue(ROOT/runtime.CFG.get("paths",{}).get("workbench_runtime_dir",".runtime/workbench_preview")/"jobs.sqlite3",store)
    try:queue.start()
    except RuntimeError as exc:
        if "owns this job queue" not in str(exc):raise
        print("Using the running workbench queue; benchmark jobs respect its existing order.",flush=True)
    report={"profile":args.profile,"configuration":runtime.CFG,"offline":args.offline,"runs":rows,
        "comparison_contract":"Same source references/preparation/seed/working face target. Single-image models use Front; Hunyuan uses supplied views. Model-specific quality controls differ; quick is not production-quality certification."}
    atomic_json(output/"benchmark.json",report);failed=False
    for row in rows:
        folder=store.create(f"benchmark_{row['case']}_{row['model']}_{row['iteration']}")
        images={}
        for name,path in row["images"].items():
            with Image.open(path) as image:images[name]=image.copy()
        manifest=store.snapshot(folder,row["settings"],images)
        request={"settings":row["settings"],"images":{k:str(store.resolve(folder,v["original"])) for k,v in manifest["inputs"].items()},"mesh":None,"offline":args.offline,
                 "benchmark":{"case":row["case"],"iteration":row["iteration"],"category":row["category"]}}
        job=queue.submit(folder,"Generate",request);row.update(job_id=job,project=str(folder),status="queued")
        started=time.monotonic();last=None
        try:
            while True:
                state=queue.get(job)
                if state["message"]!=last:
                    print(f"{row['case']}/{row['model']}: {state['message']}",flush=True);last=state["message"]
                if state["state"] in ("completed","failed","cancelled","interrupted"):break
                if time.monotonic()-started>args.timeout:queue.cancel(job);raise TimeoutError("Benchmark job timeout; cancellation requested for this job only.")
                time.sleep(.5)
        except (KeyboardInterrupt,TimeoutError) as exc:
            queue.cancel(job);row.update(status="cancellation_requested",message=str(exc),queue_and_execution_seconds=time.monotonic()-started)
            atomic_json(output/"benchmark.json",report);raise
        row.update(status=state["state"],message=state["message"],queue_and_execution_seconds=time.monotonic()-started)
        if state["state"]=="completed":
            destination=output/f"{row['case']}_{row['model']}_{row['iteration']}";source=Path(state["result"]).parent
            shutil.copytree(source,destination)
            row["artifacts"]=str(destination.relative_to(output));row["operation"]=json.loads((source/"operation.json").read_text(encoding="utf-8"))
        else:failed=True
        atomic_json(output/"benchmark.json",report)
    return int(failed)


if __name__=="__main__":raise SystemExit(main())
