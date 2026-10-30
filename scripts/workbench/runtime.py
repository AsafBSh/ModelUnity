"""Configuration and lazy model factories shared without importing a UI."""
from pathlib import Path
from functools import lru_cache
import base64
import sys
if sys.platform=="win32":
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,"reconfigure"):
            stream.reconfigure(encoding="utf-8",errors="replace")
import yaml
import torch
from .schema import TRIPOSG_PRESETS, HUNYUAN_MV_PRESETS, PAINT_PRESETS

ROOT = Path(__file__).resolve().parents[2]
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
OUT_DIR = ROOT / CFG.get("paths", {}).get("outputs_dir", "outputs")
BMS_DIR = ROOT / CFG.get("paths", {}).get("bms_export_dir", "bms_export")
PAINT_LOW_VRAM_DEFAULT = CFG.get("model", {}).get("paint", {}).get("low_vram_mode", True)

@lru_cache
def shape_engine(single=False):
    if single:
        from scripts.engine import engine_from_config
    else:
        from scripts.engine_hunyuan import engine_from_config
    return engine_from_config(CFG)

def model_config(single=False):
    from scripts.comfyui_workflows import BACKENDS
    from scripts.model_manager.service import get_manager
    manager=get_manager(ROOT,CFG)
    if isinstance(single,str) and single in BACKENDS:
        config = CFG.get("model",{}).get("comfyui",{})
        key='comfy-trellis' if single==BACKENDS[0] else 'comfy-pixal'
        return {"configuration":config,"model":single,"runtime":"Separate native Windows ComfyUI host",
                "installation":manager.status(key),
                "support":{"NVIDIA CUDA":"integration target; see Check host for actual readiness",
                           "AMD / Intel GPU":"not validated in ModelUnify"},
                "capabilities":{"input":"one image; Pixal3D optionally 1–4 fixed-orbit directions",
                                "output":"retained master GLB + optional PBR GLB"},
                "weights":"Explicitly installed Comfy-Org checkpoints; no automatic download during Generate",
                "note":"Original research stacks are Linux-first; this adapter uses current native ComfyUI core nodes on Windows."}
    config = CFG["model"]["triposg" if single else "hunyuan"]
    status=manager.status('triposg' if single else 'hunyuan')
    weights=status['location'] or config.get('weights_dir',config.get('model_repo'))
    return {"configuration":config,"weights":weights,"weights_detected_locally":status['downloaded'],"installation":status,
            "capabilities":{"input_views":1 if single else "1–4 named directions", "output":"static geometry; optional planar projection", "PBR":"separate Hunyuan3D-2.1 Paint stage"},
            "support":{"NVIDIA CUDA":"supported","CPU":"slow shape fallback","AMD ROCm / Intel XPU":"not integrated"},
            "requirements":"VRAM depends on extraction settings. Estimates are not measured usage; see live telemetry and job logs.",
            "availability_check":"Read-only filesystem/cache metadata; no weights loaded or downloaded."}

def _load_logo_data_url():
    path = ROOT / "assets" / "logo.png"
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode() if path.exists() else None

def _bms_lod_targets():
    cfg = CFG.get("bms_lods", {})
    return [(f"Model_{i}", int(cfg.get(f"lod{i}_faces", n))) for i, n in enumerate((40000,8000,3000,1000,400,150,60))]

def _build_lod_targets(count, *budgets):
    from .schema import checked_number
    count = checked_number(count, 1, 7, "LOD count", True)
    return [(f"Model_{i}", checked_number(budgets[i], 1, 10000000, "LOD budget", True)) for i in range(count)]

def _normal_baker_default():
    return "low"
