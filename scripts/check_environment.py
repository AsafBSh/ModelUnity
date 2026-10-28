"""Offline import and UI-construction checks. Does not launch a server/inference."""

import argparse
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ui", action="store_true", help="Also construct the Gradio Blocks UI"
    )
    parser.add_argument(
        "--require-paint",
        action="store_true",
        help="Fail when paint prerequisites are unavailable",
    )
    args = parser.parse_args()
    import torch
    import fast_simplification
    from scripts import engine_hunyuan, engine_paint

    report = {
        "python": sys.version,
        "executable": sys.executable,
        "packages": {
            p: metadata.version(p)
            for p in (
                "torch",
                "torchvision",
                "gradio",
                "diffusers",
                "transformers",
                "mmgp",
                "optimum-quanto",
            )
        },
        "cuda": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "hunyuan_source": __import__("hy3dgen").__file__,
        "hunyuan_engine_source": engine_hunyuan.__file__,
        "rasterizer_import": engine_paint.rasterizer_ready(),
        "realesrgan_checkpoint": (
            engine_paint.PAINT_DIR / "ckpt/RealESRGAN_x4plus.pth"
        ).is_file(),
    }
    if torch.cuda.is_available():
        report["gpu"] = torch.cuda.get_device_name(0)
    try:
        from textureGenPipeline import Hunyuan3DPaintPipeline
        from realesrgan import RealESRGANer
        from mmgp import offload
        # This lazy model import is used at paint initialization. Importing only
        # textureGenPipeline misses its Lightning dependency until real inference.
        from hunyuanpaintpbr import HunyuanPaint

        report["paint_import"] = True
        report["paint_pipeline_module"] = Hunyuan3DPaintPipeline.__module__
        report["paint_model_module"] = HunyuanPaint.__module__
        report["super_resolution_module"] = RealESRGANer.__module__
        report["mmgp_release_available"] = hasattr(offload.offload, "release")
        try:
            from DifferentiableRenderer import mesh_inpaint_processor

            report["native_mesh_inpaint"] = True
            report["native_mesh_inpaint_source"] = mesh_inpaint_processor.__file__
        except ImportError:
            report["native_mesh_inpaint"] = False
    except Exception as exc:
        report["paint_import"] = False
        report["paint_import_error"] = f"{type(exc).__name__}: {exc}"
    if args.ui:
        from scripts.web_ui import _ui

        ui = _ui()
        report["ui_components"] = len(ui.blocks)
        ui.close()
    print(json.dumps(report, indent=2))
    if sys.version_info[:2] != (3, 11) or metadata.version("gradio") != "6.17.3":
        return 1
    if args.require_paint and not all(
        report[k]
        for k in (
            "cuda_available",
            "rasterizer_import",
            "realesrgan_checkpoint",
            "paint_import",
        )
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
