"""Load a binary FBX with UVs (fbxloader drops LayerElement* children)."""
from __future__ import annotations

import copy
import fbxloader
from fbxloader import BinaryReader, parse_binary_fbx as _orig_parse  # noqa: F401
import numpy as np
import trimesh
from PIL import Image
from trimesh.visual.material import PBRMaterial


def parse_binary_fbx_keep_layers(data: bytes) -> dict:
    """Same as fbxloader.parse_binary_fbx but keeps LayerElement* subtrees."""
    import fbxloader as fl

    orig = None

    def parse_subNode(name, node, subNode):
        if subNode.get("singleProperty"):
            extra = [
                k
                for k in subNode
                if k
                not in (
                    "singleProperty",
                    "propertyList",
                    "name",
                    "id",
                    "attrName",
                    "attrType",
                )
            ]
            if extra:
                node[subNode["name"]] = subNode
                value = subNode["propertyList"][0]
                if isinstance(value, list):
                    subNode["a"] = value
                return
        return orig(name, node, subNode)

    # Patch the nested function by replaying parse with a wrapped module.
    # fbxloader defines parse_subNode inside parse_binary_fbx; we reimplement
    # by calling the original after injecting a keep-layers wrapper via
    # copying source logic from the installed package.
    reader_src = fl.__file__
    ns: dict = {}
    code = open(reader_src, encoding="utf-8").read()
    # Replace the collapse-to-scalar branch so LayerElement nodes survive.
    old = """        if subNode['singleProperty']:
            value = subNode['propertyList'][0]
            if isinstance(value, list):
                node[subNode['name']] = subNode
                subNode['a'] = value
            else:
                node[subNode['name']] = value"""
    new = """        if subNode['singleProperty']:
            value = subNode['propertyList'][0]
            extra = [k for k in subNode if k not in (
                'singleProperty', 'propertyList', 'name', 'id',
                'attrName', 'attrType')]
            if extra:
                node[subNode['name']] = subNode
                if isinstance(value, list):
                    subNode['a'] = value
            elif isinstance(value, list):
                node[subNode['name']] = subNode
                subNode['a'] = value
            else:
                node[subNode['name']] = value"""
    if old not in code:
        raise RuntimeError("fbxloader parse_subNode pattern changed")
    ns = {
        "__name__": "fbxloader",
        "__file__": reader_src,
        "__package__": "fbxloader",
    }
    exec(compile(code.replace(old, new, 1), reader_src, "exec"), ns)
    return ns["parse_binary_fbx"](data)


def _layer_uv(geo: dict):
    layer = geo.get("LayerElementUV")
    if not isinstance(layer, dict):
        return None, None, None, None
    mapping = layer.get("MappingInformationType")
    if isinstance(mapping, dict):
        mapping = mapping.get("propertyList", [None])[0]
    ref = layer.get("ReferenceInformationType")
    if isinstance(ref, dict):
        ref = ref.get("propertyList", [None])[0]
    uv_node = layer.get("UV")
    idx_node = layer.get("UVIndex")
    uvs = None
    if isinstance(uv_node, dict) and "a" in uv_node:
        uvs = np.asarray(uv_node["a"], dtype=np.float64).reshape(-1, 2)
    indices = None
    if isinstance(idx_node, dict) and "a" in idx_node:
        indices = np.asarray(idx_node["a"], dtype=np.int64)
    return (mapping, ref, uvs, indices)


def triangulate_with_uv(poly_indices, uv_per_corner) -> tuple[np.ndarray, np.ndarray]:
    faces = []
    face_uvs = []
    cur = []
    cur_uv = []
    corner = 0
    for vertex_index in poly_indices:
        end = vertex_index < 0
        vi = -vertex_index - 1 if end else vertex_index
        cur.append(vi)
        if uv_per_corner is not None:
            cur_uv.append(uv_per_corner[corner])
        corner += 1
        if end:
            v0 = cur[0]
            uv0 = cur_uv[0] if cur_uv else None
            for j in range(len(cur) - 2):
                faces.append([v0, cur[j + 1], cur[j + 2]])
                if uv_per_corner is not None:
                    face_uvs.append([uv0, cur_uv[j + 1], cur_uv[j + 2]])
            cur = []
            cur_uv = []
    faces_arr = np.asarray(faces, dtype=np.int64)
    if uv_per_corner is None:
        return faces_arr, None
    return faces_arr, np.asarray(face_uvs, dtype=np.float64)


def fbx_to_trimesh(path: str) -> trimesh.Trimesh:
    from fbxloader import FBXLoader
    from fbxloader.utils import get_transform, EULER_ORDERS
    from fbxloader.nodes import Mesh, Object3D, Scene

    with open(path, "rb") as f:
        data = f.read()
    tree = parse_binary_fbx_keep_layers(data)
    loader = FBXLoader(path)

    geos = tree["Objects"]["Geometry"]
    parts = []
    for node_id, geo in geos.items():
        if "Vertices" not in geo or "PolygonVertexIndex" not in geo:
            continue
        verts = np.asarray(geo["Vertices"]["a"], dtype=np.float64).reshape(-1, 3)
        poly = np.asarray(geo["PolygonVertexIndex"]["a"], dtype=np.int64)
        mapping, ref, uv_values, uv_index = _layer_uv(geo)
        n_corners = len(poly)
        uv_corners = None
        if uv_values is not None:
            if ref in (None, "IndexToDirect") and uv_index is not None:
                uv_corners = uv_values[uv_index]
            elif ref == "Direct" or uv_index is None:
                if len(uv_values) == n_corners:
                    uv_corners = uv_values
                elif len(uv_values) == len(verts):
                    uv_corners = None  # by-vertex; fill during triangulation
            if mapping == "ByVertex" or mapping == "ByVertice":
                uv_corners = None

        faces, face_uvs = triangulate_with_uv(
            poly,
            uv_corners if mapping != "ByVertex" and mapping != "ByVertice" else None,
        )
        if face_uvs is None and uv_values is not None and len(uv_values) == len(verts):
            face_uvs = uv_values[faces]

        # world matrix from the already-built fbxloader graph
        mesh_obj = loader.objects.get(node_id)
        if mesh_obj is None:
            continue
        verts_h = np.hstack([verts, np.ones((len(verts), 1))]).T
        verts_w = (mesh_obj.matrixWorld @ verts_h)[:3].T

        if face_uvs is None:
            tm = trimesh.Trimesh(vertices=verts_w, faces=faces, process=False)
        else:
            # split vertices so each corner can keep its UV
            new_v = verts_w[faces].reshape(-1, 3)
            new_uv = face_uvs.reshape(-1, 2)
            new_f = np.arange(len(new_v)).reshape(-1, 3)
            tm = trimesh.Trimesh(vertices=new_v, faces=new_f, process=False)
            tm.visual.uv = new_uv
        parts.append(tm)

    if not parts:
        raise RuntimeError("No FBX geometry converted")
    vertices = []
    faces = []
    uvs = []
    offset = 0
    for part in parts:
        vertices.append(part.vertices)
        faces.append(np.asarray(part.faces) + offset)
        uv = getattr(part.visual, "uv", None)
        if uv is None or len(uv) != len(part.vertices):
            raise RuntimeError("A mesh part is missing per-vertex UVs")
        uvs.append(np.asarray(uv, dtype=np.float64))
        offset += len(part.vertices)
    mesh = trimesh.Trimesh(
        vertices=np.vstack(vertices),
        faces=np.vstack(faces),
        process=False,
    )
    mesh.visual.uv = np.vstack(uvs)
    return mesh


def attach_windsock_pbr(mesh: trimesh.Trimesh, folder) -> trimesh.Trimesh:
    from pathlib import Path

    folder = Path(folder)
    albedo = Image.open(folder / "win_windsock_Albedo.png").convert("RGB")
    armw = Image.open(folder / "win_windsock_ARMW.png").convert("RGBA")
    normal = Image.open(folder / "win_windsock_Normal.png").convert("RGB")
    emissive = Image.open(folder / "win_windsock_Emission.png").convert("RGB")
    r, g, b, a = armw.split()
    mr = Image.merge("RGB", (Image.new("L", armw.size, 255), g, b))
    mesh.visual.material = PBRMaterial(
        name="windsock",
        baseColorTexture=albedo,
        metallicRoughnessTexture=mr,
        normalTexture=normal,
        occlusionTexture=r,
        emissiveTexture=emissive,
        doubleSided=True,
    )
    return mesh
