"""Repeatable offline-capable shape/paint benchmark; never reuses an output folder."""

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend", choices=("triposg", "multiview"), default="multiview"
    )
    for view in ("front", "left", "back", "right"):
        parser.add_argument("--" + view, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument(
        "--octree",
        type=int,
        default=380,
        help="MV octree resolution; TripoSG uses --octree-depth",
    )
    parser.add_argument("--octree-depth", type=int, default=9)
    parser.add_argument("--paint", action="store_true")
    parser.add_argument(
        "--normal", choices=("off", "low", "medium", "high"), default="off"
    )
    parser.add_argument("--render-size", type=int, default=1024)
    parser.add_argument("--texture-size", type=int, default=2048)
    parser.add_argument("--views", type=int, default=6)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Require cached models; prohibit HF downloads",
    )
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    views = {
        key: str(getattr(args, key).resolve())
        for key in ("front", "left", "back", "right")
        if getattr(args, key)
    }
    if not views:
        parser.error("Provide at least one view")
    if args.backend == "triposg" and "front" not in views:
        parser.error("TripoSG requires --front")
    if args.output.exists():
        parser.error("Output must be a fresh directory")
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    import psutil
    from scripts.engine import load_config, engine_from_config
    from scripts.engine_hunyuan import engine_from_config as mv_from_config
    from scripts.engine_paint import painter_from_config
    from scripts.export_contracts import mesh_status
    from scripts.gpu_lifecycle import operation

    cfg = load_config()
    args.output.mkdir(parents=True)
    report = {
        "settings": vars(args).copy(),
        "config": cfg,
        "os": platform.platform(),
        "python": sys.version,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "cuda_runtime": torch.version.cuda,
        "packages": {
            p: metadata.version(p)
            for p in ("torch", "gradio", "diffusers", "transformers", "mmgp")
        },
        "inputs": {
            k: {"path": v, "sha256": hashlib.sha256(Path(v).read_bytes()).hexdigest()}
            for k, v in views.items()
        },
        "runs": [],
    }

    def save():
        (args.output / "benchmark.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )

    @operation()
    def run(row, run_dir):
        started = time.perf_counter()
        engine = (
            mv_from_config(cfg)
            if args.backend == "multiview"
            else engine_from_config(cfg)
        )
        try:
            mesh = (
                engine.generate_multiview(
                    views,
                    seed=args.seed,
                    num_inference_steps=args.steps,
                    octree_resolution=args.octree,
                )
                if args.backend == "multiview"
                else engine.generate(
                    views["front"],
                    seed=args.seed,
                    num_inference_steps=args.steps,
                    octree_depth=args.octree_depth,
                )
            )
            mesh.export(run_dir / "shape.glb")
            row["shape_seconds"] = time.perf_counter() - started
            row["geometry"] = mesh_status(mesh)
        finally:
            engine.unload()
        if args.paint:
            painter = painter_from_config(cfg)
            painter.cfg.render_size = args.render_size
            painter.cfg.texture_size = args.texture_size
            painter.cfg.max_num_view = args.views
            paint_start = time.perf_counter()
            painter.paint(
                run_dir / "shape.glb",
                views.get("front", next(iter(views.values()))),
                run_dir / "painted.glb",
            )
            row["paint_seconds"] = time.perf_counter() - paint_start
            row["mmgp_applied"] = painter.last_mmgp_applied
            row["paint_warnings"] = painter.load_warnings
            if args.normal != "off":
                from scripts.web_ui import _embed_normal_map_in_glb

                normal_start = time.perf_counter()
                _embed_normal_map_in_glb(run_dir / "painted.glb", args.normal)
                row["normal_seconds"] = time.perf_counter() - normal_start
                sidecar = run_dir / "painted.normal_bake.json"
                row["normal_result"] = (
                    json.loads(sidecar.read_text())
                    if sidecar.exists()
                    else "skipped/failed"
                )

    save()
    failed = False
    for i in range(args.repeat):
        row = {
            "iteration": i,
            "quality_review": {
                "silhouette": None,
                "facade_alignment": None,
                "texture_seams": None,
                "lod_popping": None,
                "notes": "Manual review pending; score 1–5 with identical camera/lighting.",
            },
        }
        report["runs"].append(row)
        run_dir = args.output / f"run_{i}"
        run_dir.mkdir()
        if torch.cuda.is_available():
            row["allocated_before_bytes"] = torch.cuda.memory_allocated()
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        try:
            run(row, run_dir)
            row["status"] = "success"
        except Exception as exc:
            import traceback

            row["status"] = "failed"
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["traceback"] = traceback.format_exc()
            failed = True
        finally:
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                row["peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
                row["peak_reserved_bytes"] = torch.cuda.max_memory_reserved()
                row["allocated_after_cleanup_bytes"] = torch.cuda.memory_allocated()
            row["elapsed_seconds"] = time.perf_counter() - started
            row["default_device_after_cleanup"] = str(torch.get_default_device())
            row["process_rss_bytes"] = psutil.Process().memory_info().rss
            save()
            print(json.dumps(row, default=str), flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
