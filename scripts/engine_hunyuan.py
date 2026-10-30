"""
Hunyuan3D-2 multi-view engine.

Uses Tencent's `Hunyuan3D-2mv` shape model, which natively accepts a dict of
up to four views — `{'front': ..., 'left': ..., 'back': ..., 'right': ...}` —
and fuses them into one mesh. Geometry only (no painted texture); use the
planar projection helper or Blender for texturing, like with TripoSG.

This module deliberately avoids the `hy3dpaint` texture-painter, which needs
the CUDA Toolkit + MSVC for its custom_rasterizer/DifferentiableRenderer
extensions. Shape pipeline alone works on stock PyTorch wheels.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Union

import numpy as np
import torch
import trimesh
from PIL import Image

import sys
# Always use this checkout, never an editable mapping into a generated bundle.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "Hunyuan3D-2"))
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
from hy3dgen.rembg import BackgroundRemover


ROOT = Path(__file__).resolve().parent.parent
VALID_VIEWS = ("front", "left", "back", "right")


def _load_low_memory(cfg):
    """Use the upstream configuration/checkpoint with PyTorch meta initialization.

    Assign checkpoint tensors directly, avoiding large temporary random CPU weights.
    No model architecture, checkpoint values or inference precision are changed.
    """
    import yaml
    from safetensors.torch import load_file
    from hy3dgen.shapegen.pipelines import instantiate_from_config
    from hy3dgen.shapegen.utils import smart_load_model
    config_path,weights=smart_load_model(cfg.model_repo,cfg.subfolder,True,cfg.variant)
    config=yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    checkpoint=load_file(weights,device="cpu")
    groups={}
    for key,value in checkpoint.items():
        group,name=key.split(".",1)
        groups.setdefault(group,{})[name]=value
    modules={}
    for key in ("model","vae","conditioner"):
        if key=="vae":
            # Upstream intentionally omits encoder weights (decode-only use).
            # Preserve its normal initialization for those missing parameters.
            module=instantiate_from_config(config[key])
        else:
            with torch.device("meta"):
                module=instantiate_from_config(config[key])
        module.load_state_dict(groups[key],strict=key!="vae",assign=True)
        missing=[name for name,value in (*module.named_parameters(),*module.named_buffers()) if value.is_meta]
        if missing:
            raise RuntimeError(f"Checkpoint leaves uninitialized {key} tensors: {missing[:8]}. Disable low_cpu_mem_init for a custom checkpoint.")
        modules[key]=module
    options=dict(model_path=cfg.model_repo,subfolder=cfg.subfolder,use_safetensors=True,
                 variant=cfg.variant,dtype=cfg.torch_dtype,device=cfg.device)
    return Hunyuan3DDiTFlowMatchingPipeline(**modules,
        image_processor=instantiate_from_config(config["image_processor"]),
        scheduler=instantiate_from_config(config["scheduler"]),device=cfg.device,
        dtype=cfg.torch_dtype,from_pretrained_kwargs=options)


@dataclass
class HunyuanConfig:
    model_repo: str = "tencent/Hunyuan3D-2mv"
    subfolder: str = "hunyuan3d-dit-v2-mv"     # use 'hunyuan3d-dit-v2-mv-fast' for guidance-distilled
    variant: str = "fp16"
    device: str = "cuda"
    dtype: str = "float16"
    low_cpu_mem_init: bool = True

    @property
    def torch_dtype(self) -> torch.dtype:
        return torch.float16 if self.dtype == "float16" else torch.float32


class HunyuanMVEngine:
    """Lazy-loaded Hunyuan3D-2mv pipeline. Reused across calls."""

    def __init__(self, cfg: HunyuanConfig):
        from scripts.gpu_lifecycle import register
        register(self)
        self.cfg = cfg
        self._pipe: Optional[Hunyuan3DDiTFlowMatchingPipeline] = None
        self._rembg: Optional[BackgroundRemover] = None

    def load(self, background: bool = True) -> None:
        if self._pipe is not None:
            if background and self._rembg is None:
                self._rembg = self._background_remover()
            return
        print(f"[hunyuan] loading {self.cfg.model_repo}/{self.cfg.subfolder} ({self.cfg.dtype})")
        if self.cfg.low_cpu_mem_init:
            self._pipe=_load_low_memory(self.cfg)
        else:
            self._pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
                self.cfg.model_repo,
                subfolder=self.cfg.subfolder,
                variant=self.cfg.variant,
                device=self.cfg.device,
                dtype=self.cfg.torch_dtype,
            )
        if background:
            self._rembg = self._background_remover()

    @staticmethod
    def _background_remover():
        from scripts.model_manager.integration import onnx_session
        return BackgroundRemover(session=onnx_session('u2net',None,ROOT,None))

    def unload(self) -> None:
        """Free VRAM so a different pipeline can load. Call this between
        shape generation and PBR painting on smaller GPUs (<16 GB)."""
        import gc
        if self._pipe is not None:
            # Dropping ownership frees CUDA tensors. Copying all weights to CPU
            # first needlessly allocates several GiB and can exhaust Windows commit.
            del self._pipe
            self._pipe = None
        if self._rembg is not None:
            del self._rembg
            self._rembg = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        print("[hunyuan] unloaded - VRAM freed")

    # ---------- preprocessing ----------
    def _prep_view(self, image: Union[str, Image.Image]) -> Image.Image:
        """Ensure RGBA with alpha (background removed)."""
        if isinstance(image, (str, Path)):
            img = Image.open(image).convert("RGBA")
        else:
            img = image
            if img.mode != "RGBA":
                img = img.convert("RGBA")
        # rembg expects RGB to extract alpha; if alpha is already 0 everywhere, run rembg.
        alpha = np.asarray(img.split()[-1])
        if alpha.min() == 255 and alpha.max() == 255:
            assert self._rembg is not None, "Call load() first"
            img = self._rembg(img)
        return img

    # ---------- inference ----------
    @torch.inference_mode()
    def generate_multiview(
        self,
        views: Dict[str, Union[str, Image.Image]],
        *,
        seed: int = 12345,
        num_inference_steps: int = 50,
        octree_resolution: int = 380,
        num_chunks: int = 20000,
        guidance_scale: float = 5.0,
        mc_level: float = 0.0,
        box_v: float = 1.01,
        preprocessed: bool = False,
    ) -> trimesh.Trimesh:
        """Generate a mesh from 1–4 named views.

        Parameters
        ----------
        views               : dict with keys from {'front','left','back','right'}.
                              Missing views are simply not provided; partial sets work.
        seed                : random seed for reproducibility.
        num_inference_steps : diffusion steps (25 fast / 50 balanced / 75 HQ).
        octree_resolution   : voxel grid resolution (256 fast / 380 balanced / 512 HQ).
        num_chunks          : decoder memory chunk size; lower if you hit OOM.
        guidance_scale      : strictness to input views; lower = more creative.
        mc_level            : marching-cubes iso-surface level (0.0 is default;
                              positive = thinner surface, negative = thicker).
        box_v               : bounding-box scale (1.01 is canonical).
        """
        bad = [k for k in views if k not in VALID_VIEWS]
        if bad:
            raise ValueError(f"Invalid view name(s): {bad}. Must be a subset of {VALID_VIEWS}")
        if not views:
            raise ValueError("No views supplied — provide at least one.")
        self.load(background=not preprocessed)
        assert self._pipe is not None

        # Explicit preparation is authoritative, including intentionally opaque images.
        # Preserve the legacy automatic remover for existing CLI callers.
        prepared: Dict[str, Image.Image] = {
            k: v.convert("RGBA") if preprocessed else self._prep_view(v) for k, v in views.items()
        }

        mesh = self._pipe(
            image=prepared,
            num_inference_steps=num_inference_steps,
            octree_resolution=octree_resolution,
            num_chunks=num_chunks,
            guidance_scale=guidance_scale,
            mc_level=mc_level,
            box_v=box_v,
            generator=torch.manual_seed(seed),
            output_type="trimesh",
        )[0]
        return mesh


def engine_from_config(cfg: dict) -> HunyuanMVEngine:
    h = (cfg.get("model", {}) or {}).get("hunyuan", {}) or {}
    from scripts.model_manager.service import get_manager
    record=get_manager(ROOT,cfg).record('hunyuan')
    if record and record.get('verified') and not Path(h.get('model_repo','')).is_absolute():h={**h,'model_repo':record['directory']}
    return HunyuanMVEngine(HunyuanConfig(
        model_repo=h.get("model_repo", "tencent/Hunyuan3D-2mv"),
        subfolder=h.get("subfolder", "hunyuan3d-dit-v2-mv"),
        variant=h.get("variant", "fp16"),
        device=h.get("device", "cuda" if torch.cuda.is_available() else "cpu"),
        dtype=h.get("dtype", "float16"),
        low_cpu_mem_init=bool(h.get("low_cpu_mem_init",True)),
    ))
