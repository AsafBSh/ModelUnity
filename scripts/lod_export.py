"""
LOD set exporters for the Falcon BMS pipeline.

Two flavours:

1. `make_lod_set(mesh, name, lod_targets, out_root)`
   For UNtextured or planar-textured meshes (TripoSG single, Multi-view).
   Each LOD is a standalone .glb (embedded planar texture, if any).
   Use after a regular shape generation.

2. `make_textured_lod_set(textured_glb_path, name, lod_targets, out_root)`
   For PBR-painted meshes (Multi-view with Paint enabled, or Paint tab output).
   Produces N decimated .glb files with PBR textures EMBEDDED in each file
   (so every LOD opens fully textured in any 3D viewer with zero setup),
   plus ONE shared Materials.mtl + texture PNG set that the BMS Blender
   Plugin / InstaMAT / Substance can pick up for material editing. The
   shared external textures dedupe across LODs at BMS bake time.

Both also drop a `bms_template/` subfolder next to the LODs containing a
ready-to-use BMS-spec `Parent.dat`, JSON `materials.mtl` scaffold, and a
short README. The modeller copies the contents of that folder into
`<BMS>\Data\TerrData\Objects\Models\<XXXX>\` after their own OBJ/GLB -> BML
export (3ds Max BML Exporter or Blender BMS Plugin — we don't care which).
"""
from __future__ import annotations

import json
import re
import time
import traceback
from pathlib import Path
from typing import Iterable, Tuple, Union

import numpy as np
import trimesh

from scripts.engine import decimate, export_glb_and_obj
from scripts.export_contracts import validated_export


# #region agent log
_LOG_PATH = Path(__file__).resolve().parent.parent / "debug-c02a0e.log"
def _dbg(location: str, message: str, data: dict | None = None,
         hypothesis_id: str | None = None) -> None:
    """NDJSON append to the session log file. Failures are silently ignored."""
    try:
        entry = {
            "sessionId": "c02a0e",
            "id": f"log_{int(time.time()*1000)}_{location}",
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
        }
        if hypothesis_id:
            entry["hypothesisId"] = hypothesis_id
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
# #endregion


# =============================================================================
# Public API
# =============================================================================

@validated_export
def make_lod_set(
    mesh: trimesh.Trimesh,
    name: str,
    lod_targets: Iterable[Tuple[str, int]],
    out_root: Union[str, Path],
    normal_baker: str = "off",
) -> Path:
    """Decimate `mesh` to each (lod_name, face_count) and export as GLBs.

    Each LOD is an independent .glb; the planar-projected texture (if the
    mesh has one) is embedded into each file. This is fine for the simple
    TripoSG / multi-view flows that don't produce real PBR.

    normal_baker : "off" (default), "low", "medium", "high".
        When != "off", a single normal.png is baked once from the master
        mesh and saved to the asset folder + attached to each LOD's
        PBRMaterial.normalTexture so the embedded GLB carries it. AI
        bakers (medium/high) need an albedo image - if the input mesh has
        no baseColorTexture, the dispatcher reports a fallback to "low"
        (mesh-derived NumPy bake).
    """
    out_dir = Path(out_root) / name
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- Optionally bake a single shared normal map from the master mesh.
    normal_img = None
    if (normal_baker or "off").lower() != "off":
        try:
            # Pull an albedo if the mesh has one (planar_project_front
            # attaches a PBRMaterial with baseColorTexture for both
            # TripoSG single + multi-view tabs).
            albedo_img = None
            try:
                _mat = getattr(mesh.visual, "material", None)
                albedo_img = (getattr(_mat, "baseColorTexture", None)
                              or getattr(_mat, "image", None))
            except Exception:
                pass
            uv_size = max(albedo_img.size) if albedo_img is not None else 2048
            normal_img = bake_normal_map(mesh, albedo_img,
                                         baker=normal_baker, uv_size=uv_size)
            if normal_img is not None:
                (out_dir / "normal_bake.json").write_text(json.dumps({"requested": normal_baker,
                    "actual": normal_img.info.get("modelunify_baker", "unknown")}), encoding="utf-8")
                normal_img.save(out_dir / "normal.png")
                print(f"[lod_export] normal.png written ({uv_size}x{uv_size}, "
                      f"baker={normal_baker}).")
        except Exception as _e:
            print(f"[lod_export] WARN: normal-map bake failed: {_e} - "
                  f"continuing without a normal map.")
            normal_img = None

    for lod_name, target in lod_targets:
        m = (_decimate_keep_uv(mesh, int(target)) if getattr(mesh.visual, "uv", None) is not None
             else decimate(mesh, int(target))) if target > 0 else mesh.copy()
        if getattr(mesh.visual, "uv", None) is not None:
            if getattr(m.visual, "uv", None) is not None:
                m.visual.material = mesh.visual.material
            else:
                _flat_colour_visual(m, average_albedo_rgba(_extract_textures(mesh).get("albedo")), f"{name}_{lod_name}_flat")
        # If we baked a normal map and the LOD mesh has a PBRMaterial,
        # attach the normal so it's embedded in the per-LOD GLB.
        if normal_img is not None:
            try:
                if hasattr(m.visual, "material") and m.visual.material is not None:
                    if not isinstance(m.visual.material,
                                      trimesh.visual.material.PBRMaterial):
                        _old = m.visual.material
                        m.visual.material = trimesh.visual.material.PBRMaterial(
                            name=getattr(_old, "name", "material"),
                            baseColorTexture=getattr(_old, "image", None)
                                             or getattr(_old, "baseColorTexture", None),
                        )
                    m.visual.material.normalTexture = normal_img
            except Exception:
                pass
        # Write both `<lod>.glb` and `<lod>.obj` (+ MTL + texture PNG when
        # the mesh is planar-textured) so the BMS modeller can import
        # either format into Blender / 3ds Max. The helper renames the
        # material per LOD, so the .mtl / texture filenames for Model_0,
        # Model_1, ... don't overwrite each other inside this folder.
        export_glb_and_obj(m, out_dir / f"{lod_name}.glb")

    _write_bms_template(out_dir, name, mesh, lod_targets)
    return out_dir


@validated_export
def make_textured_lod_set(
    textured_glb_path: Union[str, Path],
    name: str,
    lod_targets: Iterable[Tuple[str, int]],
    out_root: Union[str, Path],
    normal_baker: str = "low",
) -> Path:
    """Produce a shared-texture LOD set from a painted .glb.

    Output layout (all in one folder, Blender-plugin-ready):
        <name>/
            Model_0.glb .. Model_N.glb   ← self-contained embedded PBR maps
            Materials.mtl                 ← Wavefront editing sidecar
            albedo.png                    ← shared textures (1 set, not N)
            metallic_roughness.png        ← (combined MR map from glTF)
            normal.png                    ← (if present)
            bms_template/                 ← BMS-spec Parent.dat + materials.mtl
                Parent.dat                ← drop-in usable
                materials.mtl             ← JSON scaffold (rename of slots
                                            already match BMS conventions)
                README.txt                ← what to do with this folder
    """
    src = Path(textured_glb_path)
    out_dir = Path(out_root) / name
    out_dir.mkdir(parents=True, exist_ok=True)

    # #region agent log
    _dbg("lod_export.py:make_textured_lod_set:start",
         "Starting textured LOD export",
         {"src": str(src), "name": name, "out_dir": str(out_dir),
          "lod_targets": list(lod_targets) if not isinstance(lod_targets, list) else lod_targets,
          "src_exists": src.exists(), "src_size": src.stat().st_size if src.exists() else -1},
         hypothesis_id="H1")
    # #endregion
    # lod_targets might be a generator - materialize to a list so we can iterate twice
    lod_targets = list(lod_targets)

    # Load the painted mesh. force="mesh" collapses Scene into a single Trimesh
    # while keeping visual + UVs intact.
    loaded = trimesh.load(str(src), force="mesh", process=False)
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError(f"Could not load {src} as a single textured mesh.")
    mesh: trimesh.Trimesh = loaded

    uv = getattr(mesh.visual, "uv", None)
    if uv is None or len(uv) == 0:
        raise ValueError(
            "Input mesh has no UV coordinates - shared-texture LODs need UVs. "
            "Use a mesh produced by the Paint tab or by the Multi-view tab "
            "with Paint enabled.")

    # ---- Extract textures from the glTF/GLB material into shared PNGs ----
    textures = _extract_textures(mesh)
    # #region agent log
    _dbg("lod_export.py:make_textured_lod_set:after_extract",
         "Texture extraction done",
         {"texture_keys": list(textures.keys()),
          "mesh_faces": int(mesh.faces.shape[0]),
          "mesh_verts": int(mesh.vertices.shape[0]),
          "uv_shape": list(uv.shape) if hasattr(uv, "shape") else None,
          "material_type": type(getattr(mesh.visual, "material", None)).__name__,
          "material_attrs": sorted([a for a in dir(getattr(mesh.visual, "material", None) or object()) if not a.startswith("_")])[:30]},
         hypothesis_id="H4")
    # #endregion
    saved: dict[str, str] = {}
    for kind, img in textures.items():
        fn = f"{kind}.png"
        img.save(out_dir / fn)
        saved[kind] = fn
    if "metallic_roughness" in textures:
        # Wavefront consumers do not universally interpret glTF G/B packing.
        # Keep the combined source and give the MTL unambiguous scalar maps.
        mr_rgb = textures['metallic_roughness'].convert('RGB')
        for kind, channel in (('roughness', 'G'), ('metallic', 'B')):
            fn = f'{kind}.png'
            mr_rgb.getchannel(channel).save(out_dir / fn)
            saved[kind] = fn
    if not saved:
        print("[lod_export] WARN: no textures found on input mesh - "
              "MTL will be material-only with no maps.")

    # ---- Bake a tangent-space normal map if the painter didn't provide one.
    # Hunyuan3D-2.1 paint outputs only albedo + metallicRoughness; it uses
    # normals as a CONDITIONING input but does not emit a normal texture.
    # We synthesise one here using the selected `normal_baker`:
    #   "off"     -> skip entirely
    #   "low"     -> pure-NumPy bake from the LOD0 mesh's per-vertex normals
    #   "medium"  -> Stable-X/StableNormal (AI prediction from albedo)
    #   "high"    -> prs-eth/marigold-normals-v1-1 (AI, higher quality)
    if "normal" not in saved and (normal_baker or "low").lower() != "off":
        try:
            albedo_img = textures.get("albedo")
            mr_img = textures.get("metallic_roughness")
            ref_size = None
            for cand in (albedo_img, mr_img):
                if cand is not None and getattr(cand, "size", None):
                    ref_size = max(cand.size)
                    break
            uv_size = int(ref_size) if ref_size else 2048
            normal_img = bake_normal_map(mesh, albedo_img,
                                         baker=normal_baker, uv_size=uv_size)
            if normal_img is not None:
                (out_dir / "normal_bake.json").write_text(json.dumps({"requested": normal_baker,
                    "actual": normal_img.info.get("modelunify_baker", "unknown")}), encoding="utf-8")
                normal_img.save(out_dir / "normal.png")
                saved["normal"] = "normal.png"
                # Attach to the master mesh's PBRMaterial so each LOD's
                # embedded GLB carries the same map (the LOD loop below
                # re-points each decimated mesh's material to mesh.visual.material).
                try:
                    if hasattr(mesh.visual, "material") and mesh.visual.material is not None:
                        if not isinstance(mesh.visual.material,
                                          trimesh.visual.material.PBRMaterial):
                            mesh.visual.material = trimesh.visual.material.PBRMaterial(
                                name=getattr(mesh.visual.material, "name", "material"),
                                baseColorTexture=getattr(mesh.visual.material, "image", None)
                                                or getattr(mesh.visual.material, "baseColorTexture", None),
                            )
                        mesh.visual.material.normalTexture = normal_img
                except Exception as _e:
                    print(f"[lod_export] WARN: could not attach baked normal to "
                          f"master material: {_e}")
        except Exception as _e:
            print(f"[lod_export] WARN: normal-map bake failed: {_e} - "
                  f"continuing without a normal map.")
    elif (normal_baker or "low").lower() == "off":
        print("[lod_export] normal_baker=off - no new normal bake; existing source maps are preserved.")

    # ---- Drop a short README listing what's here (real maps only - no fakes) ----
    _write_pbr_readme(saved, out_dir)
    # #region agent log
    _dbg("lod_export.py:make_textured_lod_set:after_synth",
         "Final texture files written - real outputs only, no placeholders",
         {"final_texture_files": list(saved.keys())},
         hypothesis_id="HG")
    # #endregion

    # ---- Write the single shared Materials.mtl ----
    material_name = name
    (out_dir / "Materials.mtl").write_text(
        _build_mtl(material_name, saved), encoding="utf-8")

    # ---- Decimate + export each LOD as a self-contained GLB with the PBR
    #      maps EMBEDDED in the file. GLB is the right format here because
    #      it carries albedo + metallicRoughness + normal as binary blobs in
    #      a single file - so the LOD shows fully textured in ANY viewer (no
    #      external MTL/PNG path resolution required, unlike OBJ).
    #
    #      The shared Materials.mtl + albedo.png + metallic_roughness.png
    #      written above are still useful for Blender + BMS plugin editing
    #      workflows (one shared set, not per-LOD copies, so they don't
    #      count as "doubled" output).
    #
    #      Colour used for any LOD whose UVs don't survive decimation. Derived
    #      once from the master albedo so all such LODs agree.
    flat_rgba = average_albedo_rgba(textures.get("albedo"))
    flat_lods: list[str] = []

    for lod_name, target in lod_targets:
        target = int(target)
        # #region agent log
        _dbg("lod_export.py:make_textured_lod_set:lod_start",
             f"Starting LOD {lod_name}",
             {"lod_name": lod_name, "target_faces": target,
              "current_faces": int(mesh.faces.shape[0])},
             hypothesis_id="H1")
        # #endregion
        try:
            if target > 0 and mesh.faces.shape[0] > target:
                m = _decimate_keep_uv(mesh, target)
            else:
                m = mesh.copy()

            # Decimation can strip the material reference from the visual
            # (the new mesh's TextureVisuals carries UVs but may have a
            # different material instance). Re-attach the master's PBR
            # material so the embedded GLB carries ALL maps, not just albedo.
            # If the UVs did NOT survive, the atlas is unusable for this LOD:
            # fall back to a flat colour rather than shipping a mesh that
            # samples a UV set it no longer has.
            try:
                _uv = getattr(m.visual, "uv", None)
                if _uv is not None and len(_uv) == len(m.vertices):
                    m.visual.material = mesh.visual.material
                else:
                    _flat_colour_visual(m, flat_rgba, f"{name}_{lod_name}_flat")
                    flat_lods.append(lod_name)
                    print(f"[lod_export] {lod_name}: UVs lost during decimation "
                          f"({target} faces) - exporting flat RGBA{flat_rgba} "
                          f"instead of a broken atlas reference.")
            except Exception as _e:
                print(f"[lod_export] {lod_name}: material re-attach failed ({_e}).")

            # #region agent log
            _dbg("lod_export.py:make_textured_lod_set:lod_decimated",
                 f"Decimation OK for {lod_name}",
                 {"lod_name": lod_name,
                  "out_faces": int(m.faces.shape[0]),
                  "out_verts": int(m.vertices.shape[0]),
                  "has_uv": hasattr(m.visual, "uv") and m.visual.uv is not None,
                  "uv_count": len(m.visual.uv) if (hasattr(m.visual, "uv") and m.visual.uv is not None) else 0,
                  "material_class": type(getattr(m.visual, "material", None)).__name__,
                  "has_baseColor": hasattr(getattr(m.visual, "material", None), "baseColorTexture") and
                                   getattr(m.visual.material, "baseColorTexture", None) is not None,
                  "has_MR": hasattr(getattr(m.visual, "material", None), "metallicRoughnessTexture") and
                            getattr(m.visual.material, "metallicRoughnessTexture", None) is not None},
                 hypothesis_id="H2,H3,EMBED")
            # #endregion

            m.metadata["modelunify_uv_method"] = m.metadata.get("modelunify_uv_method", "unchanged")
            glb_path = out_dir / f"{lod_name}.glb"
            m.export(str(glb_path))

            # #region agent log
            try:
                _bbox = m.bounds.tolist()
                _master_bbox = mesh.bounds.tolist()
            except Exception:
                _bbox = None; _master_bbox = None
            _was_copied = (target <= 0) or (mesh.faces.shape[0] <= target)
            # Verify the GLB has the embedded textures by round-tripping it.
            _roundtrip_albedo = _roundtrip_mr = "unknown"
            try:
                import trimesh as _tr
                _r = _tr.load(str(glb_path), force="mesh", process=False)
                _rm = getattr(_r.visual, "material", None)
                _roundtrip_albedo = "present" if getattr(_rm, "baseColorTexture", None) is not None else "MISSING"
                _roundtrip_mr = "present" if getattr(_rm, "metallicRoughnessTexture", None) is not None else "MISSING"
            except Exception as _re:
                _roundtrip_albedo = f"err: {_re}"
            _dbg("lod_export.py:make_textured_lod_set:lod_written",
                 f"GLB written for {lod_name}",
                 {"lod_name": lod_name, "path": str(glb_path),
                  "size_bytes": glb_path.stat().st_size if glb_path.exists() else -1,
                  "was_copied_from_master": _was_copied,
                  "master_faces": int(mesh.faces.shape[0]),
                  "lod_faces": int(m.faces.shape[0]),
                  "lod_verts": int(m.vertices.shape[0]),
                  "bbox_matches_master": (_bbox == _master_bbox) if _bbox else None,
                  "glb_embedded_albedo": _roundtrip_albedo,
                  "glb_embedded_MR": _roundtrip_mr},
                 hypothesis_id="H1,LOD0_align,EMBED")
            # #endregion
        except Exception as _e:
            # #region agent log
            _dbg("lod_export.py:make_textured_lod_set:lod_FAILED",
                 f"LOD {lod_name} raised an exception",
                 {"lod_name": lod_name, "exception_type": type(_e).__name__,
                  "exception_msg": str(_e),
                  "traceback": traceback.format_exc()},
                 hypothesis_id="H2,H3")
            # #endregion
            raise

    if flat_lods:
        print(f"[lod_export] {len(flat_lods)} LOD(s) exported untextured "
              f"(flat RGBA{flat_rgba}) because decimation destroyed their UVs: "
              f"{', '.join(flat_lods)}. The shared atlas still applies to the "
              f"remaining levels.")

    _write_bms_template(out_dir, name, mesh, lod_targets)
    return out_dir


# =============================================================================
# Normal-map bakers
# =============================================================================
#
# Four levels, selected by name via `bake_normal_map(... baker=...)`:
#
#   "off"     no normal map at all.
#   "low"     bake_tangent_normal_to_uv(mesh) - pure NumPy, free, fast (~3 s),
#             no extra deps, no VRAM. LOD-consistency only; does NOT add
#             brick / panel / rivet detail beyond what the LOD0 mesh has.
#   "medium"  Stable-X/StableNormal (yoso turbo). AI predicts tangent-space
#             normals from the albedo image. ~3 GB VRAM, ~10-15 s,
#             requires an installed StableNormal model from Models.
#   "high"    prs-eth/marigold-normals-v1-1. AI prediction, higher quality.
#             ~5 GB VRAM, ~30-60 s; install Marigold from Models first.
#
# Legacy alias: "geometry" -> "low" (older configs / docs may still say
# "geometry" for the NumPy mesh baker - both names work).
#
# AI bakers consume the ALBEDO texture (the UV-space PNG produced by the
# Hunyuan painter). The output is in the same UV space - no MikkTSpace,
# no high-poly reference needed. Both AI models output tangent-space normals
# in glTF/OpenGL convention (R=X-right, G=Y-up, B=Z-out).

_MARIGOLD_PIPE = None
_STABLENORMAL_PIPE = None


def _load_marigold_pipe():
    global _MARIGOLD_PIPE
    if _MARIGOLD_PIPE is None:
        import torch
        import diffusers
        from scripts.model_manager.integration import directory
        _MARIGOLD_PIPE = diffusers.MarigoldNormalsPipeline.from_pretrained(
            str(directory('marigold')),
            variant="fp16",
            torch_dtype=torch.float16,
            local_files_only=True,
        )
        if torch.cuda.is_available():
            _MARIGOLD_PIPE = _MARIGOLD_PIPE.to("cuda")
    return _MARIGOLD_PIPE


def _unload_marigold_pipe():
    global _MARIGOLD_PIPE
    if _MARIGOLD_PIPE is None:
        return
    import gc
    import torch
    try:
        _MARIGOLD_PIPE.to("cpu")
    except Exception:
        pass
    del _MARIGOLD_PIPE
    _MARIGOLD_PIPE = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def _load_stablenormal_pipe():
    global _STABLENORMAL_PIPE
    if _STABLENORMAL_PIPE is None:
        import torch
        from scripts.model_manager.integration import directory
        code=directory('stablenormal-code')
        weights=directory('stablenormal')
        if not str(weights).endswith('yoso-normal-v0-3'):
            raise RuntimeError('StableNormal requires its managed installation layout. Use Models to install it.')
        _STABLENORMAL_PIPE = torch.hub.load(str(code), 'StableNormal_turbo',
            source='local',trust_repo=True,yoso_version=str(weights))
    return _STABLENORMAL_PIPE


def _unload_stablenormal_pipe():
    global _STABLENORMAL_PIPE
    if _STABLENORMAL_PIPE is None:
        return
    import gc
    import torch
    del _STABLENORMAL_PIPE
    _STABLENORMAL_PIPE = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def bake_normal_marigold(albedo_img, uv_size: int = 2048):
    """High-quality: Marigold-Normal v1-1 predicts surface normals from the
    albedo texture. ~5 GB VRAM, ~30-60 s; install Marigold from Models first.
    Best perceptual surface detail (bricks, panel seams, window mullions).
    Returns a PIL.Image in 'RGB' mode at (uv_size, uv_size)."""
    from PIL import Image as _Image
    pipe = _load_marigold_pipe()
    src = albedo_img.convert("RGB")
    if src.size != (uv_size, uv_size):
        src = src.resize((uv_size, uv_size), _Image.LANCZOS)
    result = pipe(src)
    vis = pipe.image_processor.visualize_normals(result.prediction)
    out = vis[0] if hasattr(vis, "__iter__") else vis
    if out.size != (uv_size, uv_size):
        out = out.resize((uv_size, uv_size), _Image.LANCZOS)
    return out.convert("RGB")


def bake_normal_stablenormal(albedo_img, uv_size: int = 2048):
    """Low-cost AI: Stable-X/StableNormal (turbo). ~3 GB VRAM, ~10-15 s,
    Install StableNormal from Models first. Faster than Marigold, slightly less
    sharp on fine detail.
    Returns a PIL.Image in 'RGB' mode at (uv_size, uv_size)."""
    from PIL import Image as _Image
    predictor = _load_stablenormal_pipe()
    src = albedo_img.convert("RGB")
    if src.size != (uv_size, uv_size):
        src = src.resize((uv_size, uv_size), _Image.LANCZOS)
    out = predictor(src)
    if out.size != (uv_size, uv_size):
        out = out.resize((uv_size, uv_size), _Image.LANCZOS)
    return out.convert("RGB")


def _bake_normal_map(mesh, albedo_img, baker: str = "low", uv_size: int = 2048):
    """Dispatcher. See module docstring above for the four bakers.

    Returns a PIL.Image (RGB normal map in UV space), or None when
    baker == "off". Falls back to "low" (mesh-based geometry bake) if an AI
    baker fails (missing model, OOM, no albedo, etc.) so we never silently
    lose the normal map.

    Accepted values: "off", "low", "medium", "high".
    Legacy alias: "geometry" -> "low".
    """
    baker = (baker or "low").lower()
    if baker == "geometry":
        baker = "low"

    if baker == "off":
        print("[lod_export] normal_baker=off - skipping normal map.")
        return None

    if baker == "low":
        print(f"[lod_export] Baking tangent-space normal map (low, NumPy "
              f"mesh-derived) at {uv_size}x{uv_size}.")
        return _normal_result(bake_tangent_normal_to_uv(mesh, uv_size=uv_size), "low", baker)

    if albedo_img is None:
        print(f"[lod_export] WARN: normal_baker={baker!r} needs an albedo "
              f"texture but none was found on the painted mesh. "
              f"Falling back to 'low' (mesh-derived).")
        return _normal_result(bake_tangent_normal_to_uv(mesh, uv_size=uv_size), "low", baker)

    try:
        if baker == "medium":
            print(f"[lod_export] Baking normal map via Stable-X/StableNormal "
                  f"(turbo) at {uv_size}x{uv_size}, using installed weights.")
            try:
                return _normal_result(bake_normal_stablenormal(albedo_img, uv_size=uv_size), "medium", baker)
            finally:
                _unload_stablenormal_pipe()
        if baker == "high":
            print(f"[lod_export] Baking normal map via Marigold-Normal v1-1 "
                  f"at {uv_size}x{uv_size}, using installed weights.")
            try:
                return _normal_result(bake_normal_marigold(albedo_img, uv_size=uv_size), "high", baker)
            finally:
                _unload_marigold_pipe()
    except ImportError as e:
        print(f"[lod_export] AI normal baker {baker!r} cannot import its deps: "
              f"{e}\n               Falling back to 'low' (mesh-derived).")
        return _normal_result(bake_tangent_normal_to_uv(mesh, uv_size=uv_size), "low", baker)
    except Exception as e:
        print(f"[lod_export] AI normal baker {baker!r} failed: {e}\n"
              f"               Falling back to 'low' (mesh-derived).")
        return _normal_result(bake_tangent_normal_to_uv(mesh, uv_size=uv_size), "low", baker)

    raise ValueError(
        f"Unknown normal_baker={baker!r}. Choose from: off, low, medium, high.")


def bake_normal_map(mesh, albedo_img, baker="low", uv_size=2048):
    return _bake_normal_map(mesh, albedo_img, baker=baker, uv_size=uv_size)

def _normal_result(image, actual, requested):
    if image is not None:
        image.info["modelunify_baker"] = actual
        image.info["modelunify_requested_baker"] = requested
    print(f"[normal] requested={requested}; actual={actual if image is not None else 'skipped (no valid UVs)'}")
    return image

# =============================================================================
# Helpers
# =============================================================================

def bake_tangent_normal_to_uv(mesh: trimesh.Trimesh, uv_size: int = 2048):
    """Bake a tangent-space normal map from the mesh's per-vertex normals
    into the mesh's existing UV layout.

    Why this exists
    ---------------
    The Hunyuan3D-2.1 paint pipeline produces only `albedo` and
    `metallicRoughness` maps - it uses normal maps as conditioning input but
    does not output one. To get a tangent-space normal map for BMS we have to
    bake one ourselves from the geometry we already have.

    What this gives you
    -------------------
    - For LOD0 (the highest-poly mesh), the result is approximately flat blue
      (R=128, G=128, B=255) - the per-vertex smooth normals already match the
      surface's local tangent frame at every point.
    - For LOWER LODs that share this same UV layout (which is what
      `_decimate_keep_uv` arranges), sampling this LOD0-derived map gives
      them LOD0's surface orientation at each UV pixel, recovering some of
      the shading they'd otherwise lose to decimation.

    Implementation
    --------------
    Pure NumPy. Per-face barycentric rasterization with bilinear-style
    accumulation. ~1-3 s for a 50k-face mesh at 2048², ~10 s for 200k faces.
    No external rasterizer (nvdiffrast, Blender, OpenGL) required.

    Returns a PIL.Image in 'RGB' mode, shape (uv_size, uv_size, 3).
    Returns None if the mesh has no UVs.
    """
    from PIL import Image as _Image

    uv = getattr(mesh.visual, "uv", None)
    if uv is None or len(uv) == 0:
        return None
    uv = np.asarray(uv, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.asarray(mesh.vertices, dtype=np.float32)
    vnorm = np.asarray(mesh.vertex_normals, dtype=np.float32)

    if len(faces) == 0:
        # Empty mesh - return a flat-blue identity normal map.
        flat = np.zeros((uv_size, uv_size, 3), dtype=np.uint8)
        flat[..., 0] = 128; flat[..., 1] = 128; flat[..., 2] = 255
        return _Image.fromarray(flat, mode="RGB")

    # Per-face vertex/uv/normal lookups.
    v0 = verts[faces[:, 0]]; v1 = verts[faces[:, 1]]; v2 = verts[faces[:, 2]]
    uv0 = uv[faces[:, 0]];   uv1 = uv[faces[:, 1]];   uv2 = uv[faces[:, 2]]
    n0v = vnorm[faces[:, 0]]; n1v = vnorm[faces[:, 1]]; n2v = vnorm[faces[:, 2]]

    e1 = v1 - v0
    e2 = v2 - v0
    duv1 = uv1 - uv0
    duv2 = uv2 - uv0

    # Per-face geometric normal.
    fnorm = np.cross(e1, e2)
    flen = np.linalg.norm(fnorm, axis=1, keepdims=True)
    fnorm = np.divide(fnorm, np.maximum(flen, 1e-12))

    # Per-face tangent T from UV gradients (standard MikkTSpace-ish formula,
    # without the bitangent-handedness sign flip - good enough for buildings).
    denom = duv1[:, 0] * duv2[:, 1] - duv2[:, 0] * duv1[:, 1]
    f_inv = np.where(np.abs(denom) > 1e-8, 1.0 / denom, 0.0).reshape(-1, 1)
    T = f_inv * (duv2[:, 1:2] * e1 - duv1[:, 1:2] * e2)
    # Orthonormalize T against the face normal so (T, B, N) is a real frame.
    T = T - np.sum(T * fnorm, axis=1, keepdims=True) * fnorm
    Tlen = np.linalg.norm(T, axis=1, keepdims=True)
    T = np.divide(T, np.maximum(Tlen, 1e-12))
    B = np.cross(fnorm, T)

    def _to_tan(nw):
        return np.stack([
            np.sum(T * nw, axis=1),
            np.sum(B * nw, axis=1),
            np.sum(fnorm * nw, axis=1),
        ], axis=1)

    nt0 = _to_tan(n0v)
    nt1 = _to_tan(n1v)
    nt2 = _to_tan(n2v)
    # Renormalize per-vertex tangent-space normals.
    for nt in (nt0, nt1, nt2):
        nl = np.linalg.norm(nt, axis=1, keepdims=True)
        np.divide(nt, np.maximum(nl, 1e-12), out=nt)

    # UV (0..1, +Y up) to image-space pixels (+Y down).
    px0 = np.stack([uv0[:, 0] * uv_size, (1.0 - uv0[:, 1]) * uv_size], axis=1)
    px1 = np.stack([uv1[:, 0] * uv_size, (1.0 - uv1[:, 1]) * uv_size], axis=1)
    px2 = np.stack([uv2[:, 0] * uv_size, (1.0 - uv2[:, 1]) * uv_size], axis=1)

    img = np.zeros((uv_size, uv_size, 3), dtype=np.float32)
    weight = np.zeros((uv_size, uv_size), dtype=np.float32)

    F = len(faces)
    for fi in range(F):
        p0 = px0[fi]; p1 = px1[fi]; p2 = px2[fi]
        n0t = nt0[fi]; n1t = nt1[fi]; n2t = nt2[fi]

        x_min = max(0, int(np.floor(min(p0[0], p1[0], p2[0]))))
        x_max = min(uv_size - 1, int(np.ceil(max(p0[0], p1[0], p2[0]))))
        y_min = max(0, int(np.floor(min(p0[1], p1[1], p2[1]))))
        y_max = min(uv_size - 1, int(np.ceil(max(p0[1], p1[1], p2[1]))))
        if x_min > x_max or y_min > y_max:
            continue

        denom_e = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
        if abs(denom_e) < 1e-9:
            continue

        xs = np.arange(x_min, x_max + 1, dtype=np.float32) + 0.5
        ys = np.arange(y_min, y_max + 1, dtype=np.float32) + 0.5
        X, Y = np.meshgrid(xs, ys)

        a = ((p1[1] - p2[1]) * (X - p2[0]) + (p2[0] - p1[0]) * (Y - p2[1])) / denom_e
        b = ((p2[1] - p0[1]) * (X - p2[0]) + (p0[0] - p2[0]) * (Y - p2[1])) / denom_e
        c = 1.0 - a - b
        inside = (a >= 0) & (b >= 0) & (c >= 0)
        if not inside.any():
            continue

        nx = a * n0t[0] + b * n1t[0] + c * n2t[0]
        ny = a * n0t[1] + b * n1t[1] + c * n2t[1]
        nz = a * n0t[2] + b * n1t[2] + c * n2t[2]

        ys_grid = np.arange(y_min, y_max + 1).reshape(-1, 1)
        xs_grid = np.arange(x_min, x_max + 1).reshape(1, -1)
        Y_idx = np.broadcast_to(ys_grid, X.shape)[inside]
        X_idx = np.broadcast_to(xs_grid, X.shape)[inside]

        img[Y_idx, X_idx, 0] += nx[inside]
        img[Y_idx, X_idx, 1] += ny[inside]
        img[Y_idx, X_idx, 2] += nz[inside]
        weight[Y_idx, X_idx] += 1.0

    covered = weight > 0.5
    safe_w = np.where(covered, weight, 1.0)[..., None]
    img = img / safe_w
    nlen = np.linalg.norm(img, axis=2, keepdims=True)
    img = img / np.maximum(nlen, 1e-12)
    rgb = ((img + 1.0) * 0.5 * 255.0).clip(0, 255).astype(np.uint8)
    # Pixels outside any UV island get the identity (flat blue) value.
    rgb[~covered] = [128, 128, 255]
    return _Image.fromarray(rgb, mode="RGB")


def _write_pbr_readme(saved: dict, out_dir: Path) -> None:
    """Describe only maps actually emitted, with honest normal provenance."""
    descriptions = {
        "albedo": "base color from source material; inspect baked lighting",
        "metallic_roughness": "glTF packing: G=roughness, B=metallic",
        "roughness": "scalar G channel extracted for Wavefront map_Pr",
        "metallic": "scalar B channel extracted for Wavefront map_Pm",
        "normal": "source normal retained or generated locally; inspect orientation",
        "occlusion": "occlusion map retained from source material",
        "emissive": "emissive map retained from source material",
    }
    lines = ["PBR maps actually written\n=========================\n"]
    lines += [f"{filename}: {descriptions.get(kind, kind)}\n" for kind, filename in saved.items()]
    provenance = out_dir / "normal_bake.json"
    if provenance.exists():
        lines.append("Normal bake: " + provenance.read_text(encoding="utf-8") + "\n")
    lines += [
        "\nGLB levels embed usable maps; levels that lose UVs use a flat average albedo.\n",
        "Read lod_report.json for actual face counts, UV state and fallback methods.\n",
        "Materials.mtl here is Wavefront interchange, not the BMS exporter's JSON.\n",
        "No DDS, height or BML is generated by this LOD export. Use the external BMS exporter.\n",
        "For optional AO/wetness/ARMW enhancement, see scripts/enhance_model.py.\n",
    ]
    (out_dir / "PBR_MAPS_README.txt").write_text("".join(lines), encoding="utf-8")


def _extract_textures(mesh: trimesh.Trimesh) -> dict:
    """Pull (albedo, metallic_roughness, normal) PIL images off mesh.visual.material.

    Trimesh's PBRMaterial uses glTF-style names (baseColorTexture,
    metallicRoughnessTexture, normalTexture). Standard SimpleMaterial uses
    .image. We handle both.
    """
    out = {}
    mat = getattr(mesh.visual, "material", None)
    if mat is None:
        return out

    # PBR (glTF) names
    bc = getattr(mat, "baseColorTexture", None)
    if bc is not None:
        out["albedo"] = bc
    mr = getattr(mat, "metallicRoughnessTexture", None)
    if mr is not None:
        out["metallic_roughness"] = mr
    nrm = getattr(mat, "normalTexture", None)
    if nrm is not None:
        out["normal"] = nrm
    emi = getattr(mat, "emissiveTexture", None)
    if emi is not None:
        out["emissive"] = emi
    occ = getattr(mat, "occlusionTexture", None)
    if occ is not None:
        out["occlusion"] = occ

    # SimpleMaterial fallback: a single diffuse image
    if not out:
        img = getattr(mat, "image", None)
        if img is not None:
            out["albedo"] = img
    return out


def _build_mtl(material_name: str, saved_textures: dict) -> str:
    """Build a Wavefront MTL string with PBR map references.

    Uses the modern PBR extension keys (map_Pm/map_Pr) which the BMS
    Blender Plugin and most modern importers understand. Also references
    the BMS-conventional ARMW map and normal/height placeholder maps.
    """
    lines = [
        f"# Materials.mtl - shared across all LODs for asset {material_name}\n",
        "# Generated by Modelunify. References every PBR map in this folder.\n",
        "# Wavefront editing sidecar; LOD meshes are self-contained GLBs.\n\n",
        f"newmtl {material_name}\n",
        "Ka 1.000 1.000 1.000\n",
        "Kd 1.000 1.000 1.000\n",
        "Ks 0.000 0.000 0.000\n",
        "Ke 0.000 0.000 0.000\n",
        "Ni 1.500\n",
        "d 1.000\n",
        "illum 2\n",
    ]
    if "albedo" in saved_textures:
        lines.append(f"map_Kd {saved_textures['albedo']}\n")
    if "metallic_roughness" in saved_textures:
        lines.append(f"map_Pm {saved_textures['metallic']}\n")
        lines.append(f"map_Pr {saved_textures['roughness']}\n")
    if "normal" in saved_textures:
        # The painter doesn't produce this; only present if the source GLB
        # already carried a real normal map. We don't write a placeholder.
        lines.append(f"map_Bump {saved_textures['normal']}\n")
        lines.append(f"norm {saved_textures['normal']}\n")
    if "occlusion" in saved_textures:
        lines.append(f"map_Ka {saved_textures['occlusion']}\n")
    if "emissive" in saved_textures:
        lines.append(f"map_Ke {saved_textures['emissive']}\n")
    return "".join(lines)


def _write_obj_with_external_mtl(
    mesh: trimesh.Trimesh,
    out_path: Path,
    *,
    mtllib_name: str,
    material_name: str,
) -> None:
    """Export `mesh` as OBJ and patch its mtllib/usemtl lines to point at a
    shared external Materials.mtl + material name."""
    obj_text = mesh.export(file_type="obj")
    if isinstance(obj_text, bytes):
        obj_text = obj_text.decode("utf-8", errors="replace")

    # If trimesh emitted a mtllib line, replace it; otherwise prepend one.
    if re.search(r"^mtllib\s+", obj_text, flags=re.MULTILINE):
        obj_text = re.sub(r"^mtllib\s+\S+",
                          f"mtllib {mtllib_name}", obj_text, flags=re.MULTILINE)
    else:
        obj_text = f"mtllib {mtllib_name}\n" + obj_text

    # Same for usemtl.
    if re.search(r"^usemtl\s+", obj_text, flags=re.MULTILINE):
        obj_text = re.sub(r"^usemtl\s+\S+",
                          f"usemtl {material_name}", obj_text, flags=re.MULTILINE)
    else:
        # Inject usemtl after the mtllib line.
        obj_text = obj_text.replace(
            f"mtllib {mtllib_name}\n",
            f"mtllib {mtllib_name}\nusemtl {material_name}\n",
            1,
        )

    # Trimesh sometimes writes a sibling .mtl alongside the .obj during export
    # via filename. We're using the text path so no sibling file is produced.
    out_path.write_text(obj_text, encoding="utf-8")


def average_albedo_rgba(albedo_img, default=(128, 128, 128, 255)) -> tuple:
    """Mean opaque colour of an albedo texture, as an 8-bit RGBA tuple.

    Used as the flat colour for LODs that lost their UVs. A distant LOD
    tinted with the model's own average reads as the same object getting
    smaller; a neutral grey one pops against its neighbours at the swap
    distance. Fully transparent texels are excluded so cut-out atlases
    (fences, foliage) don't average towards their empty background.
    """
    if albedo_img is None:
        return default
    try:
        from PIL import Image as _Image
        img = albedo_img.convert("RGBA")
        # Thumbnail first: the mean is identical to within rounding, and a
        # 4k atlas would otherwise cost ~200 MB as a float array.
        if max(img.size) > 256:
            img = img.resize((256, 256), _Image.BILINEAR)
        arr = np.asarray(img, dtype=np.float32)
        opaque = arr[..., 3] > 8
        if not opaque.any():
            return default
        rgb = arr[..., :3][opaque].mean(axis=0)
        return (int(round(rgb[0])), int(round(rgb[1])), int(round(rgb[2])), 255)
    except Exception as _e:
        print(f"[lod_export] average_albedo_rgba failed ({_e}) - using {default}.")
        return default


def _flat_colour_visual(mesh: trimesh.Trimesh, rgba: tuple, name: str):
    """Give `mesh` a single untextured colour, in place.

    Applied when decimation destroys the UVs: the LOD can no longer sample
    the shared atlas, and leaving the old material attached makes the
    renderer index a UV set that isn't there (garbage texels, or black).

    Uses a `baseColorFactor` on a texture-less PBRMaterial. Do NOT also set
    vertex colours: attaching a material to a ColorVisuals makes trimesh's
    glTF exporter treat the mesh as textured and silently drop both the
    colours and the factor, so the LOD round-trips with no colour at all.
    One or the other survives, never both — and a material slot is what
    Blender and the BMS exporter want to see.
    """
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            name=name,
            baseColorFactor=[c / 255.0 for c in rgba],
            metallicFactor=0.0,
            roughnessFactor=0.9,
        )
    )
    return mesh


def _decimate_keep_uv(mesh: trimesh.Trimesh, target_faces: int, *, max_passes: int = 3,
                      preserve_boundary: bool = False) -> trimesh.Trimesh:
    """UV-seam-aware quadric edge collapse decimation.

    Why this is non-trivial: a textured mesh loaded from a GLB has its
    vertices "split at seams" - the same 3D position may appear as multiple
    vertex entries, each carrying a different UV (one per UV island border).
    A naive geometry-only decimator (fast_simplification / trimesh's
    `simplify_quadric_decimation`) doesn't see the UVs, so it happily
    collapses across seams. Re-attaching UVs by 3D nearest-neighbor after
    the fact is wrong at every seam - the closest pre-decimation vertex
    might belong to the OTHER UV island, so faces grab UVs from the wrong
    texture region. Visually this shows up as "chrome" / mirror reflections
    and shattered facade textures starting at LOD1.

    Fix: use pymeshlab's `meshing_decimation_quadric_edge_collapse_with_texture`,
    which knows about per-wedge UVs and respects seams. Each face carries
    its three UVs through the collapse; the algorithm only collapses edges
    that share UV coordinates on both ends, or weights collapses by UV-space
    distortion (`extratcoordw`). After decimation we read the per-wedge UVs
    back and split vertices at seams to convert to the per-vertex UV layout
    trimesh wants.

    Falls back to the old KDTree method only if pymeshlab is unavailable or
    the texture-aware filter raises - and logs which path was taken.
    """
    if isinstance(max_passes, bool) or not 1 <= max_passes <= 3 or int(max_passes) != max_passes:
        raise ValueError("Decimation passes must be an integer from 1 to 3.")
    if mesh.faces.shape[0] <= target_faces:
        return mesh.copy()

    old_pos = np.asarray(mesh.vertices, dtype=np.float64)
    old_faces = np.asarray(mesh.faces, dtype=np.int32)
    old_uv = np.asarray(mesh.visual.uv, dtype=np.float64) \
             if hasattr(mesh.visual, "uv") and mesh.visual.uv is not None else None
    old_material = getattr(mesh.visual, "material", None)

    # No UVs to preserve - just decimate geometry.
    if old_uv is None or old_uv.shape[0] != old_pos.shape[0]:
        try:
            return mesh.simplify_quadric_decimation(
                face_count=int(target_faces), aggression=3)
        except TypeError:
            return mesh.simplify_quadric_decimation(int(target_faces))

    # ---- Preferred path: pymeshlab texture-aware quadric decimation ----
    #
    # Implementation detail: pymeshlab's `meshing_decimation_quadric_edge_
    # collapse_with_texture` requires per-face texture state (each face must
    # be assigned to a texture by index), and constructing that state from
    # raw numpy matrices is not exposed in the python API. The reliable way
    # is to write the mesh to a tmp OBJ + MTL + texture PNG and have
    # pymeshlab `load_new_mesh` set it all up. We then run the filter, save
    # back to OBJ, and reload via trimesh - reattaching the original PBR
    # material so metallic/roughness/normal maps survive.
    import tempfile, shutil
    tmp_dir = None
    try:
        import pymeshlab  # type: ignore

        # #region agent log
        _dbg("lod_export.py:_decimate_keep_uv:pymeshlab_attempt",
             "Trying pymeshlab texture-aware decimator (OBJ-roundtrip path)",
             {"target_faces": int(target_faces),
              "input_faces": int(old_faces.shape[0]),
              "input_verts": int(old_pos.shape[0]),
              "uv_shape": list(old_uv.shape)},
             hypothesis_id="H_SEAM,H_WEDGE_API")
        # #endregion

        tmp_dir = tempfile.mkdtemp(prefix="lod_decimate_")
        tmp_in = f"{tmp_dir}/in.obj"
        tmp_out = f"{tmp_dir}/out.obj"

        # Export to OBJ - trimesh writes OBJ + sibling MTL + texture PNG that
        # pymeshlab can pick up. Note: we must export the GLB-loaded mesh as
        # an OBJ that retains the diffuse texture; trimesh does this when
        # the visual.material has a baseColorTexture / diffuse image.
        mesh.export(tmp_in)

        ms = pymeshlab.MeshSet()
        ms.load_new_mesh(tmp_in)

        # Verified empirically with `residential_3_textured.glb` (40K faces):
        #   preserveboundary=True   -> bottoms out at ~11K faces (refuses to
        #                              collapse across UV-island borders, so
        #                              we can't reach low LOD targets)
        #   preserveboundary=False  -> hits target exactly, AND with
        #                              extratcoordw=1.0 the UV-space error
        #                              still dominates the collapse choice
        #                              so seams stay coherent (chrome /
        #                              shattered look gone)
        #   boundaryweight=1.0      -> still penalises boundary collapses but
        #                              doesn't lock them
        #   extratcoordw=1.0        -> weights UV-space distortion = 1x of 3D
        #                              error; keeps texture map intact
        passes = []
        previous = int(ms.current_mesh().face_number())
        for pass_index in range(int(max_passes)):
            ms.apply_filter(
                'meshing_decimation_quadric_edge_collapse_with_texture',
                targetfacenum=int(target_faces),
                qualitythr=0.3,
                extratcoordw=1.0,
                preserveboundary=preserve_boundary,
                boundaryweight=1.0,
                optimalplacement=True,
                preservenormal=True,
                planarquadric=True,
            )
            achieved = int(ms.current_mesh().face_number())
            passes.append({"pass": pass_index + 1, "before_faces": previous, "achieved_faces": achieved})
            # Reinitializing the collapse queue can unlock further valid edges.
            # Keep every safety parameter unchanged; never lower quality to zero.
            if achieved <= target_faces or achieved >= previous:
                break
            previous = achieved

        result = ms.current_mesh()
        out_faces = int(result.face_matrix().shape[0])
        out_verts = int(result.vertex_matrix().shape[0])
        out_wedge = result.wedge_tex_coord_matrix().shape

        ms.save_current_mesh(tmp_out)
        decim = trimesh.load(tmp_out, force="mesh", process=False)

        # Reattach the master's PBR material so metallic/roughness/normal
        # textures (which the OBJ roundtrip doesn't carry) come back.
        try:
            decim.visual.material = old_material
        except Exception:
            pass

        # #region agent log
        _dbg("lod_export.py:_decimate_keep_uv:pymeshlab_success",
             "pymeshlab texture-aware decimation succeeded",
             {"input_faces": int(old_faces.shape[0]),
              "target_faces": int(target_faces),
              "out_faces": out_faces,
              "out_verts": out_verts,
              "wedge_uv_shape": list(out_wedge),
              "trimesh_loaded_faces": int(decim.faces.shape[0]),
              "trimesh_loaded_verts": int(decim.vertices.shape[0]),
              "trimesh_has_uv": hasattr(decim.visual, "uv") and decim.visual.uv is not None,
              "trimesh_uv_count": len(decim.visual.uv) if (hasattr(decim.visual, "uv") and decim.visual.uv is not None) else 0,
              "material_class": type(getattr(decim.visual, "material", None)).__name__,
              "material_has_baseColor": getattr(getattr(decim.visual, "material", None), "baseColorTexture", None) is not None,
              "material_has_MR": getattr(getattr(decim.visual, "material", None), "metallicRoughnessTexture", None) is not None},
             hypothesis_id="H_SEAM,H_WEDGE_API")
        # #endregion

        decim.metadata["modelunify_uv_method"] = "pymeshlab texture-aware"
        decim.metadata["modelunify_decimation_passes"] = passes
        return decim

    except Exception as _pml_err:
        # #region agent log
        _dbg("lod_export.py:_decimate_keep_uv:pymeshlab_FAILED",
             "pymeshlab texture-aware decimation failed - falling back to KDTree",
             {"exception_type": type(_pml_err).__name__,
              "exception_msg": str(_pml_err),
              "traceback": traceback.format_exc()},
             hypothesis_id="H_FALLBACK")
        # #endregion
        print(f"[lod_export] WARN: pymeshlab UV-aware decimation failed ({_pml_err}); "
              f"falling back to KDTree nearest-neighbor (LOD may show texture seams).")
    finally:
        if tmp_dir is not None:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    # ---- Fallback: geometry decimation + KDTree UV transplant (the OLD method)
    # ---- Only runs if pymeshlab is unavailable or its filter raises.
    try:
        decimated = mesh.simplify_quadric_decimation(
            face_count=int(target_faces), aggression=3)
    except TypeError:
        decimated = mesh.simplify_quadric_decimation(int(target_faces))

    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(old_pos)
        new_pos = np.asarray(decimated.vertices, dtype=np.float64)
        _, idx = tree.query(new_pos, k=1)
        new_uv = old_uv[idx]
        visual = trimesh.visual.TextureVisuals(uv=new_uv, material=old_material)
        result = trimesh.Trimesh(
            vertices=decimated.vertices,
            faces=decimated.faces,
            visual=visual,
            process=False,
        )
        result.metadata["modelunify_uv_method"] = "KDTree fallback (may show texture seams)"
        return result
    except Exception as _uv_err:
        print(f"[lod_export] WARN: UV reattach also failed: {_uv_err}")
        return decimated


# -----------------------------------------------------------------------------
# BMS-spec template emitter
# -----------------------------------------------------------------------------
# These helpers write Falcon BMS-spec `Parent.dat` and `materials.mtl` (JSON)
# files into a `bms_template/` subfolder of the asset directory, alongside the
# Wavefront OBJ/MTL the modeller uses to load the geometry in Blender / 3ds Max.
# Spec source: "3D modellers How-to PBR/BML v0.4 for Falcon BMS" (Apr 2025).

# Metres -> feet. BMS Parent.dat values are in decimal feet; AI-generated
# meshes from TripoSG / Hunyuan3D are nominally in metres (glTF convention),
# though they are also normalised to a unit-ish bounding box, so the values
# we emit are deliberately starting points the modeller fine-tunes after
# scaling the model to real-world size in 3ds Max / Blender.
_M_TO_FT = 3.28084

# Default LOD viewing distances (feet) matching docs/BMS_WORKFLOW.md.
_DEFAULT_LOD_DISTANCES_FT = [500, 1500, 4000, 10000, 25000, 60000, 150000]


def _build_parent_dat(
    name: str,
    mesh: trimesh.Trimesh,
    lod_targets: Iterable[Tuple[str, int]],
) -> str:
    """Build a spec-compliant `Parent.dat` text for `mesh`.

    Format (per the BMS PBR/BML guide):
        Dimensions = R xmin xmax ymin ymax zmin zmax    (all in feet)
        TextureSets = 1
        Switches    = 0
        Dofs        = 0
        AddLOD      = Model_N.bml <distance_ft>
    """
    bounds = mesh.bounds  # shape (2, 3): [[xmin,ymin,zmin],[xmax,ymax,zmax]]
    xmin, ymin, zmin = (float(v) * _M_TO_FT for v in bounds[0])
    xmax, ymax, zmax = (float(v) * _M_TO_FT for v in bounds[1])
    radius_ft = float(np.linalg.norm(mesh.vertices, axis=1).max()) * _M_TO_FT

    lod_targets = list(lod_targets)
    distances = _DEFAULT_LOD_DISTANCES_FT[:len(lod_targets)]

    header = [
        f"# Parent.dat for {name}\n",
        "# Generated by Modelunify from the AI-produced mesh.\n",
        "# Spec: 3D modellers How-to PBR/BML v0.4 for Falcon BMS.\n",
        "#\n",
        "# Units: decimal feet. Source mesh assumed to be in metres; values were\n",
        f"#        scaled by {_M_TO_FT} (metres -> feet). The AI mesh is normalised,\n",
        "#        so re-run / re-measure these Dimensions after you scale the model\n",
        "#        to real-world size in 3ds Max or Blender.\n",
        "#\n",
        "# Tune before going in-game:\n",
        "#   - AddLOD viewing distances (the values below are sensible defaults).\n",
        "#   - Switches / Dofs counts if you add any animation in your modeller.\n",
        "#   - Add `AddSlot = X Y Z` lines for aircraft hardpoints (not needed\n",
        "#     for buildings, vehicles, or static props).\n",
        "\n",
    ]
    body = [
        f"Dimensions  = {radius_ft:.6f} "
        f"{xmin:.6f} {xmax:.6f} {ymin:.6f} {ymax:.6f} {zmin:.6f} {zmax:.6f}\n",
        "TextureSets = 1\n",
        "Switches    = 0\n",
        "Dofs        = 0\n",
    ]
    for (lod_name, _faces), dist_ft in zip(lod_targets, distances):
        body.append(f"AddLOD      = {lod_name}.bml {dist_ft}\n")

    return "".join(header + body)


def _build_bms_materials_mtl(name: str) -> str:
    """Build a BMS-format `materials.mtl` JSON scaffold for one PBR material.

    Material is named after the asset (matches the `usemtl` line we already
    write into each Model_N.obj). Texture filenames follow the BMS naming
    convention `<name>_Set1_ALB.dds` / `_ARMW.dds` / `_NOR.dds` so the
    modeller knows exactly what to bake and name.
    """
    payload = {
        "Materials": [
            {
                "Name": name,
                "Textures": [
                    {"Slot": 0, "File": f"{name}_Set1_ALB.dds"},
                    {"Slot": 1, "File": f"{name}_Set1_ARMW.dds"},
                    {"Slot": 2, "File": f"{name}_Set1_NOR.dds"},
                ],
                "Flags": {
                    "Cull": "BACK",
                    "ShadowCaster": 1,
                    "DepthBias": 0,
                    "SlopeScaledDepthBias": 0,
                },
                "ShaderParams": [],
                "Template": {"File": "PBR", "Material": "PBR"},
                "Samplers": [],
            }
        ]
    }
    return json.dumps(payload, indent=2) + "\n"


def _build_bms_template_readme(name: str) -> str:
    """Short README that lives inside `bms_template/` next to the generated
    BMS files. Tells the modeller what to do with them and quotes the PDF
    guide on PNG -> DDS conversion + copy-paste material blocks for Glass and
    Decals, since those are the most common extras after the solid PBR
    material we already emit."""
    return f"""\
bms_template/ - Falcon BMS-spec files for asset "{name}"
========================================================

What these two files are
------------------------
- Parent.dat     : asset-level metadata (bounding box, LOD distances, etc.)
- materials.mtl  : BMS PBR material definition (JSON, lowercase filename
                   on purpose - that's what BMS looks for).

What to do with them
--------------------
After you have converted the Model_N.obj files (one folder up) to
Model_N.bml using your preferred BMS exporter - 3ds Max BML Exporter or
the Blender BMS Plugin, the choice is yours - copy these two files into:

    <BMS install>\\Data\\TerrData\\Objects\\Models\\<XXXX>\\

...alongside your Model_N.bml files. Pick <XXXX> from an unused Parent ID
in the BMS Editor.

How this relates to the Wavefront MTL one folder up
---------------------------------------------------
The `Materials.mtl` (capital M) one folder up is a *Wavefront OBJ* MTL.
It exists so Blender / 3ds Max can auto-load the Model_N.obj files together
with the placeholder albedo.png / metallic_roughness.png. BMS itself does
not read that file - it reads the JSON `materials.mtl` in this folder.

Textures: PNG -> DDS conversion checklist
-----------------------------------------
BMS does not read PNGs. Before placing the asset in-game you must bake/save
your final textures as DDS files with these exact formats (BC7 / BC5 with
the right sRGB vs linear flag - getting this wrong shows up as wrong colours
in sim):

  {name}_Set1_ALB.dds   BC7_UNORM_SRGB    (Albedo,  sRGB,  with full mipchain)
  {name}_Set1_ARMW.dds  BC7_UNORM         (AO/Roughness/Metal/Wetness, linear)
  {name}_Set1_NOR.dds   BC5_UNORM         (Normal, XY only, tangent-space, linear)

The Intel Texture Works Photoshop plug-in handles all three with the right
presets. Verify the saved DDS header with Microsoft DirectXTex `texdiag info`:

    texdiag.exe info {name}_Set1_ALB.dds
    -> format = BC7_UNORM_SRGB     (correct)

If the format line does not match the table above, the texture is saved
wrong and will look wrong in sim.

The AI painter only produces albedo + a combined metallic/roughness map.
ARMW (AO + Roughness + Metal + Wetness) and NOR (Normal) need to be baked
from your final geometry in InstaMAT / Substance / Blender before going
in-game.

Optional extra material blocks (Glass, Decals)
----------------------------------------------
The materials.mtl below ships with one solid `"PBR"` material. If your
asset has glass panels or decals/license-plate-style geometry, add the
matching block(s) inside the `"Materials"` array. Names must be globally
unique across the whole game install, so prefix with the asset name.

Glass (transparent, uses albedo RGB for base reflectivity + alpha):

    {{
      "Name": "{name}_Glass",
      "Textures": [
        {{ "Slot": 0, "File": "{name}_Set1_ALB.dds" }},
        {{ "Slot": 1, "File": "{name}_Set1_ARMW.dds" }},
        {{ "Slot": 2, "File": "{name}_Set1_NOR.dds" }}
      ],
      "ShaderParams": [],
      "Template": {{ "File": "PBR", "Material": "PBR-Glass" }},
      "Samplers": []
    }}

Decals / license plates (transparent, alpha in albedo):

    {{
      "Name": "{name}_Decals",
      "Textures": [
        {{ "Slot": 0, "File": "{name}_Set1_L1_ALB.dds" }},
        {{ "Slot": 1, "File": "{name}_Set1_L1_ARMW.dds" }},
        {{ "Slot": 2, "File": "{name}_Set1_L1_NOR.dds" }}
      ],
      "ShaderParams": [],
      "Template": {{ "File": "PBR", "Material": "PBR-DefaultAlpha" }},
      "Samplers": []
    }}

For other variants (emissive, afterburner, billboard glow lights, etc.)
see the PBR/BML guide PDF.

Note
----
We deliberately do not emit `AddSlot = X Y Z` lines in Parent.dat. Those
are for aircraft hardpoints (racks / weapons). AI-generated assets here
are buildings / vehicles / static props that have no slots.
"""


def _write_bms_template(
    out_dir: Path,
    name: str,
    mesh: trimesh.Trimesh,
    lod_targets: Iterable[Tuple[str, int]],
) -> Path:
    """Write the BMS-spec `Parent.dat` + `materials.mtl` + README into a
    `bms_template/` subfolder of `out_dir`. Returns the subfolder path."""
    lod_targets = list(lod_targets)
    template_dir = out_dir / "bms_template"
    template_dir.mkdir(parents=True, exist_ok=True)

    (template_dir / "Parent.dat").write_text(
        _build_parent_dat(name, mesh, lod_targets), encoding="utf-8")
    (template_dir / "materials.mtl").write_text(
        _build_bms_materials_mtl(name), encoding="utf-8")
    (template_dir / "README.txt").write_text(
        _build_bms_template_readme(name), encoding="utf-8")
    return template_dir
