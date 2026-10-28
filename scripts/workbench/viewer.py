"""Offline single-canvas inspection using Gradio's bundled Babylon viewer."""
from pathlib import Path
import json
import re
from urllib.parse import quote
from functools import lru_cache
import numpy as np
from PIL import Image, ImageDraw
from .projects import digest
from .runtime import ROOT,CFG

CACHE = ROOT / CFG.get("paths",{}).get("workbench_runtime_dir",".runtime/workbench_preview") / "viewer"

def checker(size=1024):
    image = Image.new("RGB", (size,size), "#223346")
    draw = ImageDraw.Draw(image)
    cell = size//16
    for y in range(16):
        for x in range(16):
            if (x+y)%2:
                draw.rectangle((x*cell,y*cell,(x+1)*cell,(y+1)*cell),fill="#53cfbf")
    return image

def uv_atlas(path):
    from scripts.export_contracts import load_static_master
    mesh = load_static_master(path)
    uv = getattr(mesh.visual,"uv",None)
    if uv is None or len(uv) != len(mesh.vertices):
        return None, "No valid UV coordinates; UV operations require an unwrapped mesh."
    image = checker()
    draw = ImageDraw.Draw(image)
    points = np.array(uv) * [1023,-1023] + [0,1023]
    for face in mesh.faces:
        vertices = [tuple(p) for p in points[face]]
        draw.line(vertices+[vertices[0]],fill="#f2e4ac",width=1)
    outside = int(np.any((np.array(uv)<0)|(np.array(uv)>1),axis=1).sum())
    return image, f"Actual UV triangle edges · {len(mesh.faces):,} faces · {outside:,} vertices outside 0–1. Overlap/stretch metrics are not computed."

def derived(path, channel):
    if not path or channel == "PBR":
        return path
    from scripts.export_contracts import load_static_master
    from scripts.workbench.materials import _extract_textures
    import trimesh
    destination = CACHE / f"{digest(path)}_{channel.replace(' ','_')}.glb"
    if destination.exists():
        return str(destination)
    mesh = load_static_master(path).copy()
    maps = _extract_textures(mesh)
    uv = getattr(mesh.visual,"uv",None)
    if channel == "Clay":
        material = trimesh.visual.material.PBRMaterial(baseColorFactor=[.68,.74,.8,1],metallicFactor=0,roughnessFactor=.85)
    else:
        if uv is None:
            raise ValueError("Channel inspection requires UV coordinates.")
        if channel == "UV checker":
            image = checker()
        elif channel in ("Roughness","Metallic"):
            if "metallic_roughness" not in maps:
                raise ValueError("The asset has no metallic/roughness texture.")
            image = maps["metallic_roughness"].convert("RGB").getchannel("G" if channel=="Roughness" else "B").convert("RGB")
        else:
            key = {"Albedo":"albedo","Normal":"normal","Occlusion":"occlusion"}[channel]
            if key not in maps:
                raise ValueError(f"The asset has no {key} texture.")
            image = maps[key]
        material = trimesh.visual.material.PBRMaterial(baseColorTexture=image,metallicFactor=0,roughnessFactor=1)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv,material=material)
    CACHE.mkdir(parents=True,exist_ok=True)
    # Deterministic cache files contain derived display materials; originals remain intact.
    mesh.export(destination)
    return str(destination)

@lru_cache(maxsize=128)
def channels(path):
    if not path:return ["PBR","Clay"]
    from scripts.export_contracts import load_static_master
    from scripts.workbench.materials import _extract_textures
    mesh=load_static_master(path)
    maps=_extract_textures(mesh)
    result=["PBR","Clay"]
    if getattr(mesh.visual,"uv",None) is not None:
        result += [label for label,key in (("Albedo","albedo"),("Roughness","metallic_roughness"),
                   ("Metallic","metallic_roughness"),("Normal","normal"),("Occlusion","occlusion")) if key in maps]
        result.append("UV checker")
    return result

def payload(path, display="solid", channel="PBR", bounds=False, light=1, fit=0, distance=0, scale=1):
    target = derived(path,channel)
    return json.dumps({"url":"/gradio_api/file="+quote(str(Path(target).resolve()).replace("\\","/"),safe="/:") if target else None,
                       "mode":display,"bounds":bounds,"light":light,"fit":fit,"channel":channel,
                       "distance":distance,"scale":scale})

def viewer_js():
    import gradio
    assets = Path(gradio.__file__).parent / "templates" / "frontend" / "assets"
    for path in assets.glob("Canvas3D-*.js"):
        source = path.read_text(encoding="utf-8")
        match = re.search(r'import\("\./([^\"]+)"\)\.then\(\w+=>\w+\.(\w+)\)',source)
        if match:
            module, export = match.groups()
            break
    else:
        raise RuntimeError("Installed Gradio viewer bundle changed; verify the supported Gradio 6.17.3 frontend.")
    return "(async()=>{" + JS.replace("__MODULE__",module).replace("__EXPORT__",export) + "})().catch(error=>{element.querySelector('.viewer-message').textContent='Viewer error: '+error.message;console.error(error);});"

JS = r"""
const canvas = element.querySelector('canvas');
const status = element.querySelector('.viewer-message');
let details, viewer, loaded = null, lastFit = 0, lastDistance = null, serial = Promise.resolve();
const api = (await import('/assets/__MODULE__')).__EXPORT__;
viewer = await api.CreateViewerForCanvas(canvas, {
 clearColor:[0.043,0.067,0.102,1],useRightHandedSystem:true,animationAutoPlay:false,
 cameraAutoOrbit:{enabled:false},onInitialized:value=>{details=value;}
});
window.muWorkbenchViewer = {viewer,get details(){return details;},get loaded(){return loaded;}};
canvas.addEventListener('pointerup', event=>{
 if(!event.shiftKey || !details || !loaded)return;
 const rect=canvas.getBoundingClientRect(), x=event.clientX-rect.left, y=event.clientY-rect.top;
 const field=document.querySelector('#protect-center textarea, #protect-center input');
 let point=null;
 {
  // Gradio's tree-shaken viewer does not register Babylon's optional Ray module.
  // Unproject screen coordinates and intersect retained CPU triangles directly.
  const matrix=details.scene.getTransformMatrix().constructor.Identity();
  const camera=details.scene.activeCamera,Vector=camera.position.constructor,engine=details.scene.getEngine();
  const width=engine.getRenderWidth(),height=engine.getRenderHeight();
  const screenX=x*width/rect.width,screenY=y*height/rect.height;
  const near=Vector.Unproject(new Vector(screenX,screenY,0),width,height,matrix,camera.getViewMatrix(),camera.getProjectionMatrix());
  const far=Vector.Unproject(new Vector(screenX,screenY,1),width,height,matrix,camera.getViewMatrix(),camera.getProjectionMatrix());
  const ray={origin:near,direction:far.subtract(near).normalize()};let closest=Infinity,visited=0;
  for(const mesh of details.scene.meshes){
   const vertices=mesh.getVerticesData('position'),indices=mesh.getIndices();
   if(!vertices||!indices||!mesh.isVisible)continue;
   visited+=indices.length/3;if(visited>2000000)break;
   const inverse=mesh.getWorldMatrix().clone().invert();
   const o=Vector.TransformCoordinates(ray.origin,inverse),d=Vector.TransformNormal(ray.direction,inverse);
   for(let i=0;i<indices.length;i+=3){
    const a=indices[i]*3,b=indices[i+1]*3,c=indices[i+2]*3;
    const e1=[vertices[b]-vertices[a],vertices[b+1]-vertices[a+1],vertices[b+2]-vertices[a+2]];
    const e2=[vertices[c]-vertices[a],vertices[c+1]-vertices[a+1],vertices[c+2]-vertices[a+2]];
    const p=[d.y*e2[2]-d.z*e2[1],d.z*e2[0]-d.x*e2[2],d.x*e2[1]-d.y*e2[0]];
    const det=e1[0]*p[0]+e1[1]*p[1]+e1[2]*p[2];if(Math.abs(det)<1e-12)continue;
    const t=[o.x-vertices[a],o.y-vertices[a+1],o.z-vertices[a+2]];
    const u=(t[0]*p[0]+t[1]*p[1]+t[2]*p[2])/det;if(u<0||u>1)continue;
    const q=[t[1]*e1[2]-t[2]*e1[1],t[2]*e1[0]-t[0]*e1[2],t[0]*e1[1]-t[1]*e1[0]];
    const v=(d.x*q[0]+d.y*q[1]+d.z*q[2])/det;if(v<0||u+v>1)continue;
    const distance=(e2[0]*q[0]+e2[1]*q[1]+e2[2]*q[2])/det;
    if(distance>=0&&distance<closest){closest=distance;point=[o.x+d.x*distance,o.y+d.y*distance,o.z+d.z*distance];}
   }
  }
 }
 if(point && field){
  field.value=point.map(v=>v.toPrecision(9)).join(',');
  field.dispatchEvent(new Event('input',{bubbles:true}));
  status.textContent='Protection center picked. Use the working Result view; set a half-size in Optimize.';
 }else{
  status.textContent='No triangle picked. Shift-click on the working surface or enter region coordinates numerically.';
 }
});
const resize = new ResizeObserver(()=>{
 if(details){details.scene.getEngine().resize();details.markSceneMutated();}
});
resize.observe(element);
async function update() {
 const p = JSON.parse(props.value || '{}');
 try {
  if(p.url !== loaded) {
   const c = details.camera;
   const old = loaded ? {alpha:c.alpha,beta:c.beta,radius:c.radius,target:c.target.clone(),
     upperRadiusLimit:c.upperRadiusLimit,minZ:c.minZ,maxZ:c.maxZ} : null;
   status.textContent = p.url ? 'Loading asset…' : 'Open or generate an asset';
   if(p.url) {
    await viewer.loadModel(p.url);
    if(old) {
     // loadModel starts an asynchronous camera interpolation. Stop it before
     // restoring comparison framing or later frames keep changing the radius.
     c.stopInterpolation();details.scene.stopAnimation(c);
     c.inertialAlphaOffset=c.inertialBetaOffset=c.inertialRadiusOffset=0;
     c.inertialPanningX=c.inertialPanningY=0;
     // setTarget normally rebuilds spherical coordinates from the newly loaded
     // model's position. Its clone flag keeps the saved angles/radius intact.
     c.setTarget(old.target,false,false,true);c.alpha=old.alpha;c.beta=old.beta;c.radius=old.radius;
     c.upperRadiusLimit=old.upperRadiusLimit;c.minZ=old.minZ;c.maxZ=Math.max(old.maxZ,c.radius*10);
    }
   } else viewer.resetModel();
   loaded=p.url;
  }
  details.scene.forceWireframe=p.mode==='wireframe';
  details.scene.forcePointsCloud=p.mode==='point_cloud';
  details.scene.environmentIntensity=Number(p.light ?? 1);
  for(const mesh of details.scene.meshes) mesh.showBoundingBox=Boolean(p.bounds);
  if(p.fit !== lastFit) {viewer.resetCamera();lastFit=p.fit;}
  const distanceKey=JSON.stringify([p.distance,p.scale]);
  if(distanceKey!==lastDistance && p.distance>0 && p.scale>0) {
   details.camera.radius=Number(p.distance)*.3048/Number(p.scale);
   details.camera.maxZ=Math.max(10000,details.camera.radius*10);
  }
  lastDistance=distanceKey;
  details.camera.lowerRadiusLimit=.01;
  // The viewer sleeps while the camera is still. Scene properties alone do not
  // wake its on-demand render loop; invalidate after applying every preview update.
  details.markSceneMutated();
  status.textContent = p.url ? p.channel+' · Drag to orbit · Wheel to zoom · Right-drag to pan' : 'Open or generate an asset';
  canvas.dataset.ready = p.url ? 'true' : 'empty';
 } catch(error) {status.textContent='Viewer error: '+error.message;canvas.dataset.ready='error';}
}
function schedule(){serial=serial.then(update).catch(error=>{status.textContent=error.message;});}
watch('value',schedule); schedule();
const observer = new MutationObserver(()=>{if(!element.isConnected){resize.disconnect();observer.disconnect();viewer.dispose();}});
observer.observe(document.body,{childList:true,subtree:true});
"""

TEMPLATE = '<div class="mu-viewer"><canvas aria-label="3D asset inspection viewport"></canvas><div class="viewer-message">Starting local 3D viewer…</div></div>'
VIEWER_CSS = """
height:100%;min-height:0;display:flex;flex:1;
.mu-viewer{position:relative;height:100%;width:100%;min-height:150px;overflow:hidden;background:#0b111a;}
canvas{display:block;width:100%;height:100%;touch-action:none;outline:none;}
.viewer-message{position:absolute;bottom:12px;left:12px;right:12px;pointer-events:none;color:#91b0c7;font-family:var(--mu-font-ui,'Segoe UI',sans-serif);font-size:11px;line-height:1.45;}
"""
