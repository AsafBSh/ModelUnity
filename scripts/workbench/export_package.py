"""General OBJ/PBR interchange and source-backed static BMS sidecar handoff.

No global theater DAT authoring, BML generation, DDS encoding or installation.
"""
import json
import re
import zipfile
from pathlib import Path
import numpy as np
from PIL import Image
from .materials import _extract_textures
from scripts.export_contracts import load_static_master, mesh_status


NEXT_STEPS = '''BMS handoff — static geometry only

1. Review dimensions, axes and pivot. General OBJ geometry retains input units.
   bms_handoff/geometry, when requested, uses the selected BMS XYZ mapping and FEET.
   Parent.dat describes exactly those staged coordinates. Avoid a second unit or
   axis conversion in your DCC exporter; verify its actual BML vertex bounds.
2. Import each LOD independently in Blender/3ds Max with a compatible BMS exporter.
   Keep the single material slot and the names listed in each Model_n.mti.
   Export one matching Model_n.bml. This application has not created these BMLs.
3. Convert the supplied *_ALB.png, *_ARMW.png and *_NOR.png to the referenced DDS
   filenames. ALB uses sRGB; ARMW and normal are linear data. ARMW channels are
   R=AO, G=roughness, B=metallic, A=wetness. Preserve alpha. Select DDS compression
   compatible with the target shader/toolchain; BML v2 does not itself require BC7.
4. Reconcile exporter-written material slots/names with Materials.mtl and MTI.
   MTI is a skin-major list of S × M names, including repetitions; this handoff
   authors ONE skin / ONE material per LOD. Materials.mtl is BMS JSON; Wavefront
   OBJ .mtl files are a separate format and must never replace that library.
5. Validate BML + MTI + Materials.mtl + DDS + Parent.dat together in BML Workbench
   and BMS Editor: bounds, normals, PBR channel slots, every LOD/skin and lighting.
   Vertex layout/tangents must match the PBR shader. Check in-game afterward.
6. Reserve an unused object/parent ID in your target theater and author the
   appropriate database registration with the BMS tools. Global DAT/CT/feature
   records depend on object type and theater; they cannot be guessed from a mesh.
   Work on a test copy and retain backups before deploying anything.

Animated aircraft/turrets, DOFs, switches, slots, glass and emissive effects need
separate authoring. The zero control counts here describe a STATIC model only.
Generated sidecars are not proof of a BMS-ready or installed asset.
'''


def _name(value):
    result=re.sub(r'[^A-Za-z0-9_-]+','_',str(value)).strip('_')[:60]
    return result or 'asset'


def base_color_factor(material):
    value=getattr(material,'baseColorFactor',None)
    if value is None:return np.ones(4)
    array=np.asarray(value)
    # Trimesh stores colour factors as uint8, including very dark 0/1 values.
    return array.astype(float)/255 if array.dtype.kind in 'ui' or array.max()>1 else array.astype(float)


def write_obj(mesh,path,material_name):
    """One explicit Wavefront material per OBJ; no BMS JSON masquerading as OBJ MTL."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    maps=_extract_textures(mesh);mat=getattr(mesh.visual,'material',None)
    factor=base_color_factor(mat)
    uv=getattr(mesh.visual,'uv',None);normals=mesh.vertex_normals
    lines=[f'mtllib {path.stem}.mtl\n',f'o {path.stem}\n']
    lines.extend('v '+' '.join(f'{v:.9g}' for v in row)+'\n' for row in mesh.vertices)
    lines.extend('vn '+' '.join(f'{v:.9g}' for v in row)+'\n' for row in normals)
    if uv is not None:lines.extend('vt '+' '.join(f'{v:.9g}' for v in row)+'\n' for row in uv)
    lines.append(f'usemtl {material_name}\n')
    for face in mesh.faces:
        lines.append('f '+' '.join(f'{i+1}/{i+1}/{i+1}' if uv is not None else f'{i+1}//{i+1}' for i in face)+'\n')
    path.write_text(''.join(lines),encoding='utf-8')
    material=[f'newmtl {material_name}', 'Kd '+' '.join(f'{v:.6g}' for v in factor[:3]),f'd {factor[3]:.6g}',
              f'Pm {getattr(mat,"metallicFactor",1) if getattr(mat,"metallicFactor",None) is not None else 1}',f'Pr {getattr(mat,"roughnessFactor",1) if getattr(mat,"roughnessFactor",None) is not None else 1}']
    for key,keyword in [('albedo','map_Kd'),('normal','norm'),('emissive','map_Ke')]:
        if key in maps:
            filename=f'{path.stem}_{key}.png';maps[key].save(path.parent/filename);material.append(f'{keyword} {filename}')
    if 'metallic_roughness' in maps:
        mr=maps['metallic_roughness'].convert('RGB')
        for channel,key,keyword in [('G','roughness','map_Pr'),('B','metallic','map_Pm')]:
            filename=f'{path.stem}_{key}.png';mr.getchannel(channel).save(path.parent/filename);material.append(f'{keyword} {filename}')
    (path.with_suffix('.mtl')).write_text('\n'.join(material)+'\n',encoding='utf-8')


def axis_matrix(text):
    parts=[v.strip().upper() for v in text.split(',')]
    if len(parts)!=3 or any(v not in ['+X','-X','+Y','-Y','+Z','-Z'] for v in parts) or len({v[1] for v in parts})!=3:
        raise ValueError('BMS axes need three distinct signed axes, e.g. +Z,-X,-Y.')
    return np.array([np.eye(3)['XYZ'.index(v[1])]*(1 if v[0]=='+' else -1) for v in parts])


def build_package(lod_dir,settings):
    lod_dir=Path(lod_dir);options=settings['export'];name=_name(options.get('asset_name','asset'))
    paths=sorted(lod_dir.glob('Model_[0-6].glb'))
    if not paths:raise ValueError('No validated LOD GLBs to package.')
    scale=float(options.get('metres_per_unit',1))
    wetness=float(options.get('wetness',0))
    if not np.isfinite(scale) or scale<=0 or not np.isfinite(wetness) or not 0<=wetness<=1:raise ValueError('Export scale/wetness must be finite and in range.')
    bms=bool(options.get('bms_handoff',False));rotation=axis_matrix(options.get('bms_axes','+Z,-X,-Y'))
    report={'profile':'general + static BMS handoff' if bms else 'general interchange','source_units_metres':scale,
            'bms_ready':False,'warnings':[], 'lods':[]}
    general=lod_dir/'interchange';general.mkdir(exist_ok=False)
    handoff=lod_dir/'bms_handoff'
    if bms:handoff.mkdir(exist_ok=False)
    definitions=[];bounds=[];radius=0
    distances=options.get('distances',[])[:len(paths)]
    if len(distances)!=len(paths) or not np.isfinite(distances).all() or any(v<=0 for v in distances) or any(a>=b for a,b in zip(distances,distances[1:])):
        raise ValueError('Provide one positive increasing LOD distance per level.')
    for path in paths:
        mesh=load_static_master(path);material_name=f'{name}_{path.stem}'
        write_obj(mesh,general/path.with_suffix('.obj').name,material_name)
        item={'lod':path.stem,'material':material_name,'inspection':mesh_status(mesh)}
        report['lods'].append(item)
        if not bms:continue
        mat=mesh.visual.material if hasattr(mesh.visual,'material') else None
        if getattr(mat,'alphaMode','OPAQUE') not in (None,'OPAQUE') or getattr(mat,'doubleSided',False):
            raise ValueError('Static BMS PBR handoff requires opaque, single-sided materials. Author glass/cutouts/two-sided effects with the BMS exporter.')
        if np.any(np.asarray(getattr(mat,'emissiveFactor',[0,0,0]) if getattr(mat,'emissiveFactor',None) is not None else [0,0,0])>0):
            raise ValueError('Emissive materials need an explicit BMS shader recipe; use general interchange.')
        native=mesh.copy();transform=np.eye(4);transform[:3,:3]=rotation*(scale/0.3048);native.apply_transform(transform)
        write_obj(native,handoff/'geometry'/path.with_suffix('.obj').name,material_name)
        bounds.append(native.bounds);radius=max(radius,float(np.linalg.norm(native.vertices,axis=1).max()))
        maps=_extract_textures(mesh);factor=base_color_factor(mat)
        albedo=maps.get('albedo',Image.new('RGBA',(4,4),'white')).convert('RGBA')
        albedo=Image.fromarray(np.rint(np.asarray(albedo)*factor).astype('uint8'))
        size=albedo.size
        mr=maps.get('metallic_roughness');rough=float(getattr(mat,'roughnessFactor',1) if getattr(mat,'roughnessFactor',None) is not None else 1);metal=float(getattr(mat,'metallicFactor',1) if getattr(mat,'metallicFactor',None) is not None else 1)
        r=np.asarray(mr.convert('RGB').resize(size).getchannel('G'),dtype=float)*rough if mr else np.full(size[::-1],255*rough)
        m=np.asarray(mr.convert('RGB').resize(size).getchannel('B'),dtype=float)*metal if mr else np.full(size[::-1],255*metal)
        ao=maps.get('occlusion',Image.new('RGB',size,'white')).convert('RGB').resize(size).getchannel('R')
        armw=Image.fromarray(np.stack((np.asarray(ao),np.clip(r,0,255),np.clip(m,0,255),np.full(size[::-1],255*wetness)),axis=-1).astype('uint8'))
        normal=maps.get('normal',Image.new('RGB',size,(128,128,255)))
        for suffix,image in [('ALB',albedo),('ARMW',armw),('NOR',normal)]:image.save(handoff/f'{material_name}_{suffix}.png')
        if 'normal' not in maps:report['warnings'].append(f'{path.stem}: neutral normal authored; no surface detail was invented.')
        definitions.append({'Name':material_name,'Template':{'File':'PBR','Material':'PBR'},
            'Flags':{'Cull':'BACK','ShadowCaster':1,'DepthBias':0,'SlopeScaledDepthBias':0},'ShaderParams':[],'Samplers':[],
            'Textures':[{'Slot':i,'File':f'{material_name}_{suffix}.dds'} for i,suffix in enumerate(['ALB','ARMW','NOR'])]})
        (handoff/f'{path.stem}.mti').write_text(material_name+'\n',encoding='utf-8')
    if bms:
        box=np.array(bounds);low=box[:,0].min(0);high=box[:,1].max(0)
        dimensions=[radius,*np.column_stack((low,high)).ravel()]
        parent='# Static object; bounds in BMS XYZ feet, matching geometry/. Verify after BML export.\n'
        parent+='Dimensions = '+' '.join(f'{v:.6f}' for v in dimensions)+'\nTextureSets = 1\nSwitches = 0\nDofs = 0\n'
        parent+=''.join(f'AddLOD = {path.stem}.bml {distance:g}\n' for path,distance in zip(paths,distances))
        (handoff/'Parent.dat').write_text(parent,encoding='utf-8')
        (handoff/'Materials.mtl').write_text(json.dumps({'Materials':definitions},indent=2)+'\n',encoding='utf-8')
        report.update(bms_axes=options.get('bms_axes','+Z,-X,-Y'),bms_bounds_ft=[low.tolist(),high.tolist()],
            texture_sets=1,material_slots_per_lod=1,missing_for_bms=['BML geometry and matching exporter slot validation','DDS conversion','object/theater database registration','Editor and in-game validation'])
    (lod_dir/'NEXT_STEPS_BMS.txt').write_text(NEXT_STEPS,encoding='utf-8')
    (general/'README.txt').write_text('Wavefront OBJ + MTL and texture maps. Input units are retained; metres/unit: '+str(scale)+'.\nPm/Pr/norm map extensions depend on importer support; GLB is the PBR reference.\n',encoding='utf-8')
    (lod_dir/'export_package.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    # A single download avoids a long virtualized browser list and keeps relative
    # OBJ/MTL/texture paths together. Legacy scaffolds are not mixed into it.
    archive=lod_dir/'export_package.zip'
    members=[*paths,lod_dir/'export_package.json',lod_dir/'NEXT_STEPS_BMS.txt',
             *[p for p in general.rglob('*') if p.is_file()]]
    if bms:members.extend(p for p in handoff.rglob('*') if p.is_file())
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=3) as bundle:
        for member in sorted(members):bundle.write(member,member.relative_to(lod_dir).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:raise ValueError('Export archive failed its integrity check.')
    return report
