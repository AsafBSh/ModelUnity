"""Bounded CPU reference/mask checks; camera alignment remains a user contract."""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from .schema import VIEWS, Preparation


def mask_metrics(image):
    rgba=image.convert("RGBA"); alpha=np.asarray(rgba.getchannel("A"),dtype=float)/255
    foreground=alpha>.1
    ys,xs=np.nonzero(foreground)
    bbox=None if not len(xs) else [int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)]
    return {"size":list(image.size),"has_alpha_mask":bool(alpha.min()<1),
        "foreground_fraction":float(foreground.mean()),"soft_alpha_fraction":float(((alpha>.01)&(alpha<.99)).mean()),
        "bbox":bbox,"edge_contact_fraction":float(np.concatenate((foreground[0],foreground[-1],foreground[:,0],foreground[:,-1])).mean()),
        "bbox_fraction":None if bbox is None else [(bbox[2]-bbox[0])/image.width,(bbox[3]-bbox[1])/image.height],
        "center_fraction":None if bbox is None else [(bbox[2]+bbox[0])/2/image.width,(bbox[3]+bbox[1])/2/image.height]}


def overlay(image):
    """Checkerboard, alpha boundary and framing crosshair; no mask modification."""
    rgba=image.convert("RGBA"); bg=Image.new("RGBA",rgba.size,"#172b38"); draw=ImageDraw.Draw(bg)
    cell=max(8,image.width//16)
    for y in range(0,image.height,cell):
        for x in range(0,image.width,cell):
            if (x//cell+y//cell)%2:draw.rectangle((x,y,x+cell-1,y+cell-1),fill="#355263")
    result=Image.alpha_composite(bg,rgba).convert("RGB")
    alpha=rgba.getchannel("A"); edge=alpha.filter(ImageFilter.FIND_EDGES).point(lambda p:255 if p>30 else 0)
    result.paste(Image.new("RGB",rgba.size,"#ffca66"),(0,0),edge)
    d=ImageDraw.Draw(result);m=mask_metrics(rgba)
    if m["bbox"]:d.rectangle(m["bbox"],outline="#69ecd0",width=max(1,image.width//512))
    cx,cy=image.width//2,image.height//2
    d.line((cx-10,cy,cx+10,cy),fill="#ec8fea",width=2);d.line((cx,cy-10,cx,cy+10),fill="#ec8fea",width=2)
    return result


def check_inputs(settings,images):
    backend=settings.get("backend","Hunyuan3D-2mv")
    multi=backend=="Hunyuan3D-2mv" or (backend.startswith("Pixal3D") and settings.get("c_multiview",False))
    fixed=backend.startswith("Pixal3D") and multi
    prep=Preparation(**settings.get("preparation",{}))
    result={"ready":False,"errors":[],"warnings":[],"views":{},"model":backend,
            "alignment_verified":False,"alignment_method":"Mask/framing heuristics; cannot verify camera poses or object identity."}
    sizes=[];boxes=[]
    for name in VIEWS if multi else ("front",):
        image=images.get(name)
        if image is None:continue
        if not isinstance(image,Image.Image):
            with Image.open(image) as pixels:image=pixels.copy()
        pixels=image.convert("RGBA");small=pixels.copy();small.thumbnail((512,512))
        metrics=mask_metrics(small);metrics["original_size"]=list(image.size);result["views"][name]=metrics;sizes.append(image.size)
        if metrics["bbox"] is None:result["errors"].append(f"{name}: alpha is empty; no foreground to reconstruct.")
        if min(image.size)<256:result["warnings"].append(f"{name}: less than 256 pixels; small details may be lost.")
        if not metrics["has_alpha_mask"] and prep.provider=="none":
            rgb=np.asarray(small.convert("RGB"));border=np.concatenate((rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]))
            if np.mean(np.max(border,axis=1)>24)>.1:
                result["warnings"].append(f"{name}: opaque scene background retained. Choose a remover or supply an isolated object on black/alpha.")
        if metrics["has_alpha_mask"]:
            if metrics["foreground_fraction"]<.01:result["warnings"].append(f"{name}: foreground occupies less than 1% of the frame.")
            if metrics["edge_contact_fraction"]>.03:result["warnings"].append(f"{name}: foreground touches image edges; check clipped extremities.")
            if metrics["bbox_fraction"]:boxes.append(max(metrics["bbox_fraction"]))
        if prep.crop.strip():
            try:
                x1,y1,x2,y2=map(int,prep.crop.split(","))
                valid=0<=x1<x2<=image.width and 0<=y1<y2<=image.height
            except ValueError:valid=False
            if not valid:result["errors"].append(f"{name}: crop is invalid or outside the image.")
    if not result["views"]:result["errors"].append("Upload at least one reference view.")
    if not multi and "front" not in result["views"]:result["errors"].append("This model requires the Front input.")
    if fixed:
        result["camera_contract"]="Named Front/Left/Back/Right at 90-degree intervals, equal framing/scale and shared horizontal FOV."
        if len(set(sizes))>1:result["errors"].append("Pixal multiview originals must have equal dimensions.")
        if prep.crop.strip():result["errors"].append("Pixal multiview requires aligned originals; individual cropping is disabled.")
        if len(boxes)>1 and max(boxes)/max(min(boxes),1e-9)>1.25:
            result["warnings"].append("Mask bounding-box sizes differ by over 25%; check shared object scale and camera framing.")
        if not settings.get("input_confirm_rig",False):result["warnings"].append("Confirm the fixed-orbit camera contract; these checks cannot calibrate arbitrary photographs.")
        if "front" not in result["views"] and result["views"]:result["warnings"].append("No Front supplied: Pixal will pose the first supplied direction as front.")
    result["ready"]=not result["errors"]
    return result
