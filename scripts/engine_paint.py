"""
Hunyuan3D-2.1 PBR texture painter engine.

Wraps Hunyuan3DPaintPipeline from vendor/Hunyuan3D-2.1.
Produces a textured .glb with:
  - Albedo texture map
  - MR (Metallic/Roughness) texture map
  - Automatic UV unwrap via xatlas

Requirements before using:
  - custom_rasterizer compiled: run build_paint_extensions.bat
  - DifferentiableRenderer compiled: same batch (optional but recommended)
  - RealESRGAN weights: vendor/Hunyuan3D-2.1/hy3dpaint/ckpt/RealESRGAN_x4plus.pth
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PAINT_DIR = ROOT / "vendor" / "Hunyuan3D-2.1" / "hy3dpaint"


def _save_png_maps(mesh, output_path):
    """Additional lossless maps; native OBJ/JPG companions remain intact."""
    from scripts.workbench.materials import _extract_textures
    output_path=Path(output_path)
    geometries=list(mesh.geometry.values()) if hasattr(mesh,"geometry") else [mesh]
    written=[]
    for index,geometry in enumerate(geometries):
        maps=_extract_textures(geometry)
        if "metallic_roughness" in maps:
            packed=maps["metallic_roughness"].convert("RGB")
            maps.update(roughness=packed.getchannel("G"),metallic=packed.getchannel("B"))
        prefix=output_path.stem+(f"_material_{index}" if len(geometries)>1 else "")
        for key,image in maps.items():
            target=output_path.with_name(f"{prefix}_{key}.png")
            image.save(target);written.append(target)
    return written

# Add hy3dpaint paths to sys.path so internal relative imports work.
# Order matters: DifferentiableRenderer must come BEFORE hy3dpaint so that
# `from DifferentiableRenderer.mesh_utils import ...` resolves correctly.
for _p in [
    str(PAINT_DIR / "DifferentiableRenderer"),
    str(PAINT_DIR),
    str(ROOT / "vendor" / "Hunyuan3D-2.1"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Apply torchvision compatibility shim BEFORE basicsr/realesrgan are imported.
# basicsr imports torchvision.transforms.functional_tensor which was removed in
# torchvision 0.15+. The fix lives in hy3dpaint/utils/torchvision_fix.py.
try:
    from utils.torchvision_fix import fix_torchvision_functional_tensor
    fix_torchvision_functional_tensor()
except Exception:
    pass


# Patch huggingface_hub's symlink creation to fall back to copying on Windows
# when symlinks fail (WinError 1314). This avoids the need for Developer Mode
# or admin privileges. Cost: ~2x disk usage (no dedup), but reliable.
def _patch_hf_symlinks():
    import sys
    if sys.platform != "win32":
        return
    try:
        import shutil
        import huggingface_hub.file_download as _hfd

        _orig = _hfd._create_symlink

        def _safe_symlink(src, dst, new_blob=False):
            try:
                return _orig(src, dst, new_blob=new_blob)
            except OSError as e:
                # WinError 1314 = "A required privilege is not held by the client"
                if getattr(e, "winerror", None) == 1314 or "1314" in str(e):
                    import os
                    abs_src = os.path.abspath(os.path.join(os.path.dirname(dst), src)) \
                              if not os.path.isabs(src) else src
                    if os.path.exists(dst):
                        try: os.remove(dst)
                        except OSError: pass
                    shutil.copy2(abs_src, dst)
                    return
                raise

        _hfd._create_symlink = _safe_symlink
    except Exception:
        pass


_patch_hf_symlinks()


def _attach_extra_pbr_maps(mesh, work_dir, obj_stem: str) -> None:
    """Find metallic/roughness/normal JPGs in `work_dir` (written by Hunyuan-2.1
    painter) and attach them to `mesh.visual.material` as glTF PBR maps. The
    next GLB export then carries full PBR data instead of only albedo.

    glTF expects metallicRoughness combined into ONE image:
        R channel = (unused, often occlusion)
        G channel = roughness
        B channel = metallic

    The painter writes them as two separate grayscale JPGs; we combine here.
    """
    import numpy as _np
    from PIL import Image as _Image
    import trimesh as _trimesh

    # #region agent log
    import json as _json, time as _time
    from pathlib import Path as _P
    def _dbg(loc, msg, data, hyp="HE"):
        try:
            _entry = {"sessionId": "c02a0e",
                      "id": f"log_{int(_time.time()*1000)}_{loc}",
                      "timestamp": int(_time.time() * 1000),
                      "location": loc, "message": msg, "data": data,
                      "hypothesisId": hyp}
            _log = _P(__file__).resolve().parent.parent / "debug-c02a0e.log"
            with open(_log, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps(_entry) + "\n")
        except Exception: pass
    # #endregion

    vis = getattr(mesh, "visual", None)
    # #region agent log
    _dbg("engine_paint.py:_attach_extra_pbr_maps:entry",
         "Called _attach_extra_pbr_maps",
         {"work_dir": str(work_dir), "obj_stem": obj_stem,
          "vis_type": type(vis).__name__,
          "is_TextureVisuals": isinstance(vis, _trimesh.visual.TextureVisuals),
          "initial_material_class": type(getattr(vis, "material", None)).__name__})
    # #endregion
    if not isinstance(vis, _trimesh.visual.TextureVisuals):
        return
    mat = getattr(vis, "material", None)
    if mat is None:
        return

    # Trimesh's OBJ loader produces SimpleMaterial (a basic Phong material),
    # which has no concept of PBR maps. Convert to PBRMaterial so the GLB
    # writer actually serializes metallicRoughnessTexture and normalTexture.
    # Confirmed by log line "material_class": "SimpleMaterial" + the round-trip
    # showing MR / normal as "missing" after a `final.export(.glb)`.
    if not isinstance(mat, _trimesh.visual.material.PBRMaterial):
        diffuse_img = getattr(mat, "image", None) or getattr(mat, "baseColorTexture", None)
        new_pbr = _trimesh.visual.material.PBRMaterial(
            name=getattr(mat, "name", "material"),
            baseColorTexture=diffuse_img,
            metallicFactor=1.0,
            roughnessFactor=1.0,
            doubleSided=True,
        )
        vis.material = new_pbr
        mat = new_pbr

    work_dir = Path(work_dir)

    def _find(suffix: str):
        for ext in (".jpg", ".jpeg", ".png"):
            p = work_dir / f"{obj_stem}{suffix}{ext}"
            if p.exists():
                return p
        return None

    m_path = _find("_metallic")
    r_path = _find("_roughness")
    n_path = _find("_normal")
    # #region agent log
    _dbg("engine_paint.py:_attach_extra_pbr_maps:scan",
         "PBR file scan results",
         {"metallic_found": str(m_path) if m_path else None,
          "roughness_found": str(r_path) if r_path else None,
          "normal_found": str(n_path) if n_path else None,
          "work_dir_listing": [p.name for p in work_dir.iterdir()] if work_dir.exists() else []})
    # #endregion
    if m_path is not None and r_path is not None:
        m_img = _Image.open(m_path).convert("L")
        r_img = _Image.open(r_path).convert("L")
        if r_img.size != m_img.size:
            r_img = r_img.resize(m_img.size, _Image.LANCZOS)
        m_arr = _np.array(m_img)
        r_arr = _np.array(r_img)
        # R=occlusion(255 default), G=roughness, B=metallic
        mr_arr = _np.stack([
            _np.full_like(m_arr, 255),
            r_arr,
            m_arr,
        ], axis=-1)
        mat.metallicRoughnessTexture = _Image.fromarray(mr_arr)
        # Make the factors permissive so the textures fully drive the values.
        try:
            mat.metallicFactor = 1.0
            mat.roughnessFactor = 1.0
        except Exception:
            pass

    if n_path is not None:
        mat.normalTexture = _Image.open(n_path).convert("RGB")

    # #region agent log
    _dbg("engine_paint.py:_attach_extra_pbr_maps:after_attach",
         "Material state after attach",
         {"baseColorTexture": "set" if getattr(mat, "baseColorTexture", None) is not None else "none",
          "metallicRoughnessTexture": "set" if getattr(mat, "metallicRoughnessTexture", None) is not None else "none",
          "normalTexture": "set" if getattr(mat, "normalTexture", None) is not None else "none",
          "material_class": type(mat).__name__})
    # #endregion


def _check_rasterizer() -> bool:
    """Return True if custom_rasterizer_kernel is compiled and importable."""
    try:
        import torch  # must be imported first so Windows finds the CUDA DLLs in torch\lib\  # noqa: F401
        import custom_rasterizer_kernel  # noqa: F401
        return True
    except (ImportError, OSError):
        return False


@dataclass
class PaintConfig:
    max_num_view: int = 6           # How many virtual views to render for baking (4–6 is good)
    resolution: int = 512           # Diffusion resolution per view (256/384/512)
    use_remesh: bool = True         # Remesh before painting (strongly recommended)
    # Upstream defaults are 2048 / 4096 which trigger 5-10 min cv2.inpaint calls
    # on a 12 GB laptop GPU. We lower defaults to keep runs under ~3 min.
    render_size: int = 1024         # Internal render resolution per virtual view
    texture_size: int = 2048        # Final UV texture map size (1024/2048/4096/8192)
    bake_exp: int = 4               # Exponent controlling view-blending sharpness when baking
    merge_method: str = "fast"      # "fast" or "max" - how multi-view bakes are merged
    save_separate_maps: bool = False  # If True, also export albedo / metallic / roughness / normal as PNGs
    # Hunyuan-2.1 paint normally needs ~21 GB VRAM. With low_vram_mode the
    # multiview diffusion pipeline is wrapped in mmgp's LowRAM_LowVRAM profile
    # (profile 4), which swaps weights between system RAM and VRAM during
    # inference. mmgp profile 4 targets >=32 GB system RAM + >=12 GB VRAM
    # and runs ~20-30% slower than the full-VRAM path. Required on cards with
    # <16 GB VRAM; harmless on bigger GPUs but unnecessary.
    low_vram_mode: bool = False
    safe_cpu_checkpoint_io: bool = True


class Hunyuan3DPainter:
    """Lazy-loaded PBR texture painter. Call load() before paint()."""

    def __init__(self, cfg: PaintConfig):
        from scripts.gpu_lifecycle import register
        register(self)
        self.cfg = cfg
        self._pipeline = None
        self._offload = None
        self._previous_default_device = None
        self._dll_handles = []
        # Set during load() so callers (Gradio handlers, CLI) can echo the
        # actual mmgp state back to the user. Without this, the only signal
        # that mmgp failed silently is a buried [paint] WARN line in the
        # terminal - the Gradio status box never sees it.
        self.mmgp_applied: bool = False
        self.last_mmgp_applied: bool = False
        self.load_warnings: list[str] = []
        self.last_view_count = None

    def _assert_rasterizer(self):
        if not _check_rasterizer():
            raise RuntimeError(
                "custom_rasterizer_kernel is unavailable. Run build_paint_extensions.bat "
                "with VS2022 Build Tools and a CUDA Toolkit matching torch.version.cuda."
            )

    def load(self):
        if self._pipeline is not None:
            return
        # Reset per-load state so a fresh load() (e.g. after unload()) doesn't
        # inherit warnings from a previous run with different settings.
        self.mmgp_applied = self.last_mmgp_applied = False
        self.load_warnings = []
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("PBR painting requires NVIDIA CUDA; CPU painting is unsupported.")
        self._assert_rasterizer()
        # Ensure Windows can find CUDA + torch DLLs before importing native extensions.
        import os, sys
        _cuda_bin = os.path.join(os.environ.get("CUDA_HOME") or os.environ.get("CUDA_PATH", ""), "bin")
        if os.path.isdir(_cuda_bin) and _cuda_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _cuda_bin + os.pathsep + os.environ.get("PATH", "")
            if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
                self._dll_handles.append(os.add_dll_directory(_cuda_bin))
        import torch  # must come before any native extension import on Windows
        _torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(_torch_lib) and sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            self._dll_handles.append(os.add_dll_directory(_torch_lib))
        from textureGenPipeline import Hunyuan3DPaintPipeline, Hunyuan3DPaintConfig
        print("[paint] Loading installed Hunyuan3D-2.1 paint pipeline (offline)...")
        cfg = Hunyuan3DPaintConfig(
            max_num_view=self.cfg.max_num_view,
            resolution=self.cfg.resolution,
        )
        # Override the upstream defaults with our PaintConfig advanced parameters.
        cfg.render_size = int(self.cfg.render_size)
        cfg.texture_size = int(self.cfg.texture_size)
        cfg.bake_exp = int(self.cfg.bake_exp)
        cfg.merge_method = str(self.cfg.merge_method)
        # Resolve the pipeline's relative paths to absolute ones, otherwise it
        # will look for them relative to the user's current working directory.
        v21_root = ROOT / "vendor" / "Hunyuan3D-2.1"
        cfg.multiview_cfg_path = str(v21_root / "hy3dpaint" / "cfgs" / "hunyuan-paint-pbr.yaml")
        cfg.realesrgan_ckpt_path = str(v21_root / "hy3dpaint" / "ckpt" / "RealESRGAN_x4plus.pth")
        from scripts.model_manager.integration import directory
        cfg.multiview_pretrained_path = str(directory('paint',root=ROOT))
        cfg.dino_ckpt_path = str(directory('dinov2',root=ROOT))
        cfg.realesrgan_ckpt_path = str(directory('realesrgan',root=ROOT)/'RealESRGAN_x4plus.pth')

        # Sanity-check both paths early with clear errors.
        for p, name in [(cfg.multiview_cfg_path, "multiview config"),
                        (cfg.realesrgan_ckpt_path, "RealESRGAN checkpoint")]:
            if not os.path.exists(p):
                raise FileNotFoundError(f"{name} not found: {p}")

        # Low-VRAM mode: keep the heavy diffusion components on CPU during
        # construction so mmgp can manage their VRAM footprint at inference
        # time. This is the recommended Tencent path for <16 GB cards
        # (Hunyuan3D-2.1 issue #15).
        if self.cfg.low_vram_mode:
            try:
                cfg.device = "cpu"
                print("[paint] low_vram_mode=True: pipeline will load on CPU; "
                      "mmgp will swap weights to VRAM only during inference.")
            except Exception as _e:
                print(f"[paint] WARN: could not set device=cpu on Hunyuan3DPaintConfig: {_e}")

        # Retain ownership during __init__ too: upstream can allocate some GPU
        # models before a later checkpoint/import failure aborts construction.
        self._pipeline = Hunyuan3DPaintPipeline.__new__(Hunyuan3DPaintPipeline)
        from scripts.checkpoint_io import windows_dino_checkpoint_io
        with windows_dino_checkpoint_io(self.cfg.safe_cpu_checkpoint_io):
            Hunyuan3DPaintPipeline.__init__(self._pipeline, cfg)

        # Apply mmgp LowRAM_LowVRAM profile to the multiview diffusion pipeline.
        # This is what actually makes the painter fit on a 12 GB GPU; without
        # it, just setting device=cpu above would only delay the OOM until the
        # first .to('cuda') call inside the pipeline.
        if self.cfg.low_vram_mode:
            try:
                from mmgp import offload, profile_type   # type: ignore
                multiview = self._pipeline.models["multiview_model"]
                core_pipe = multiview.pipeline
                components = dict(core_pipe.components)
                # DINO is outside the diffusers pipeline. Leaving it out runs
                # the giant image encoder on CPU under config.device='cpu'.
                if getattr(multiview, "dino_v2", None) is not None:
                    components["dino_encoder"] = multiview.dino_v2
                previous_offload = offload.last_offload_obj
                self._previous_default_device = torch.get_default_device()
                try:
                    self._offload = offload.profile(components, profile_type.LowRAM_LowVRAM)
                except Exception:
                    # profile() can create a global offloader before it fails.
                    if offload.last_offload_obj is not previous_offload:
                        self._offload = offload.last_offload_obj
                    raise
                self.mmgp_applied = self.last_mmgp_applied = True
                print("[paint] mmgp LowRAM_LowVRAM (profile 4) applied to "
                      "multiview pipeline. Targets >=12 GB VRAM + >=32 GB "
                      "system RAM; actual memory and runtime depend on settings.")
            except ImportError:
                _w = ("Low-VRAM mode requested but `mmgp` is not installed. "
                      "Install with `pip install mmgp` to enable CPU<->VRAM "
                      "weight offload. Paint will stop because requested offload is unavailable.")
                self.load_warnings.append(_w)
                print(f"[paint] WARN: {_w}")
            except Exception as _e:
                _w = (f"Low-VRAM mode requested but the mmgp profile failed "
                      f"to apply: {_e}. Paint will stop because requested offload is unavailable.")
                self.load_warnings.append(_w)
                print(f"[paint] WARN: {_w}")

        if self.cfg.low_vram_mode and not self.mmgp_applied:
            self.unload()
            raise RuntimeError("Requested mmgp offload is unavailable; paint stopped. " + " ".join(self.load_warnings))

        # Wrap the inner methods of view_processor with a stopwatch so users
        # see WHERE time is being spent. Diffusion shows its own tqdm bar;
        # the silent killers are usually super-resolution and cv2.inpaint.
        self._patch_stage_timing(self._pipeline)
        select_views=self._pipeline.view_processor.bake_view_selection
        def measured_views(*args,**kwargs):
            result=select_views(*args,**kwargs)
            self.last_view_count=len(result[0])
            return result
        self._pipeline.view_processor.bake_view_selection=measured_views
        print("[paint] Pipeline loaded.")

    def unload(self) -> None:
        """Free VRAM. Call after painting if you'll do other GPU work."""
        import gc, torch as _torch
        if self._offload is not None:
            try:
                self._offload.release()
            except Exception as exc:
                print(f"[paint] WARN: mmgp release failed: {exc}")
            finally:
                self._offload = None
        # mmgp 3.7.6 changes torch's process/thread default to CUDA and its
        # release() does not restore it. Subsequent scheduler constructors
        # expect CPU tensors for NumPy conversion, including a second paint.
        if self._previous_default_device is not None:
            _torch.set_default_device(self._previous_default_device)
            self._previous_default_device = None
        self.mmgp_applied = False
        for handle in self._dll_handles:
            handle.close()
        self._dll_handles.clear()
        if self._pipeline is not None:
            try:
                # Move models to CPU first, then drop them.
                if hasattr(self._pipeline, "models"):
                    for k, m in list(self._pipeline.models.items()):
                        components = (m, getattr(m, 'pipeline', None),
                                      getattr(m, 'dino_v2', None),
                                      getattr(getattr(m, 'upsampler', None), 'model', None))
                        for component in components:
                            try:
                                if hasattr(component, 'to'):
                                    component.to('cpu')
                            except Exception:
                                pass
                    # Exception tracebacks may still retain the upstream object.
                    # Clear its ownership too, including render buffers.
                    self._pipeline.models.clear()
                self._pipeline.render = None
                self._pipeline.view_processor = None
            except Exception:
                pass
            del self._pipeline
            self._pipeline = None
        gc.collect()
        if _torch.cuda.is_available():
            _torch.cuda.empty_cache()
            _torch.cuda.ipc_collect()
        print("[paint] unloaded - VRAM freed")

    @staticmethod
    def _patch_stage_timing(pipeline) -> None:
        """Wrap a Hunyuan3DPaintPipeline's inner methods with a stopwatch so users
        can see exactly where time goes. The slowest stage is usually cv2.inpaint
        of the final 2K/4K texture, NOT the diffusion itself."""
        import time as _t
        vp = pipeline.view_processor
        sm = pipeline.models.get("super_model")

        # Idempotent: don't double-wrap if load() is called more than once.
        if getattr(vp.texture_inpaint, "_stage_wrapped", False):
            return

        state = {"t0": None}

        def _stage(label: str):
            now = _t.time()
            if state["t0"] is None:
                state["t0"] = now
                last = now
            else:
                last = state.get("last", now)
            state["last"] = now
            total = now - state["t0"]
            print(f"[paint][{total:6.1f}s elapsed] -> {label}", flush=True)

        def _wrap(fn, label):
            def w(*a, **kw):
                _stage(label)
                return fn(*a, **kw)
            w._stage_wrapped = True
            return w

        vp.render_normal_multiview   = _wrap(vp.render_normal_multiview,
                                             "render normal-maps (GPU rasterizer)")
        vp.render_position_multiview = _wrap(vp.render_position_multiview,
                                             "render position-maps (GPU rasterizer)")
        vp.bake_from_multiview       = _wrap(vp.bake_from_multiview,
                                             "bake textures from views")
        vp.texture_inpaint           = _wrap(vp.texture_inpaint,
            f"cv2.inpaint UV seams at {pipeline.config.texture_size}^2 - CPU-only, this is the slow step")

        if sm is not None and hasattr(sm, "__call__") and not getattr(sm, "_stage_wrapped", False):
            _orig_sm = sm.__call__
            def w_sm(*a, **kw):
                _stage("RealESRGAN super-resolution (per view)")
                return _orig_sm(*a, **kw)
            try:
                sm.__call__ = w_sm
                sm._stage_wrapped = True
            except Exception:
                pass  # bound to type, can't patch instance — ignore.

    def paint(self, *args, **kwargs):
        try:
            return self._paint(*args, **kwargs)
        finally:
            self.unload()

    def _paint(
        self,
        mesh_path: Union[str, Path],
        reference_image: Union[str, Path, Image.Image],
        output_path: Optional[Union[str, Path]] = None,
        keep_intermediate: bool = False,
    ) -> Path:
        """
        Paint `mesh_path` using `reference_image` as the style reference.
        Returns the path to the output .glb (textured).

        The asset folder model
        ----------------------
        The PARENT of `output_path` is treated as the asset's dedicated
        folder. The Hunyuan-2.1 painter natively emits a Wavefront bundle
        (OBJ + MTL + albedo / metallic / roughness JPGs) and we re-package
        that into a single .glb. All of these artifacts now land directly
        in the asset folder, so the user gets BOTH editable formats in one
        place:

            outputs/<asset_name>/
              <asset_name>.glb                          (this output_path)
              <asset_name>_textured.obj                 (editable Wavefront)
              <asset_name>_textured.mtl
              <asset_name>_textured.jpg                  (albedo)
              <asset_name>_textured_metallic.jpg
              <asset_name>_textured_roughness.jpg

        mesh_path         : .glb or .obj file generated by TripoSG / Hunyuan3D
                            shape pipeline
        reference_image   : the source photo you used to generate the mesh
                            (front view)
        output_path       : where to save the textured .glb. Its PARENT is
                            the asset folder; its STEM is used as the prefix
                            for the painter's OBJ + MTL + texture files
                            (so `<output_path.stem>_textured.obj` etc.).
                            Defaults to <mesh_stem>_textured.glb beside the
                            input mesh.
        keep_intermediate : if True, keep ALL files the Hunyuan pipeline
                            writes (including its internal scratch files
                            like `white_mesh_remesh.obj` and the pre-paint
                            input OBJ). Defaults to FALSE - the known
                            redundant intermediates are removed on success
                            so the asset folder only contains the actual
                            deliverables. The user-facing painter outputs
                            (OBJ + MTL + textures) are ALWAYS kept; this
                            flag only controls disposal of scratch files.
        """
        import os, shutil, trimesh, torch

        mesh_path = Path(mesh_path)
        if not mesh_path.exists():
            raise FileNotFoundError(f"Input mesh not found: {mesh_path}")

        if output_path is None:
            # Default: place the asset folder next to the input mesh.
            asset_dir = mesh_path.parent / mesh_path.stem
            output_path = asset_dir / f"{mesh_path.stem}.glb"
        output_path = Path(output_path)

        if output_path.resolve() == mesh_path.resolve():
            raise ValueError("Paint output must differ from the input master.")
        # The painter emits fixed scratch names in this directory too.
        planned = [output_path, output_path.with_suffix(".obj"),
                   output_path.with_name("white_mesh_remesh.obj")]
        planned += list(output_path.parent.glob(f"{output_path.stem}_textured*"))
        for candidate in planned:
            if candidate.exists() and candidate.resolve() != mesh_path.resolve():
                raise FileExistsError(f"Refusing paint overwrite: {candidate}. Choose a fresh asset folder.")
        if output_path.with_suffix(".obj").resolve() == mesh_path.resolve():
            raise ValueError("Paint scratch OBJ would collide with the input master; choose another output stem/folder.")
        self.load()

        # The output's parent IS the asset folder. It already exists when
        # called from the web UI (which creates it explicitly), but we
        # ensure it for callers that pass a deeper path.
        asset_dir = output_path.parent
        asset_dir.mkdir(parents=True, exist_ok=True)
        print(f"[paint] Asset folder: {asset_dir}")

        # The Hunyuan painter writes OBJ + MTL + texture JPGs whose
        # filenames are derived from `output_mesh_path.stem`. We feed it
        # `<asset_name>_textured.obj` as the output target, so every
        # texture and material file ends up with the asset name as a
        # clean prefix:
        #     <asset_name>_textured.obj
        #     <asset_name>_textured.mtl
        #     <asset_name>_textured.jpg         (albedo)
        #     <asset_name>_textured_metallic.jpg
        #     <asset_name>_textured_roughness.jpg
        # We separately keep `<asset_name>.glb` (output_path) as the
        # single-file binary deliverable, built from the OBJ bundle.
        #
        # The pipeline ALSO needs a (possibly converted-from-GLB) input
        # OBJ to read geometry from; we write that as
        # `<asset_name>.obj` and remove it after painting since it is
        # redundant with the input GLB the caller already provided.
        obj_path = asset_dir / f"{output_path.stem}.obj"
        if mesh_path.suffix.lower() == ".glb":
            scene = trimesh.load(str(mesh_path), force="mesh", process=False)
            if hasattr(scene, "export"):
                scene.export(str(obj_path))
            else:
                raise RuntimeError(f"Could not load {mesh_path} as a mesh")
            print(f"[paint] Converted GLB → OBJ ({obj_path})")
        else:
            # OBJ input: copy into the asset folder under the canonical
            # name so painter output filenames stay consistent.
            if mesh_path.resolve() != obj_path.resolve():
                shutil.copy2(mesh_path, obj_path)

        # Reference image — convert RGBA to RGB with white background for the diffuser.
        if isinstance(reference_image, Image.Image):
            img = reference_image
        else:
            img = Image.open(str(reference_image)).convert("RGBA")
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.getchannel("A"))
            img = bg
        else:
            img = img.convert("RGB")

        out_obj = asset_dir / f"{obj_path.stem}_textured.obj"
        # PAINT_BUILD_TAG=2026-06-22b - if you don't see this exact line in the
        # terminal when running paint, the web UI is running stale module code
        # and needs to be restarted with `python scripts\launch_webui.py`.
        print(f"[paint][build=2026-06-22b] Running multi-view PBR diffusion (this takes ~60-120 s)...")

        # Defensive guard: ensure super_model weights live on CUDA before the
        # pipeline runs. The painter calls super-resolution from inside the
        # diffusion pipeline call; if its weights ever ended up on CPU (whether
        # from a previous bad code path, a notebook session that ran offload
        # logic, or any other reason), the conv layer would crash with
        # "Input type cuda.HalfTensor and weight type HalfTensor".
        try:
            import torch as _t_pre
            _sm_pre = self._pipeline.models.get("super_model") if hasattr(self._pipeline, "models") else None
            if _sm_pre is not None and hasattr(_sm_pre, "upsampler") and hasattr(_sm_pre.upsampler, "model"):
                _sm_pre.upsampler.model.to("cuda")
                # Also normalize its device attribute so realesrgan internals
                # don't get confused.
                try:
                    _sm_pre.upsampler.device = _t_pre.device("cuda")
                except Exception:
                    pass
                print("[paint][build=2026-06-22b] super_model verified on cuda")
        except Exception as _pre_e:
            print(f"[paint][build=2026-06-22b] could not verify super_model on cuda: {_pre_e}")

        try:
            self._pipeline(
                mesh_path=str(obj_path),
                image_path=img,
                output_mesh_path=str(out_obj),
                use_remesh=self.cfg.use_remesh,
                save_glb=False,   # we'll do the GLB export ourselves
            )
        except Exception as _pipe_err:
            # #region agent log
            try:
                import torch as _t2, json as _json, time as _time, traceback as _tb
                from pathlib import Path as _P
                _free = _total = 0
                try: _free, _total = _t2.cuda.mem_get_info()
                except Exception: pass
                _entry = {
                    "sessionId": "c02a0e",
                    "id": f"log_{int(_time.time()*1000)}_paint_pipeline_crash",
                    "timestamp": int(_time.time() * 1000),
                    "location": "engine_paint.py:paint:pipeline_call",
                    "message": "Painter pipeline raised",
                    "hypothesisId": "HJ",
                    "data": {
                        "exception_type": type(_pipe_err).__name__,
                        "exception_msg": str(_pipe_err)[:500],
                        "vram_free_gb": _free / (1024 ** 3) if _total else None,
                        "vram_total_gb": _total / (1024 ** 3) if _total else None,
                        "max_num_view": getattr(self.cfg, "max_num_view", None),
                        "resolution": getattr(self.cfg, "resolution", None),
                        "render_size": getattr(self.cfg, "render_size", None),
                        "texture_size": getattr(self.cfg, "texture_size", None),
                        "traceback_tail": _tb.format_exc()[-1500:],
                    },
                }
                _log = _P(__file__).resolve().parent.parent / "debug-c02a0e.log"
                with open(_log, "a", encoding="utf-8") as _f:
                    _f.write(_json.dumps(_entry) + "\n")
            except Exception:
                pass
            # #endregion
            # Try to recover VRAM so the next attempt has a chance.
            try:
                import torch as _t3, gc as _gc
                _gc.collect()
                if _t3.cuda.is_available():
                    _t3.cuda.empty_cache(); _t3.cuda.ipc_collect()
            except Exception:
                pass
            # Make the failure mode obvious to the user instead of a cryptic
            # "CUDA error: illegal memory access" message that scrolls in the UI.
            err_str = str(_pipe_err).lower()
            if isinstance(_pipe_err, torch.cuda.OutOfMemoryError) or "out of memory" in err_str:
                raise RuntimeError(
                    "PBR paint ran out of GPU memory.\n\n"
                    f"Settings used: views={self.cfg.max_num_view}, "
                    f"resolution={self.cfg.resolution}, render_size={self.cfg.render_size}, "
                    f"texture_size={self.cfg.texture_size}.\n\n"
                    "Use mmgp and reduce render size, texture size, or baking views "
                    "below the settings shown above. Close other GPU-heavy applications.\n"
                ) from _pipe_err
            raise

        # What did the pipeline actually produce?
        print(f"[paint] Pipeline finished. Files in {asset_dir}:")
        for f in sorted(asset_dir.iterdir()):
            size_kb = f.stat().st_size / 1024
            print(f"          {f.name}   ({size_kb:,.1f} KB)")

        # Build a textured GLB ourselves so the textures + materials are preserved.
        # trimesh.load on an OBJ + MTL + PNG bundle reads the diffuse texture into
        # the visual.material; exporting to GLB embeds it.
        if not out_obj.exists():
            raise RuntimeError(
                f"Pipeline did not produce expected OBJ: {out_obj}\n"
                f"Files actually written are listed above.")

        print(f"[paint] Loading textured OBJ for GLB export...")
        loaded = trimesh.load(str(out_obj), process=False)
        # OBJs with materials come back as Scene; concatenate preserves UVs and texture.
        if isinstance(loaded, trimesh.Scene):
            geoms = list(loaded.geometry.values())
            if len(geoms) == 1:
                final = geoms[0]
            else:
                # Multi-geometry export keeps each material separately in GLB.
                final = loaded
        else:
            final = loaded

        # ---- Embed PBR maps that the painter wrote separately ----
        # Hunyuan-2.1 produces albedo + metallic + roughness + (optional) normal
        # as separate JPGs in the work directory. Trimesh's MTL parser only loads
        # the albedo (map_Kd) into the material on its own. We manually attach
        # the rest here so the exported GLB carries full PBR data, and any
        # downstream code that reads from the GLB (e.g. shared-texture LOD
        # extraction) finds all four maps instead of just albedo.
        try:
            _attach_extra_pbr_maps(final, asset_dir, out_obj.stem)
        except Exception as _e:
            print(f"[paint] WARN: could not attach extra PBR maps: {_e}")

        # Diagnostic: did we actually get a texture?
        try:
            vis = getattr(final, "visual", None)
            mat = getattr(vis, "material", None) if vis is not None else None
            tex = getattr(mat, "baseColorTexture", None) or getattr(mat, "image", None)
            if tex is not None:
                print(f"[paint] OK - mesh has texture ({getattr(tex, 'size', '?')})")
            mr = getattr(mat, "metallicRoughnessTexture", None) if mat is not None else None
            nrm = getattr(mat, "normalTexture", None) if mat is not None else None
            if mr is not None:
                print(f"[paint] OK - PBR metallicRoughness map present ({getattr(mr, 'size', '?')})")
            if nrm is not None:
                print(f"[paint] OK - normal map present ({getattr(nrm, 'size', '?')})")
            elif isinstance(final, trimesh.Scene):
                tex_count = sum(
                    1 for g in final.geometry.values()
                    if getattr(getattr(g.visual, "material", None), "baseColorTexture", None) is not None
                )
                print(f"[paint] Scene has {tex_count} textured geometries / {len(final.geometry)} total")
            elif tex is None:
                print("[paint] WARNING: mesh has no detectable texture - "
                      "diffusion likely did not produce one. Inspect the texture .jpg files in the asset folder.")
        except Exception as e:
            print(f"[paint] Texture check failed: {e}")

        final.export(str(output_path))
        if self.cfg.save_separate_maps:
            paths=_save_png_maps(final,output_path)
            print(f"[paint] Saved {len(paths)} additional lossless PNG maps")
        print(f"[paint] Textured GLB saved → {output_path}")

        # #region agent log
        # Re-load the just-exported GLB to verify what trimesh's GLB serializer
        # actually preserved. If the maps are on `final.visual.material` BUT
        # missing in the re-loaded GLB, the bug is in trimesh's GLB writer
        # (and we'd need to use a different exporter).
        try:
            import json as _json, time as _time
            from pathlib import Path as _P
            import trimesh as _trimesh_v
            _reload = _trimesh_v.load(str(output_path), force="mesh", process=False)
            _vis = getattr(_reload, "visual", None)
            _mat = getattr(_vis, "material", None) if _vis is not None else None
            _entry = {
                "sessionId": "c02a0e",
                "id": f"log_{int(_time.time()*1000)}_glb_roundtrip",
                "timestamp": int(_time.time() * 1000),
                "location": "engine_paint.py:paint:glb_roundtrip_verify",
                "message": "Round-trip GLB verification: what's actually in the saved file",
                "hypothesisId": "HE",
                "data": {
                    "vis_type": type(_vis).__name__,
                    "material_type": type(_mat).__name__ if _mat else None,
                    "baseColorTexture": "present" if getattr(_mat, "baseColorTexture", None) is not None else "missing",
                    "metallicRoughnessTexture": "present" if getattr(_mat, "metallicRoughnessTexture", None) is not None else "missing",
                    "normalTexture": "present" if getattr(_mat, "normalTexture", None) is not None else "missing",
                    "has_uv": hasattr(_vis, "uv") and getattr(_vis, "uv", None) is not None,
                    "uv_count": len(_vis.uv) if (hasattr(_vis, "uv") and _vis.uv is not None) else 0,
                    "glb_size_bytes": output_path.stat().st_size,
                },
            }
            _log = _P(__file__).resolve().parent.parent / "debug-c02a0e.log"
            with open(_log, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps(_entry) + "\n")
        except Exception as _e:
            pass
        # #endregion

        # The asset folder is the deliverable. The OBJ + MTL + texture
        # JPGs the painter wrote already live there with clean asset-name
        # prefixes (see the asset folder layout in the docstring), so
        # there is no longer a separate `_maps/` folder - everything is
        # already side-by-side with `<asset_name>.glb`.
        #
        # However, the painter pipeline also writes a few internal scratch
        # files into the same dir that the user has no use for:
        #   - `<asset_name>.obj`           : the pre-paint untextured OBJ
        #                                    we wrote to feed the pipeline
        #                                    (redundant with the input GLB
        #                                    the caller already provided).
        #   - `white_mesh_remesh.obj`      : the painter's remeshed copy
        #                                    of the input geometry.
        # Remove these on success so the asset folder contains ONLY the
        # final deliverables. `keep_intermediate=True` opts back into the
        # raw painter-output layout for debugging.
        if not keep_intermediate:
            for scratch_name in (f"{output_path.stem}.obj",
                                  "white_mesh_remesh.obj"):
                scratch = asset_dir / scratch_name
                if scratch.exists() and scratch.resolve() != out_obj.resolve():
                    try:
                        scratch.unlink()
                    except OSError as _e:
                        print(f"[paint] WARN: could not remove scratch "
                              f"`{scratch.name}`: {_e}")

        return output_path


def painter_from_config(cfg: dict) -> Hunyuan3DPainter:
    p = (cfg.get("model", {}) or {}).get("paint", {}) or {}
    return Hunyuan3DPainter(PaintConfig(
        max_num_view=p.get("max_num_view", 6),
        resolution=p.get("resolution", 512),
        use_remesh=p.get("use_remesh", True),
        render_size=p.get("render_size", 2048),
        texture_size=p.get("texture_size", 4096),
        bake_exp=p.get("bake_exp", 4),
        merge_method=p.get("merge_method", "fast"),
        save_separate_maps=p.get("save_separate_maps", False),
        low_vram_mode=p.get("low_vram_mode", False),
        safe_cpu_checkpoint_io=p.get("safe_cpu_checkpoint_io",True),
    ))


def rasterizer_ready() -> bool:
    return _check_rasterizer()
