"""Bounded, explicit UV raster sampling and material diagnostics. Never edits meshes."""
import numpy as np
from PIL import Image, ImageDraw
from .materials import _extract_textures


def cleanup_settings(settings):
    from .schema import checked_number
    strict=settings.get("c_guard_strict",False)
    if not isinstance(strict,bool):raise ValueError("Cleanup strict mode must be a boolean.")
    return (checked_number(settings.get("c_guard_bounds",5),0,100,"Cleanup bounds limit"),
            checked_number(settings.get("c_guard_surface",2),0,100,"Cleanup surface limit"),strict)


def diagnose(mesh,resolution=256,face_limit=200000,raster_budget=20000000):
    if resolution not in (128,256,512):raise ValueError("Diagnostic resolution must be 128, 256 or 512.")
    maps=_extract_textures(mesh)
    report={"maps":{},"warnings":[],"uv":None,"units":"Texel density is per mesh unit; apply measured scale for pixels/metre."}
    for name,image in maps.items():
        small=image.copy();small.thumbnail((128,128));rgb=np.asarray(small.convert("RGB"),dtype=float)/255
        report["maps"][name]={"size":list(image.size),"mode":image.mode,"channel_min":rgb.min((0,1)).tolist(),"channel_max":rgb.max((0,1)).tolist()}
        if name=="normal":
            lengths=np.linalg.norm(rgb*2-1,axis=2)
            report["maps"][name]["nonunit_fraction"]=float((np.abs(lengths-1)>.2).mean())
            if (np.abs(lengths-1)>.2).mean()>.1:report["warnings"].append("Normal map has many non-unit decoded vectors; check encoding and map type.")
    for name in ("albedo","metallic_roughness"):
        if name not in maps:report["warnings"].append(f"Missing {name} image; material factors may still be intentional.")
    uv=getattr(mesh.visual,"uv",None)
    if uv is None or len(uv)!=len(mesh.vertices) or not np.isfinite(uv).all():
        report["warnings"].append("Missing or invalid UVs.");return report,(None,None,None)
    if not len(mesh.faces):
        report["warnings"].append("Mesh has no faces.");return report,(None,None,None)
    if face_limit<1 or raster_budget<1:raise ValueError("Diagnostic sampling budgets must be positive.")
    uv=np.asarray(uv);indices=np.linspace(0,len(mesh.faces)-1,min(face_limit,len(mesh.faces)),dtype=int)
    faces=np.asarray(mesh.faces)[indices];tri=uv[faces];xyz=np.asarray(mesh.vertices)[faces]
    e1,e2=xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]
    area3=np.linalg.norm(np.cross(e1,e2),axis=1)/2
    a,b=tri[:,1]-tri[:,0],tri[:,2]-tri[:,0];det=a[:,0]*b[:,1]-a[:,1]*b[:,0];area2=np.abs(det)/2
    valid=(area3>1e-14)&(area2>1e-14)
    length=np.maximum(np.linalg.norm(e1,axis=1),1e-14);proj=np.sum(e1*e2,axis=1)/length
    height=np.sqrt(np.maximum(np.sum(e2*e2,axis=1)-proj**2,1e-28))
    jac=np.empty((len(faces),2,2));jac[:,:,0]=a/length[:,None];jac[:,:,1]=(b-a*(proj/length)[:,None])/height[:,None]
    singular=np.linalg.svd(jac,compute_uv=False);stretch=singular[:,0]/np.maximum(singular[:,1],1e-14)
    atlas=maps.get("albedo",next(iter(maps.values()),None));pixels=atlas.width if atlas else 1
    density=np.sqrt(area2/np.maximum(area3,1e-14))*pixels
    occupancy=np.zeros((resolution,resolution),dtype=np.uint32)
    stretch_image=Image.new("RGB",(resolution,resolution),"#122333");sd=ImageDraw.Draw(stretch_image)
    density_image=stretch_image.copy();dd=ImageDraw.Draw(density_image)
    median=float(np.median(density[valid])) if valid.any() else 1
    raster_work=0;raster_faces=0;raster_limited=False
    for t,d,ratio,is_valid in zip(tri,density,stretch,valid):
        if not is_valid:continue
        lo=np.maximum(0,np.floor(t.min(0)*resolution).astype(int));hi=np.minimum(resolution-1,np.ceil(t.max(0)*resolution).astype(int))
        if np.any(hi<lo):continue
        work=int(np.prod(hi-lo+1))
        if raster_work+work>raster_budget:
            raster_limited=True;break
        raster_work+=work;raster_faces+=1
        xs=(np.arange(lo[0],hi[0]+1)+.5)/resolution;ys=(np.arange(lo[1],hi[1]+1)+.5)/resolution
        x,y=np.meshgrid(xs,ys);v0,v1=t[1]-t[0],t[2]-t[0];den=v0[0]*v1[1]-v0[1]*v1[0]
        u=((x-t[0,0])*v1[1]-(y-t[0,1])*v1[0])/den
        v=(v0[0]*(y-t[0,1])-v0[1]*(x-t[0,0]))/den
        inside=(u>1e-8)&(v>1e-8)&(u+v<1-1e-8) # exclude shared-edge pixels
        occupancy[lo[1]:hi[1]+1,lo[0]:hi[0]+1]+=inside
        polygon=[(float(p[0]*resolution),float((1-p[1])*resolution)) for p in t]
        heat=min(1,max(0,np.log2(max(ratio,1))/4));sd.polygon(polygon,fill=(int(60+195*heat),int(205*(1-heat)),100))
        rel=np.clip(np.log2(max(d,1e-12)/max(median,1e-12)),-2,2)/2
        dd.polygon(polygon,fill=(int(70+185*max(rel,0)),int(200*(1-abs(rel))),int(70+185*max(-rel,0))))
    overlap=np.zeros((resolution,resolution,3),dtype=np.uint8);overlap[:]=[18,35,51]
    overlap[occupancy>0]=[71,205,175];overlap[occupancy>1]=[245,90,105]
    covered=int((occupancy>0).sum());shared=int((occupancy>1).sum())
    report["uv"]={"total_faces":len(mesh.faces),"tested_faces":len(faces),"sampled":len(faces)<len(mesh.faces),
        "raster_resolution":resolution,"raster_tested_faces":raster_faces,"raster_budget_limited":raster_limited,
        "coverage_fraction":covered/resolution**2,"overlap_pixels":shared,
        "overlap_of_covered_fraction":shared/max(1,covered),"outside_vertices":int(np.any((uv<0)|(uv>1),axis=1).sum()),
        "degenerate_tested_faces":int((~valid).sum()),"negative_uv_orientation_fraction":float((det<0).mean()),
        "stretch_anisotropy_median":float(np.median(stretch[valid])) if valid.any() else None,
        "stretch_anisotropy_p95":float(np.percentile(stretch[valid],95)) if valid.any() else None,
        "texels_per_mesh_unit_median":float(np.median(density[valid])) if valid.any() else None,
        "limitations":"Raster interior samples; subpixel/edge overlap can be missed. Large meshes use a deterministic face sample. Mirrored overlap may be intentional; orientation alone cannot identify intent."}
    if shared:report["warnings"].append("UV overlap detected at sampled texels; review whether mirrored/stacked islands are intentional.")
    if raster_limited:report["warnings"].append("Raster work budget reached; overlap and heatmaps cover only the reported tested faces.")
    if report["uv"]["outside_vertices"]:report["warnings"].append("UVs extend outside 0–1; check intended tiling/UDIM use before BMS export.")
    return report,(Image.fromarray(np.flipud(overlap)),stretch_image,density_image)
