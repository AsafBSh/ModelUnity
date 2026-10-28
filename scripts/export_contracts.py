"""Preflight and atomic publication for static LOD exports."""

from functools import wraps
from inspect import signature
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import trimesh


def fresh_asset_dir(root, name):
    if (
        not name
        or Path(name).name != name
        or name in (".", "..")
        or any(c in name for c in "/\\:")
    ):
        raise ValueError("Asset name must be a single directory name.")
    dest = Path(root) / name
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"Refusing overwrite: {dest}. Choose a fresh asset name.")
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def mesh_status(mesh):
    uv = getattr(mesh.visual, "uv", None)
    mat = getattr(mesh.visual, "material", None)
    edge_uses = np.bincount(mesh.edges_unique_inverse)
    return {
        "triangles": len(mesh.faces),
        "vertices": len(mesh.vertices),
        "uv_valid": bool(
            uv is not None and len(uv) == len(mesh.vertices) and np.isfinite(uv).all()
        ),
        "materials": type(mat).__name__ if mat is not None else None,
        "textures": [
            key
            for key in (
                "baseColorTexture",
                "metallicRoughnessTexture",
                "normalTexture",
                "occlusionTexture",
                "emissiveTexture",
                "image",
            )
            if getattr(mat, key, None) is not None
        ],
        "components": len(
            trimesh.graph.connected_components(
                mesh.face_adjacency, nodes=np.arange(len(mesh.faces)), min_len=1
            )
        ),
        "bounds": mesh.bounds.tolist(),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "boundary_edges": int((edge_uses == 1).sum()),
        "nonmanifold_edges": int((edge_uses > 2).sum()),
    }


def load_static_master(path):
    path = Path(path)
    document = {}
    if path.suffix.lower() == ".gltf":
        document = json.loads(path.read_text(encoding="utf-8"))
    elif path.suffix.lower() == ".glb":
        import struct

        with path.open("rb") as stream:
            stream.seek(12)
            size, kind = struct.unpack("<II", stream.read(8))
            if kind == 0x4E4F534A:
                document = json.loads(stream.read(size))
    if document.get("animations") or document.get("skins"):
        raise ValueError(
            "Animated/skinned master detected. Export an explicitly baked static copy before LOD processing."
        )
    scene = trimesh.load(str(path), force="scene", process=False)
    print(
        f"[preflight] Source {Path(path).resolve()}; geometry={len(scene.geometry)}, "
        f"instances={len(scene.graph.nodes_geometry)}; static export cannot retain animation/DOFs."
    )
    if len(scene.geometry) != 1 or len(scene.graph.nodes_geometry) != 1:
        raise ValueError(
            "LOD export requires one static mesh/material. Merge/bake a copy explicitly first; master preserved."
        )
    # to_mesh applies the node transform; force='mesh' uses the same path.
    mesh = scene.to_mesh()
    if isinstance(
        getattr(mesh.visual, "material", None), trimesh.visual.material.MultiMaterial
    ):
        raise ValueError(
            "Multiple materials require explicit atlas baking before LOD export."
        )
    return mesh


def validate_targets(mesh, targets):
    targets = list(targets)
    if not targets or len(targets) > 7:
        raise ValueError("Request 1–7 LODs.")
    previous = len(mesh.faces) + 1
    for i, (name, target) in enumerate(targets):
        if (
            name != f"Model_{i}"
            or isinstance(target, bool)
            or int(target) != target
            or target <= 0
        ):
            raise ValueError(
                "Use ordered Model_0…Model_N names and positive integer face targets."
            )
        actual = min(int(target), len(mesh.faces))
        print(
            f"[preflight] {name}: target={target}, maximum={actual}"
            + (
                " (master retained without reduction)"
                if i == 0 and target >= len(mesh.faces)
                else ""
            )
        )
        if actual >= previous:
            raise ValueError(
                f"{name} would be a duplicate/no-op lower LOD. Use fewer levels or a scaled ladder."
            )
        previous = actual
    return targets


def validated_export(fn):
    """Stage the entire set, check achieved reduction, then publish to a fresh folder."""

    @wraps(fn)
    def run(*args, **kwargs):
        bound = signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        values = bound.arguments
        name = values["name"]
        if (
            not name
            or Path(name).name != name
            or name in (".", "..")
            or "/" in name
            or "\\" in name
        ):
            raise ValueError("Asset name must be a single directory name.")
        src = values.get("textured_glb_path")
        mesh = load_static_master(src) if src is not None else values["mesh"]
        if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
            raise ValueError("Master must contain finite, nonempty geometry.")
        status = mesh_status(mesh)
        if src is not None and not status["uv_valid"]:
            raise ValueError("Textured master needs finite per-vertex UV coordinates.")
        print("[preflight] " + json.dumps(status))
        targets = validate_targets(mesh, values["lod_targets"])
        root = Path(values["out_root"]).resolve()
        destination = root / name
        print(f"[preflight] Output: {destination}; source master remains intact.")
        if destination.exists():
            raise FileExistsError(
                f"Refusing overwrite: {destination}. Choose a new asset name/output root."
            )
        if isinstance(
            getattr(mesh.visual, "material", None),
            trimesh.visual.material.MultiMaterial,
        ):
            raise ValueError(
                "Multiple materials need explicit atlas baking before LOD processing."
            )
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".lod-stage-", dir=root) as stage:
            values["out_root"] = Path(stage)
            values["lod_targets"] = targets
            result = fn(**values)
            rows = []
            previous = len(mesh.faces) + 1
            for lod_name, target in targets:
                output = trimesh.load(
                    result / f"{lod_name}.glb", force="mesh", process=False
                )
                actual = len(output.faces)
                if actual <= 0 or actual >= previous:
                    raise ValueError(
                        f"{lod_name}: achieved {actual} faces, previous {previous}; refusing duplicate/no-op output."
                    )
                row = {
                    "lod": lod_name,
                    "target_faces": int(target),
                    "achieved_faces": actual,
                    "uv_valid": mesh_status(output)["uv_valid"],
                    "master_no_op": lod_name == "Model_0" and actual == len(mesh.faces),
                    "uv_method": output.metadata.get(
                        "modelunify_uv_method", "unchanged or geometry-only"
                    ),
                }
                row["uv_fallback"] = (
                    "flat average albedo"
                    if status["uv_valid"] and not row["uv_valid"]
                    else None
                )
                if row["uv_valid"]:
                    expected = {
                        "baseColorTexture" if key == "image" else key
                        for key in status["textures"]
                    }
                    material = getattr(output.visual, "material", None)
                    missing = [
                        key for key in expected if getattr(material, key, None) is None
                    ]
                    if missing:
                        raise ValueError(
                            f"{lod_name}: GLB round-trip lost PBR maps: {missing}"
                        )
                rows.append(row)
                previous = actual
                print("[export] " + json.dumps(row))
            (result / "lod_report.json").write_text(
                json.dumps(
                    {
                        "source": str(src) if src else "in-memory mesh",
                        "master": status,
                        "levels": rows,
                        "static_export": True,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            # Windows rename refuses an existing destination, including a concurrent publication.
            result.rename(destination)
        return destination

    return run
