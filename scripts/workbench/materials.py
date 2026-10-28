"""Lightweight extraction of embedded glTF/SimpleMaterial images."""

def _extract_textures(mesh) -> dict:
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

