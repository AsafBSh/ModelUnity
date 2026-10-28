"""Normal embedding shared by the workbench without a UI dependency."""
from pathlib import Path
from scripts.lod_export import bake_normal_map

def _append_normal_to_mtl(mtl_path: Path, normal_filename: str) -> None:
    """Add `map_Bump` + `norm` references to an existing Wavefront MTL.

    Idempotent: if the MTL already references this normal map (e.g. because
    the user re-ran the same generation), the existing reference is left
    in place and no duplicates are added.

    The dual-directive write (`map_Bump` AND `norm`) mirrors the convention
    used elsewhere in this codebase (`lod_export._compose_mtl_lines`) and
    maximises compatibility: older OBJ importers (Maya, classic Blender)
    read `map_Bump`; modern glTF-aware ones read `norm`.
    """
    text = mtl_path.read_text(encoding="utf-8", errors="replace")
    needs_bump = f"map_Bump {normal_filename}" not in text
    needs_norm = f"norm {normal_filename}" not in text
    if not (needs_bump or needs_norm):
        return
    # Ensure trailing newline so our appended lines don't fuse onto a
    # pre-existing last line (e.g. if the painter's MTL didn't end with
    # one).
    if not text.endswith("\n"):
        text += "\n"
    if needs_bump:
        text += f"map_Bump {normal_filename}\n"
    if needs_norm:
        text += f"norm {normal_filename}\n"
    mtl_path.write_text(text, encoding="utf-8")


def _embed_normal_map_in_glb(glb_path: Path, baker: str) -> Path | None:
    """Bake a tangent-space normal map and embed it into a painted GLB.

    Hunyuan3D-2.1 paint outputs only albedo + metallicRoughness; it uses
    the normal direction as a CONDITIONING input but does not emit a normal
    texture. This helper synthesises one with the selected baker
    ("low"/"medium"/"high") and rewrites `glb_path` with the new map
    attached to the PBR material.

    The baked normal map is ALSO saved as a standalone PNG inside the
    asset folder, using the painter's naming convention so it sits
    next to the other texture maps:

        outputs/<asset_name>/
          <asset_name>.glb                          (this glb_path)
          <asset_name>_textured.jpg                  (albedo)
          <asset_name>_textured_metallic.jpg
          <asset_name>_textured_roughness.jpg
          <asset_name>_textured_normal.png           <-- this function adds this

    Without that on-disk PNG the "Normal map: Low/Medium/High" control
    appeared to do nothing (the embedded copy inside the GLB is
    invisible in a file explorer).

    Returns the path to the saved standalone normal-map PNG on success.
    Returns None if the bake was skipped (`baker == "off"`) or failed.
    """
    baker = (baker or "off").lower()
    if baker == "off":
        return None
    try:
        import trimesh
        import trimesh.visual.material as _mat
        loaded = trimesh.load(str(glb_path), force="mesh", process=False)
        if not isinstance(loaded, trimesh.Trimesh):
            print(f"[mv-unified] WARN: could not load {glb_path} as a single mesh "
                  f"for normal-map embed.")
            return None
        mat = getattr(loaded.visual, "material", None)
        if getattr(mat, "normalTexture", None) is not None:
            return None
        albedo = getattr(mat, "baseColorTexture", None) if mat is not None else None
        ref_size = max(albedo.size) if (albedo is not None and getattr(albedo, "size", None)) else 2048
        normal_img = bake_normal_map(loaded, albedo, baker=baker, uv_size=int(ref_size))
        if normal_img is None:
            return None
        if mat is None or not isinstance(mat, _mat.PBRMaterial):
            loaded.visual.material = _mat.PBRMaterial(
                name=getattr(mat, "name", "material") if mat is not None else "material",
                baseColorTexture=albedo,
            )
        import json
        (glb_path.with_suffix(".normal_bake.json")).write_text(json.dumps({
            "requested": baker, "actual": normal_img.info.get("modelunify_baker", "unknown")
        }), encoding="utf-8")
        loaded.visual.material.normalTexture = normal_img
        loaded.export(str(glb_path))

        # Save the baked normal as a real PNG next to the painter's
        # other texture files. The naming mirrors what the painter
        # itself writes (`<stem>_textured_metallic.jpg`,
        # `<stem>_textured_roughness.jpg`) so all four PBR channels
        # show up together in the asset folder.
        normal_png = glb_path.with_name(f"{glb_path.stem}_textured_normal.png")
        try:
            normal_img.save(str(normal_png))
            print(f"[mv-unified] Normal map saved: {normal_png}")
        except Exception as _e:
            print(f"[mv-unified] WARN: could not save standalone normal PNG: {_e}")
            return None

        # Also link the normal map into the painter's MTL file so the
        # OBJ companion (which 3D editors like Blender / Maya open
        # directly) carries the full PBR set instead of just albedo +
        # metallic + roughness. We use both `map_Bump` and `norm`
        # directives - same dual-line convention `_compose_mtl_lines`
        # uses in lod_export.py - which maximises compatibility:
        # older OBJ importers read `map_Bump`, glTF-aware ones read
        # `norm`.
        mtl_path = glb_path.with_name(f"{glb_path.stem}_textured.mtl")
        if mtl_path.exists():
            try:
                _append_normal_to_mtl(mtl_path, normal_png.name)
            except Exception as _e:
                print(f"[mv-unified] WARN: could not patch MTL "
                      f"`{mtl_path.name}` with normal map: {_e}")

        return normal_png
    except Exception as e:
        print(f"[mv-unified] WARN: normal-map embed failed: {e} - "
              f"continuing without one.")
        return None

