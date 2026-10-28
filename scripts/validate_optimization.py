"""Compare one-pass/current safeguards against bounded optimization; no AI inference."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mesh",type=Path,help="Existing static single-material mesh; kept intact")
    parser.add_argument("--target",type=int,required=True)
    parser.add_argument("--output",type=Path,required=True,help="A fresh output directory")
    parser.add_argument("--strict",action="store_true",help="Reject an over-budget candidate")
    parser.add_argument("--max-surface-error",type=float,default=2,help="Maximum sampled surface error %% of source diagonal; default 2")
    args=parser.parse_args(argv)
    from scripts.export_contracts import load_static_master,mesh_status
    from scripts.workbench.schema import OptimizationRequest
    from scripts.workbench.projects import digest,atomic_json
    from scripts.workbench.pipelines import execute
    request=OptimizationRequest(target=args.target,strict_budget=args.strict,max_surface_error=args.max_surface_error)
    source=args.mesh.resolve();mesh=load_static_master(source)
    before=digest(source)
    report={"created_at_utc":datetime.now(timezone.utc).isoformat(),"source":str(source),
        "source_sha256":before,"source_inspection":mesh_status(mesh),"runs":[],
        "quality_limit":"Bounds and sampled surface/UV/map/winding checks do not prove every silhouette, thin-part or texture seam is preserved."}
    print(json.dumps({"inspection":report["source_inspection"],"output":str(args.output.resolve()),
        "changes":"Static copy only; topology changes during reduction, originals preserved. UV fallback disabled."}),flush=True)
    args.output.mkdir(parents=True,exist_ok=False)
    path=args.output/"validation.json"
    atomic_json(path,report)
    for name,settings in (("one_pass",OptimizationRequest(target=args.target,max_passes=1,repair_winding=False,max_surface_error=args.max_surface_error)),
                          ("bounded",request)):
        start=time.perf_counter();row={"name":name,"settings":asdict(settings)}
        try:
            output,operation=execute("Optimize",{"mesh":str(source),"settings":{"optimization":asdict(settings)}},
                args.output/name,lambda message,progress:print(f"[{name}] {message}",flush=True))
            row.update(state="completed",output=str(output.resolve()),optimization=operation["optimization"],warnings=operation["warnings"])
        except Exception as error:
            row.update(state="failed",error=f"{type(error).__name__}: {error}")
        row["elapsed_seconds"]=time.perf_counter()-start
        report["runs"].append(row)
        report["source_unchanged"]=digest(source)==before
        atomic_json(path,report)
        print(json.dumps({k:v for k,v in row.items() if k not in ("optimization","settings")}),flush=True)
    report["passed"]=all(r["state"]=="completed" for r in report["runs"]) and report["source_unchanged"]
    atomic_json(path,report)
    print(json.dumps({"passed":report["passed"],"source_unchanged":report["source_unchanged"],"report":str(path.resolve())}))
    return 0 if report["passed"] else 1


if __name__=="__main__":
    raise SystemExit(main())
