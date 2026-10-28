"""Exact preservation of selected triangles while reducing the remaining mesh."""
from dataclasses import replace
from dataclasses import asdict
import numpy as np
import trimesh


def selected_faces(mesh, request):
    keep=np.zeros(len(mesh.faces),dtype=bool)
    if request.protected_faces.strip():
        try:ids=np.array([int(v) for v in request.protected_faces.split(',')])
        except ValueError as exc:raise ValueError('Protected face IDs must be comma-separated integers.') from exc
        if (ids<0).any() or (ids>=len(keep)).any():raise ValueError('Protected face index is outside this working mesh.')
        keep[ids]=True
    if request.protected_box.strip():
        try:box=np.array([float(v) for v in request.protected_box.split(',')]).reshape(2,3)
        except ValueError as exc:raise ValueError('Region box needs xmin,ymin,zmin,xmax,ymax,zmax.') from exc
        if not np.isfinite(box).all() or (box[0]>=box[1]).any():raise ValueError('Region box must have finite increasing bounds.')
        triangles=mesh.triangles
        keep |= ((triangles.max(1)>=box[0]) & (triangles.min(1)<=box[1])).all(1)
    if request.sharp_angle>0:
        adjacent=mesh.face_adjacency[mesh.face_adjacency_angles>=np.deg2rad(request.sharp_angle)]
        keep[adjacent.ravel()]=True
    if (request.protected_box.strip() or request.protected_faces.strip() or request.sharp_angle>0) and not keep.any():
        raise ValueError('Protection selected no triangles; inspect the working mesh coordinates/IDs.')
    return keep


def protected_optimize(source, request, checkpoint):
    from .optimization import optimize_mesh, assert_material_preserved, bounds_change_percent, surface_error_metrics
    from scripts.export_contracts import mesh_status
    keep=selected_faces(source,request)
    count=int(keep.sum())
    if count==len(keep) or request.target<=count:
        raise ValueError(f'{count} protected faces leave no reduction budget. Increase the target or reduce the protected region.')
    fixed=source.submesh([np.flatnonzero(keep)],append=True,repair=False)
    rest=source.submesh([np.flatnonzero(~keep)],append=True,repair=False)
    # Boundary constraints include the seam between protected and reduced geometry.
    reduced,detail=optimize_mesh(rest,replace(request,target=request.target-count,preserve_boundary=True,
        protected_box='',protected_faces='',sharp_angle=0),checkpoint)
    vertices=np.vstack((fixed.vertices,reduced.vertices));faces=np.vstack((fixed.faces,reduced.faces+len(fixed.vertices)))
    result=trimesh.Trimesh(vertices=vertices,faces=faces,process=False)
    uv_a,uv_b=getattr(fixed.visual,'uv',None),getattr(reduced.visual,'uv',None)
    if getattr(source.visual,'uv',None) is not None and (uv_a is None or uv_b is None or detail.get('uv_fallback')):
        raise ValueError('Protected reduction requires intact UVs in both regions; repair/rebake UVs before reducing this mesh.')
    if uv_a is not None and uv_b is not None:
        result.visual=trimesh.visual.TextureVisuals(uv=np.vstack((uv_a,uv_b)),material=source.visual.material.copy())
    elif getattr(source.visual,'material',None) is not None:
        result.visual=trimesh.visual.TextureVisuals(material=source.visual.material.copy())
    assert_material_preserved(source,result)
    shift=bounds_change_percent(source,result);error=surface_error_metrics(source,result)
    if shift>request.max_bounds_change or error['max_percent']>request.max_surface_error:
        raise ValueError('Protected reduction failed the whole-mesh geometry guards; no preview published.')
    if request.strict_budget and len(result.faces)>request.target:raise ValueError('Protected reduction could not meet the strict budget.')
    # Compare triangle coordinates directly, including order and winding.
    if not np.array_equal(result.triangles[:count],source.triangles[keep]):raise ValueError('Protected triangle coordinates changed.')
    detail.update(settings=asdict(request),source=mesh_status(source),result=mesh_status(result),target_met=len(result.faces)<=request.target,
        target_error_faces=max(0,len(result.faces)-request.target),bounds_change_percent=shift,surface_error=error,
        reduction_percent=100*(1-len(result.faces)/len(source.faces)),
        protected_faces=count,protected_geometry_exact=True,
        limitation='Protection applies to this mesh only. Boundaries remain split; later remeshing/painting or LOD export does not inherit these constraints.')
    return result,detail
