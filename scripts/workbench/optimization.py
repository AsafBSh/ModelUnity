"""Bounded CPU reduction with explicit budget and attribute-preservation contracts."""
from dataclasses import asdict
from importlib.metadata import version
import numpy as np
import trimesh

from scripts.export_contracts import mesh_status
from .schema import OptimizationRequest


def bounds_change_percent(source, result):
    """Maximum AABB corner displacement / source diagonal; not silhouette error."""
    diagonal = float(np.linalg.norm(np.ptp(source.bounds, axis=0)))
    if diagonal <= 0:
        raise ValueError("Mesh bounds have zero extent.")
    return float(100 * np.linalg.norm(result.bounds-source.bounds, axis=1).max() / diagonal)


def assert_material_preserved(source, result):
    """Check decoded map pixels and PBR factors, including after GLB serialization."""
    old = getattr(source.visual, "material", None)
    new = getattr(result.visual, "material", None)
    if old is None:
        return
    for key in ("baseColorTexture", "metallicRoughnessTexture", "normalTexture",
                "occlusionTexture", "emissiveTexture", "image"):
        expected = getattr(old, key, None)
        if expected is not None:
            actual = getattr(new, key, None)
            if actual is None or not np.array_equal(np.asarray(expected), np.asarray(actual)):
                raise ValueError(f"Optimization lost or changed {key} pixels.")
    for key in ("baseColorFactor", "metallicFactor", "roughnessFactor", "emissiveFactor",
                "alphaMode", "alphaCutoff", "doubleSided"):
        expected, actual = getattr(old, key, None), getattr(new, key, None)
        if expected is not None:
            if actual is None:
                raise ValueError(f"Optimization lost material parameter {key}.")
            if isinstance(expected, str):
                same = expected == actual
            else:
                same = np.allclose(np.asarray(expected), np.asarray(actual), atol=1e-6)
            if not same:
                raise ValueError(f"Optimization changed material parameter {key}.")


def surface_error_metrics(source, result, samples=512):
    """Deterministic bidirectional point-to-triangle distances, not full Hausdorff."""
    def points(mesh):
        areas = np.asarray(mesh.area_faces)
        if not np.isfinite(areas).all() or areas.sum() <= 0:
            raise ValueError("Surface comparison requires nonzero finite triangle area.")
        indices = np.searchsorted(np.cumsum(areas),(np.arange(samples)+.5)*areas.sum()/samples)
        vertices = mesh.vertices[np.linspace(0,len(mesh.vertices)-1,min(samples,len(mesh.vertices)),dtype=int)]
        return np.vstack((mesh.triangles_center[np.minimum(indices,len(mesh.faces)-1)],vertices))
    method = "deterministic sampled point-to-triangle (rtree)"
    def distance(mesh, query):
        nonlocal method
        try:
            return trimesh.proximity.closest_point(mesh,query)[1]
        except ModuleNotFoundError:
            if len(mesh.faces)>100000:
                raise ModuleNotFoundError("Large-mesh surface comparison needs rtree; refusing an unbounded brute-force query.")
            # Exact query distances without an optional spatial index; small
            # chunks bound the brute-force temporary arrays.
            method = "deterministic sampled point-to-triangle (chunked naive)"
            return np.concatenate([trimesh.proximity.closest_point_naive(mesh,query[i:i+16])[1]
                                   for i in range(0,len(query),16)])
    source_points, result_points = points(source),points(result)
    distances = np.concatenate((distance(result,source_points),distance(source,result_points)))
    if not np.isfinite(distances).all():
        raise ValueError("Surface comparison returned nonfinite distances.")
    diagonal = float(np.linalg.norm(np.ptp(source.bounds,axis=0)))
    if diagonal <= 0:
        raise ValueError("Surface comparison requires nonzero mesh bounds.")
    return {"max_percent":float(100*distances.max()/diagonal),
            "rms_percent":float(100*np.sqrt(np.mean(distances**2))/diagonal),
            "source_samples":len(source_points),"result_samples":len(result_points),"method":method,
            "limitation":"Sampled distances, not full Hausdorff distance or proof of all silhouette/UV/thin-part preservation"}


def _repair(mesh):
    before = np.asarray(mesh.faces).copy()
    if not mesh.is_winding_consistent:
        trimesh.repair.fix_winding(mesh)
    return int(np.any(np.asarray(mesh.faces) != before, axis=1).sum())


def optimize_mesh(source, request: OptimizationRequest, checkpoint=lambda *_: None):
    from scripts.lod_export import _decimate_keep_uv, _extract_textures, _flat_colour_visual, average_albedo_rgba

    if not len(source.faces) or not np.isfinite(source.vertices).all():
        raise ValueError("Optimization needs finite, nonempty geometry.")
    status = mesh_status(source)
    if getattr(source.visual, "uv", None) is not None and not status["uv_valid"]:
        raise ValueError("Invalid UV coordinates; repair them explicitly before optimizing.")
    if not status["uv_valid"] and status["textures"]:
        raise ValueError("Textured geometry requires valid UVs before optimization.")
    if request.protected_box.strip() or request.protected_faces.strip() or request.sharp_angle>0:
        from .protection import protected_optimize
        return protected_optimize(source,request,checkpoint)
    mesh = source.copy()
    mesh.metadata.pop("modelunify_decimation_passes", None)
    mesh.metadata.pop("modelunify_uv_method", None)
    # No separate weld, hole-fill or island-removal cleanup; keep the master intact.
    repaired_before = _repair(mesh) if request.repair_winding else 0
    checkpoint("Reducing mesh with unchanged safety constraints", .2)
    if len(mesh.faces) > request.target:
        if status["uv_valid"]:
            mesh = _decimate_keep_uv(mesh, request.target, max_passes=request.max_passes,
                                     preserve_boundary=request.preserve_boundary)
        else:
            import pymeshlab
            ms = pymeshlab.MeshSet()
            ms.add_mesh(pymeshlab.Mesh(vertex_matrix=mesh.vertices, face_matrix=mesh.faces))
            passes = []
            previous = len(mesh.faces)
            for index in range(request.max_passes):
                checkpoint(f"Geometry reduction pass {index+1}", .25 + .1*index)
                ms.meshing_decimation_quadric_edge_collapse(targetfacenum=request.target,
                    qualitythr=.3, preservetopology=True, preservenormal=True,
                    preserveboundary=request.preserve_boundary, boundaryweight=1.,
                    planarquadric=True, optimalplacement=True, autoclean=True)
                achieved = int(ms.current_mesh().face_number())
                passes.append({"pass":index+1,"before_faces":previous,"achieved_faces":achieved})
                if achieved <= request.target or achieved >= previous:
                    break
                previous = achieved
            native = ms.current_mesh()
            mesh = trimesh.Trimesh(vertices=native.vertex_matrix(), faces=native.face_matrix(), process=False)
            if getattr(source.visual, "material", None) is not None:
                mesh.visual = trimesh.visual.TextureVisuals(material=source.visual.material.copy())
            elif source.visual.defined:
                raise ValueError("Vertex-colour transfer is not supported by geometry optimization; master preserved.")
            mesh.metadata["modelunify_decimation_passes"] = passes
    checkpoint("Checking winding, UVs and material preservation", .65)
    repaired_after = _repair(mesh) if request.repair_winding else 0
    if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise ValueError("Decimator produced empty or nonfinite geometry.")
    result = mesh_status(mesh)
    if len(mesh.faces) > len(source.faces):
        raise ValueError("Decimator increased the triangle count.")
    method = mesh.metadata.get("modelunify_uv_method", "unchanged" if status["uv_valid"] else "pymeshlab geometry")
    fallback = None
    if status["uv_valid"] and (not result["uv_valid"] or "fallback" in method.lower()):
        fallback = method if result["uv_valid"] else "flat average albedo"
        if not request.allow_uv_fallback:
            raise ValueError(f"UV preservation failed ({fallback}); no preview published. Enable UV fallback explicitly to inspect a degraded copy.")
        if not result["uv_valid"]:
            _flat_colour_visual(mesh, average_albedo_rgba(_extract_textures(source).get("albedo")), "optimized_flat")
    if not fallback:
        assert_material_preserved(source, mesh)
    shift = bounds_change_percent(source, mesh)
    if shift > request.max_bounds_change + 1e-5:
        raise ValueError(f"Bounds change {shift:.3f}% exceeds {request.max_bounds_change:g}% limit; no preview published.")
    target_met = len(mesh.faces) <= request.target
    if request.strict_budget and not target_met:
        raise ValueError(f"Strict triangle budget not reached: {len(mesh.faces):,} achieved / {request.target:,} requested. Constraints were retained; no preview published.")
    if request.repair_winding and not mesh.is_winding_consistent:
        raise ValueError("Winding remains inconsistent after repair; no preview published.")
    checkpoint("Measuring bidirectional sampled surface deviation", .75)
    surface_error = surface_error_metrics(source,mesh)
    if surface_error["max_percent"] > request.max_surface_error + 1e-5:
        raise ValueError(f"Sampled surface error {surface_error['max_percent']:.3f}% exceeds {request.max_surface_error:g}% limit; no preview published. Use a larger triangle budget or explicitly change the surface limit for a draft.")
    warnings = []
    if not target_met:
        warnings.append(f"Optimization: {len(mesh.faces)} achieved / {request.target} requested; target not reached with the retained constraints.")
    if fallback:
        warnings.append(f"Optimization UV fallback: {fallback}; inspect texture seams before accepting.")
    if status["nonmanifold_edges"]:
        warnings.append(f"Input has {status['nonmanifold_edges']} indexed non-manifold edges; winding repair does not repair non-manifold topology.")
    if not result["winding_consistent"]:
        warnings.append("Optimized winding is inconsistent; repair was disabled.")
    if surface_error["max_percent"] > 2:
        warnings.append(f"Sampled surface deviation {surface_error['max_percent']:.3f}% exceeds the default 2% limit; the requested relaxed limit permits this draft.")
    report = {"algorithm":"bounded-quadric-v2", "packages":{key:version(key) for key in ("pymeshlab","trimesh","numpy")},
        "settings":asdict(request), "source":status, "result":mesh_status(mesh),
        "target_met":target_met,"target_error_faces":max(0,len(mesh.faces)-request.target),
        "reduction_percent":100*(1-len(mesh.faces)/len(source.faces)),
        "bounds_change_percent":shift,"bounds_metric":"AABB corner displacement / source diagonal; not a silhouette or thin-part guarantee",
        "surface_error":surface_error,
        "winding_faces_reoriented_before":repaired_before,"winding_faces_reoriented_after":repaired_after,
        "passes":mesh.metadata.get("modelunify_decimation_passes",[]),"uv_method":method,
        "uv_fallback":fallback,"warnings":warnings}
    return mesh, report
