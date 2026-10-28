"""
Shared TripoSG inference engine.

Loads weights once (download from HuggingFace on first run) and exposes a
simple `generate(image)` function used by both the CLI and the Gradio UI.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import numpy as np
import torch
import trimesh
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "TripoSG"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))
# Also expose vendor/TripoSG/scripts for the helper modules (briarmbg, image_process)
VENDOR_SCRIPTS = VENDOR / "scripts"
if str(VENDOR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(VENDOR_SCRIPTS))

from huggingface_hub import snapshot_download           # noqa: E402

from triposg.pipelines.pipeline_triposg import TripoSGPipeline   # noqa: E402
from briarmbg import BriaRMBG                                    # noqa: E402
from image_process import prepare_image                          # noqa: E402

import pymeshlab                                                 # noqa: E402


@dataclass
class EngineConfig:
    weights_dir: str = "pretrained_weights/TripoSG"
    rmbg_dir: str = "pretrained_weights/RMBG-1.4"
    device: str = "cuda"
    dtype: str = "float16"          # 'float16' or 'float32'

    @property
    def torch_dtype(self) -> torch.dtype:
        return torch.float16 if self.dtype == "float16" else torch.float32


class TripoSGEngine:
    """Lazy-loaded TripoSG pipeline. Reuses a single instance across calls."""

    def __init__(self, cfg: EngineConfig):
        from scripts.gpu_lifecycle import register
        register(self)
        self.cfg = cfg
        self._pipe: Optional[TripoSGPipeline] = None
        self._rmbg: Optional[BriaRMBG] = None

    # ---------- weights ----------
    def ensure_weights(self, background: bool = True) -> None:
        triposg_dir = ROOT / self.cfg.weights_dir
        rmbg_dir = ROOT / self.cfg.rmbg_dir
        triposg_dir.parent.mkdir(parents=True, exist_ok=True)
        rmbg_dir.parent.mkdir(parents=True, exist_ok=True)

        if not (triposg_dir / "model_index.json").exists() and not any(triposg_dir.glob("*.safetensors")):
            print(f"[engine] downloading TripoSG weights -> {triposg_dir}")
            snapshot_download(repo_id="VAST-AI/TripoSG", local_dir=str(triposg_dir))

        if background and not any(rmbg_dir.glob("*.pth")) and not (rmbg_dir / "model.safetensors").exists():
            print(f"[engine] downloading RMBG-1.4 weights -> {rmbg_dir}")
            snapshot_download(repo_id="briaai/RMBG-1.4", local_dir=str(rmbg_dir))

    # ---------- load ----------
    def load(self, background: bool = True) -> None:
        if self._pipe is not None:
            return
        self.ensure_weights(background)
        device = self.cfg.device
        dtype = self.cfg.torch_dtype

        print(f"[engine] loading TripoSG on {device} ({self.cfg.dtype})")
        self._pipe = TripoSGPipeline.from_pretrained(
            str(ROOT / self.cfg.weights_dir)
        ).to(device, dtype)

        if background:
            self._load_background()

    def _load_background(self):
        if self._rmbg is None:
            self.ensure_weights(background=True)
            print("[engine] loading RMBG-1.4")
            self._rmbg = BriaRMBG.from_pretrained(str(ROOT / self.cfg.rmbg_dir)).to(self.cfg.device)
            self._rmbg.eval()

    def unload(self) -> None:
        import gc
        self._pipe = None
        self._rmbg = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ---------- inference ----------
    @torch.no_grad()
    def generate(
        self,
        image: Union[str, Image.Image],
        *,
        seed: int = 42,
        num_inference_steps: int = 50,
        guidance_scale: float = 7.0,
        faces: int = -1,
        remove_background: bool = True,
        octree_depth: int = 9,
        dense_octree_depth: Optional[int] = None,
        bounds: float = 1.25,
        rmbg_backend: str = "rmbg",   # 'rmbg' (Briaai RMBG-1.4), 'rembg' (u2net), or 'none'
    ) -> trimesh.Trimesh:
        """Run the full image -> mesh pipeline. Returns a Trimesh.

        Parameters
        ----------
        bounds            : half-width of the SDF bounding cube. Smaller = more detail
                            concentrated on the object, but may clip the geometry. Default 1.25.
        rmbg_backend      : which background remover to use. 'rmbg' = BriaRMBG-1.4 (best for products),
                            'rembg' = u2net (better for outdoor/cluttered shots), 'none' = skip.
        dense_octree_depth: coarse grid before hierarchical refinement. None = octree_depth-1.
        """
        needs_background = remove_background and rmbg_backend == "rmbg"
        self.load(background=needs_background)
        if needs_background:
            self._load_background()
        assert self._pipe is not None

        if remove_background and rmbg_backend != "none":
            if rmbg_backend == "rembg":
                from rembg import remove as _rembg_remove
                if isinstance(image, (str, Path)):
                    img_in = Image.open(image).convert("RGBA")
                else:
                    img_in = image if image.mode == "RGBA" else image.convert("RGBA")
                img_alpha = _rembg_remove(img_in)
                bg = Image.new("RGB", img_alpha.size, (255, 255, 255))
                bg.paste(img_alpha, mask=img_alpha.getchannel("A"))
                img_pil = bg
            else:  # 'rmbg' (default Briaai)
                # TripoSG's vendor `prepare_image()` requires a filesystem
                # PATH (it calls `os.path.isfile()` then `cv2.imread()` on
                # the argument - see vendor/TripoSG/scripts/image_process.py
                # lines 21 and 144). Gradio hands us a PIL.Image, which
                # is not a path-like and triggers a TypeError from
                # os.path.isfile. Materialise to a temp PNG when we don't
                # already have a path, pass the path in, and unlink after.
                import tempfile
                if isinstance(image, (str, Path)):
                    img_pil = prepare_image(
                        str(image),
                        bg_color=np.array([1.0, 1.0, 1.0]),
                        rmbg_net=self._rmbg,
                    )
                else:
                    # mkstemp + explicit unlink avoids the Windows-specific
                    # NamedTemporaryFile re-open issue (where a handle is
                    # still open while PIL tries to read the same path).
                    fd, tmp_path = tempfile.mkstemp(suffix=".png")
                    os.close(fd)
                    try:
                        save_img = image
                        if save_img.mode not in ("RGB", "RGBA"):
                            save_img = save_img.convert("RGBA")
                        save_img.save(tmp_path)
                        img_pil = prepare_image(
                            tmp_path,
                            bg_color=np.array([1.0, 1.0, 1.0]),
                            rmbg_net=self._rmbg,
                        )
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
        else:
            img_pil = image if isinstance(image, Image.Image) else Image.open(image).convert("RGB")

        gen = torch.Generator(device=self._pipe.device).manual_seed(seed)
        # use_flash_decoder=False forces the hierarchical decoder (skimage marching cubes),
        # which avoids the diso CUDA dependency we don't want to build on Windows.
        if dense_octree_depth is None:
            dense_depth = max(7, octree_depth - 1)
        else:
            dense_depth = min(dense_octree_depth, octree_depth)
        outputs = self._pipe(
            image=img_pil,
            generator=gen,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            use_flash_decoder=False,
            dense_octree_depth=dense_depth,
            hierarchical_octree_depth=octree_depth,
            bounds=bounds,
        ).samples[0]

        verts = outputs[0].astype(np.float32)
        tris = np.ascontiguousarray(outputs[1])
        mesh = trimesh.Trimesh(vertices=verts, faces=tris)

        if faces > 0:
            mesh = decimate(mesh, faces)

        return mesh


# ---------- mesh helpers ----------
def decimate(mesh: trimesh.Trimesh, target_faces: int) -> trimesh.Trimesh:
    """Quadric-edge-collapse decimation via pymeshlab with topology preservation
    and pre/post cleanup, so we don't get the "Swiss-cheese" holes that aggressive
    decimation introduces in thin-walled meshes (windows, roof seams, etc.).
    """
    if mesh.faces.shape[0] <= target_faces:
        return mesh
    pm = pymeshlab.Mesh(vertex_matrix=mesh.vertices, face_matrix=mesh.faces)
    ms = pymeshlab.MeshSet()
    ms.add_mesh(pm)

    # ---- Pre-cleanup: fix the input mesh first. Without this, marching-cubes
    # droplets and near-duplicate vertices get fused into surface artifacts during
    # decimation.
    try: ms.meshing_remove_duplicate_vertices()
    except Exception: pass
    try: ms.meshing_remove_duplicate_faces()
    except Exception: pass
    try: ms.meshing_remove_unreferenced_vertices()
    except Exception: pass
    try: ms.meshing_remove_null_faces()
    except Exception: pass
    try: ms.meshing_merge_close_vertices()
    except Exception: pass
    # Drop tiny disconnected polygon islands left over from marching cubes.
    # mincomponentdiag is in % of the bounding-box diagonal; 5% is safe for
    # buildings, removes specks without eating real geometry.
    try:
        ms.meshing_remove_connected_component_by_diameter(
            mincomponentdiag=pymeshlab.PercentageValue(5.0))
    except Exception:
        try:  # older pymeshlab API name
            ms.meshing_remove_connected_component_by_diameter(
                mincomponentdiag=pymeshlab.Percentage(5.0))
        except Exception:
            pass

    # ---- Decimate with topology preservation. This is the big one: it stops
    # quadric-edge-collapse from punching through thin walls and frames.
    ms.meshing_decimation_quadric_edge_collapse(
        targetfacenum=int(target_faces),
        qualitythr=0.3,           # reject very low-quality collapses
        preservetopology=True,    # the fix for "Swiss cheese" walls
        preservenormal=True,      # don't flip face normals
        preserveboundary=True,    # keep open edges where they are
        planarquadric=True,       # cleaner flat surfaces (walls, roof)
        optimalplacement=True,    # smoother result
        autoclean=True,           # remove resulting degenerate tris
    )

    # ---- Post-cleanup pass
    try: ms.meshing_remove_duplicate_faces()
    except Exception: pass
    try: ms.meshing_remove_unreferenced_vertices()
    except Exception: pass
    try: ms.meshing_remove_null_faces()
    except Exception: pass

    m = ms.current_mesh()
    return trimesh.Trimesh(vertices=m.vertex_matrix(), faces=m.face_matrix())


def export_glb_and_obj(
    mesh: trimesh.Trimesh,
    glb_path: Union[str, Path],
) -> Path:
    """Export `mesh` as both `<stem>.glb` AND `<stem>.obj` next to each other.

    TripoSG returns a Trimesh that is either geometry-only or carries a
    planar-projected baseColorTexture from `planar_project_front`. We
    want the user to be able to open the asset both in a glTF viewer
    (`.glb`, single-file, textures embedded) AND in any 3D editor that
    prefers Wavefront (`.obj` + sibling `.mtl` + texture PNG). Calling
    `mesh.export(<obj_path>)` after the GLB write does exactly that:
    trimesh writes the OBJ, the MTL, and the texture image alongside.

    Texture/MTL filenames in trimesh's OBJ exporter are derived from
    `material.name`. The default `"planar_proj"` collides when several
    OBJs land in the same folder (the Folder/batch path, or a BMS LOD
    set), so we rename the material to the OBJ stem before exporting
    and pass `mtl_name` to control the MTL filename - each export then
    produces a unique `<stem>.mtl` + `<stem>.png` sibling pair.

    Returns the GLB path so callers can keep using it as the canonical
    asset reference for status messages and the Gradio Model3D viewer.
    """
    glb_path = Path(glb_path)
    obj_path = glb_path.with_suffix(".obj")

    for candidate in (glb_path, obj_path, obj_path.with_suffix(".mtl"), obj_path.with_suffix(".png")):
        if candidate.exists():
            raise FileExistsError(f"Refusing overwrite: {candidate}. Choose a fresh output path.")
    mesh = mesh.copy()
    mesh.export(str(glb_path))

    try:
        material = getattr(mesh.visual, "material", None)
        if material is not None:
            try:
                material.name = obj_path.stem
            except Exception:
                pass
        mesh.export(str(obj_path), mtl_name=f"{obj_path.stem}.mtl")
    except Exception as e:
        # OBJ companion is best-effort - the GLB is already on disk, so
        # surface the failure but don't abort the generation. Exotic
        # visual state (e.g. weird image modes) shouldn't cost the user
        # the run.
        print(f"[engine] WARN: OBJ companion export failed for {obj_path}: {e}")

    return glb_path


def load_config(path: Optional[str] = None) -> dict:
    """Tiny YAML config loader using project root config.yaml as the default."""
    import yaml
    p = Path(path) if path else (ROOT / "config.yaml")
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def engine_from_config(cfg: dict) -> TripoSGEngine:
    m = (cfg.get("model", {}) or {}).get("triposg", {}) or {}
    return TripoSGEngine(EngineConfig(
        weights_dir=m.get("weights_dir", "pretrained_weights/TripoSG"),
        rmbg_dir=m.get("rmbg_dir", "pretrained_weights/RMBG-1.4"),
        device=m.get("device", "cuda" if torch.cuda.is_available() else "cpu"),
        dtype=m.get("dtype", "float16"),
    ))
