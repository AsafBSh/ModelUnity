"""xatlas unwrap plus bounded CPU closest-surface PBR transfer on a working copy."""
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
import trimesh
from .materials import _extract_textures


def sample_image(image,uv):
    pixels=np.asarray(image.convert('RGBA'),dtype=float)/255
    uv=np.where((uv<0)|(uv>1),np.mod(uv,1),uv)
    xy=uv*[image.width-1,-(image.height-1)]+[0,image.height-1]
    lo=np.floor(xy).astype(int);hi=np.minimum(lo+1,[image.width-1,image.height-1]);w=xy-lo
    return ((pixels[lo[:,1],lo[:,0]]*(1-w[:,0,None])+pixels[lo[:,1],hi[:,0]]*w[:,0,None])*(1-w[:,1,None])+
            (pixels[hi[:,1],lo[:,0]]*(1-w[:,0,None])+pixels[hi[:,1],hi[:,0]]*w[:,0,None])*w[:,1,None])


def basis(mesh,face_ids,bary):
    tri=mesh.triangles[face_ids];uv=np.asarray(mesh.visual.uv)[mesh.faces[face_ids]]
    normal=np.sum(mesh.vertex_normals[mesh.faces[face_ids]]*bary[...,None],axis=1)
    normal/=np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-12)
    e1,e2=tri[:,1]-tri[:,0],tri[:,2]-tri[:,0];d1,d2=uv[:,1]-uv[:,0],uv[:,2]-uv[:,0]
    det=d1[:,0]*d2[:,1]-d1[:,1]*d2[:,0]
    if np.any(np.abs(det)<1e-12):raise ValueError('Degenerate UV triangle prevents reliable tangent-space transfer.')
    tangent=(e1*d2[:,1,None]-e2*d1[:,1,None])/det[:,None]
    bitangent=(-e1*d2[:,0,None]+e2*d1[:,0,None])/det[:,None]
    tangent-=normal*np.sum(tangent*normal,axis=1,keepdims=True)
    tangent/=np.maximum(np.linalg.norm(tangent,axis=1,keepdims=True),1e-12)
    sign=np.where(np.sum(np.cross(normal,tangent)*bitangent,axis=1)<0,-1,1)
    return tangent,np.cross(normal,tangent)*sign[:,None],normal


def rebake(target,source,resolution=1024,padding=4,max_distance=2.,checkpoint=lambda *_:None):
    import xatlas
    if resolution not in (256,512,1024,2048):raise ValueError('CPU rebake resolution must be 256–2048.')
    if not isinstance(padding,int) or not 1<=padding<=32:raise ValueError('Atlas padding must be 1–32 pixels.')
    if not np.isfinite(max_distance) or not 0<=max_distance<=25:raise ValueError('Projection distance must be 0–25% of source diagonal.')
    if not len(target.faces) or len(target.faces)>200000:raise ValueError('CPU unwrap supports 1–200,000 target faces.')
    if len(source.faces)>1000000:raise ValueError('CPU projection supports at most 1,000,000 source faces.')
    uv=getattr(source.visual,'uv',None)
    if uv is None or not np.isfinite(uv).all() or len(uv)!=len(source.vertices):raise ValueError('High/source mesh needs valid UVs for texture transfer.')
    maps=_extract_textures(source)
    if not maps:raise ValueError('Source mesh has no texture maps to transfer.')
    checkpoint('Creating xatlas charts and packing UVs',.12)
    atlas=xatlas.Atlas();atlas.add_mesh(np.asarray(target.vertices,dtype=np.float32),np.asarray(target.faces,dtype=np.uint32))
    packing=xatlas.PackOptions();packing.resolution=resolution;packing.padding=padding
    atlas.generate(pack_options=packing)
    mapping,faces,new_uv=atlas[0]
    result=trimesh.Trimesh(vertices=target.vertices[mapping],faces=faces,vertex_normals=target.vertex_normals[mapping],process=False)
    mat=source.visual.material.copy()
    if not isinstance(mat,trimesh.visual.material.PBRMaterial):mat=mat.to_pbr()
    result.visual=trimesh.visual.TextureVisuals(uv=new_uv,material=mat)
    coverage=np.zeros((resolution,resolution),bool)
    output={key:np.zeros((resolution,resolution,4),dtype=np.uint8) for key in maps}
    output.setdefault('normal',np.zeros((resolution,resolution,4),dtype=np.uint8))
    diag=float(np.linalg.norm(np.ptp(source.bounds,axis=0)))
    if diag<=0:raise ValueError('Source mesh has zero-size bounds.')
    largest=0.;work=0
    for index,face in enumerate(result.faces):
        if index%256==0:checkpoint('Projecting high/source textures onto packed atlas',.2+.65*index/len(result.faces))
        tri=np.asarray(new_uv)[face]*[resolution,-resolution]+[0,resolution]
        lo=np.maximum(np.floor(tri.min(0)).astype(int),0);hi=np.minimum(np.ceil(tri.max(0)).astype(int),resolution-1)
        if (hi<lo).any():continue
        work+=int(np.prod(hi-lo+1))
        if work>40000000:raise ValueError('CPU raster work exceeds 40 million samples; lower atlas resolution or split the asset.')
        yy,xx=np.mgrid[lo[1]:hi[1]+1,lo[0]:hi[0]+1];xy=np.c_[xx.ravel()+.5,yy.ravel()+.5]
        bary=trimesh.triangles.points_to_barycentric(np.tile(np.c_[tri,np.zeros(3)],(len(xy),1,1)),np.c_[xy,np.zeros(len(xy))])
        valid=np.isfinite(bary).all(1)&(bary>=-1e-7).all(1)
        xy=np.c_[xx.ravel(),yy.ravel()][valid];bary=bary[valid]
        if not len(xy):continue
        for begin in range(0,len(xy),2048):
            pixels=xy[begin:begin+2048];weights=bary[begin:begin+2048]
            points=weights@result.triangles[index]
            projected,distance,source_faces=trimesh.proximity.closest_point(source,points)
            deviation=float(distance.max()/diag*100);largest=max(largest,deviation)
            if deviation>max_distance:raise ValueError(f'Source projection deviation {deviation:.3f}% exceeds {max_distance}% guard. Align the meshes before rebaking.')
            source_bary=trimesh.triangles.points_to_barycentric(source.triangles[source_faces],projected)
            source_uv=np.sum(np.asarray(uv)[source.faces[source_faces]]*source_bary[...,None],axis=1)
            for key,image in maps.items():
                if key!='normal':output[key][pixels[:,1],pixels[:,0]]=np.rint(sample_image(image,source_uv)*255).astype('uint8')
            st,sb,sn=basis(source,source_faces,source_bary)
            world=sn
            if 'normal' in maps:
                n=sample_image(maps['normal'],source_uv)[:,:3]*2-1
                world=st*n[:,0,None]+sb*n[:,1,None]+sn*n[:,2,None]
            tt,tb,tn=basis(result,np.full(len(weights),index),weights)
            n=np.c_[np.sum(world*tt,axis=1),np.sum(world*tb,axis=1),np.sum(world*tn,axis=1)]
            n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-12)
            output['normal'][pixels[:,1],pixels[:,0]]=np.c_[np.rint(np.clip(n*.5+.5,0,1)*255).astype('uint8'),np.full(len(n),255,dtype='uint8')]
            coverage[pixels[:,1],pixels[:,0]]=True
    if not coverage.any():raise ValueError('The packed UVs have no covered pixels.')
    distance,nearest=distance_transform_edt(~coverage,return_indices=True)
    fill=(~coverage)&(distance<=padding)
    properties={'albedo':'baseColorTexture','metallic_roughness':'metallicRoughnessTexture','normal':'normalTexture','occlusion':'occlusionTexture','emissive':'emissiveTexture'}
    for key,pixels in output.items():
        pixels[fill]=pixels[nearest[0][fill],nearest[1][fill]]
        setattr(mat,properties[key],Image.fromarray(pixels))
    report={'algorithm':'xatlas + CPU closest-surface PBR transfer','resolution':resolution,'padding':padding,
            'xatlas_dimensions':[atlas.width,atlas.height],'coverage_fraction':float(coverage.mean()),
            'max_projection_error_percent':largest,'maps':list(output),'source_triangles':len(source.faces),'target_triangles':len(result.faces),
            'warnings':['Tangent normals use per-triangle derivatives and interpolated normals, not certified MikkTSpace. Inspect seams in the target renderer.',
                        'Reparameterizes UV charts; does not repair holes or recover missing texture detail. CPU projection can transfer across nearby surfaces; inspect thin parts.']}
    return result,report
