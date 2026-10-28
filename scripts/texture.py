"""
Texture baker.

TripoSG returns geometry only (no texture). For buildings, the cheapest useful
texture is a planar projection of the source photo onto the mesh's front face,
plus xatlas UV unwrap so it can be re-edited in Blender / Substance / etc.

Output: a textured `.glb` containing the mesh + baked albedo PNG.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import numpy as np
import trimesh
from PIL import Image


def planar_project_front(
    mesh: trimesh.Trimesh,
    image: Union[str, Image.Image],
    *,
    front_axis: str = "+z",
    flip_v: bool = True,
) -> trimesh.Trimesh:
    """Project `image` onto `mesh` as a planar texture from `front_axis`.

    front_axis: one of '+x','-x','+y','-y','+z','-z' — the direction the
    photo is "looking from". Default is +Z (TripoSG's canonical front).
    """
    if isinstance(image, (str, Path)):
        img = Image.open(image).convert("RGB")
    else:
        img = image.convert("RGB")

    axis = front_axis.lstrip("+-").lower()
    sign = -1.0 if front_axis.startswith("-") else 1.0

    verts = mesh.vertices.copy()
    # Pick the two axes orthogonal to `axis` to use as UV coordinates.
    axis_idx = {"x": 0, "y": 1, "z": 2}[axis]
    u_idx, v_idx = [i for i in (0, 1, 2) if i != axis_idx]

    u = verts[:, u_idx] * sign
    v = verts[:, v_idx]

    # Normalize to [0,1] across the mesh's bounding box.
    def _norm(arr):
        lo, hi = arr.min(), arr.max()
        if hi - lo < 1e-9:
            return np.zeros_like(arr)
        return (arr - lo) / (hi - lo)

    uv = np.stack([_norm(u), _norm(v)], axis=-1)
    if flip_v:
        uv[:, 1] = 1.0 - uv[:, 1]

    material = trimesh.visual.material.PBRMaterial(
        name="planar_proj",
        baseColorTexture=img,
        metallicFactor=0.0,
        roughnessFactor=0.9,
    )
    visual = trimesh.visual.TextureVisuals(uv=uv, material=material)

    out = trimesh.Trimesh(
        vertices=verts,
        faces=mesh.faces.copy(),
        visual=visual,
        process=False,
    )
    return out


def try_xatlas_unwrap(mesh: trimesh.Trimesh) -> Optional[np.ndarray]:
    """Generate proper UVs with xatlas. Returns per-vertex UV array or None
    if xatlas isn't available."""
    try:
        import xatlas
    except Exception:
        return None
    atlas = xatlas.Atlas()
    atlas.add_mesh(mesh.vertices, mesh.faces)
    atlas.generate()
    vmapping, indices, uvs = atlas.get_mesh(0)
    # We have to reindex the mesh to match xatlas's vertex mapping.
    new_verts = mesh.vertices[vmapping]
    new_faces = indices
    mesh.vertices = new_verts
    mesh.faces = new_faces
    return uvs
