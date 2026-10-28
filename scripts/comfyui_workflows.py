"""Native ComfyUI 3D graphs, derived from the official 2026-10-21 templates.

No custom nodes or hidden background remover. The raw decoded shape is saved
separately before explicitly configured working-mesh cleanup and UV/PBR baking.
"""
from dataclasses import dataclass
from scripts.workbench.schema import checked_number

BACKENDS = ("TRELLIS.2 · ComfyUI", "Pixal3D · ComfyUI")
KEYS = ("c_multiview", "c_resolution", "c_seed", "c_structure_steps", "c_shape_steps",
        "c_upsample_steps", "c_texture_steps", "c_guidance", "c_texture_guidance",
        "c_texture", "c_texture_size", "c_fov", "c_auto_fov", "c_remesh",
        "c_remesh_resolution", "c_remesh_qef", "c_faces")
WEIGHTS = {
    "trellis": "trellis_2_int8_convrot.safetensors",
    "pixal": "pixal3d_int8_convrot.safetensors",
    "pixal_mv": "pixal3d_multiview_int8_convrot.safetensors",
    "shape_vae": "trellis_2_shape_vae_bf16.safetensors",
    "texture_vae": "trellis_2_texture_vae_bf16.safetensors",
    "vision": "dino_v3_L_naf_fp32.safetensors",
    "moge": "moge_2_vitl_normal_fp16.safetensors",
}


@dataclass(frozen=True)
class ComfyRequest:
    backend: str = BACKENDS[0]
    multiview: bool = False
    resolution: int = 1024
    seed: int = 42
    structure_steps: int = 12
    shape_steps: int = 20
    upsample_steps: int = 12
    texture_steps: int = 12
    guidance: float = 7.5
    texture_guidance: float = 1.0
    texture: bool = True
    texture_size: int = 2048
    fov: float = 20.0
    auto_fov: bool = True
    remesh: bool = True
    remesh_resolution: int = 768
    remesh_qef: bool = False
    faces: int = 700000

    def __post_init__(self):
        if self.backend not in BACKENDS:
            raise ValueError("Unknown ComfyUI 3D model.")
        for key in ("multiview", "texture", "auto_fov", "remesh", "remesh_qef"):
            if not isinstance(getattr(self,key),bool):
                raise ValueError(f"{key} must be a boolean.")
        if self.backend == BACKENDS[0] and self.multiview:
            raise ValueError("TRELLIS.2 supports one image in this integration.")
        for key in ("resolution", "texture_size"):
            value = checked_number(getattr(self,key), 1, 8192, key, True)
            allowed = (512,1024,1536) if key == "resolution" else (1024,2048,4096,8192)
            if value not in allowed:
                raise ValueError(f"Unsupported {key}.")
            object.__setattr__(self,key,value)
        for key in ("structure_steps", "shape_steps", "upsample_steps", "texture_steps"):
            object.__setattr__(self,key,checked_number(getattr(self,key),1,100,key,True))
        object.__setattr__(self,"seed",checked_number(self.seed,0,2**53-1,"ComfyUI seed",True))
        for key in ("guidance", "texture_guidance"):
            object.__setattr__(self,key,checked_number(getattr(self,key),0,30,key))
        object.__setattr__(self,"fov",checked_number(self.fov,1,170,"Horizontal FOV"))
        object.__setattr__(self,"remesh_resolution",checked_number(self.remesh_resolution,32,2048,"Remesh resolution",True))
        object.__setattr__(self,"faces",checked_number(self.faces,0,50000000,"Working mesh face budget",True))

    @classmethod
    def from_settings(cls, settings):
        values = {key:settings.get("c_"+key, field.default) for key,field in cls.__dataclass_fields__.items() if key != "backend"}
        # A saved Pixal multiview toggle is inert when TRELLIS is selected.
        if settings["backend"] == BACKENDS[0]:
            values["multiview"] = False
        return cls(backend=settings["backend"], **values)

    def weight_key(self):
        return "trellis" if self.backend == BACKENDS[0] else "pixal_mv" if self.multiview else "pixal"


def build_workflow(request, uploads, prefix, weights=None):
    """Return an API-format graph and named output nodes; all settings are bound."""
    weights = {**WEIGHTS, **(weights or {})}
    if not uploads or (not request.multiview and "front" not in uploads):
        raise ValueError("Upload a Front image; Pixal multiview accepts 1–4 named directions.")
    if not request.multiview and set(uploads) != {"front"}:
        raise ValueError("Single-image workflow received extra views.")
    graph = {}
    def node(name, kind, **inputs):
        graph[name] = {"class_type":kind,"inputs":inputs,"_meta":{"title":name}}
        return [name,0]
    model = node("model","UNETLoader",unet_name=weights[request.weight_key()],weight_dtype="default")
    vision = node("vision","CLIPVisionLoader",clip_name=weights["vision"])
    shape_vae = node("shape_vae","VAELoader",vae_name=weights["shape_vae"])
    images = {key:node("image_"+key,"LoadImage",image=value) for key,value in uploads.items()}
    if request.backend == BACKENDS[0]:
        cond = node("conditioning","Trellis2Conditioning",clip_vision_model=vision,image=images["front"])
    elif request.multiview:
        cond = node("conditioning","Pixal3DMultiViewConditioning",clip_vision_model=vision,fov=request.fov,**images)
    else:
        fov = request.fov
        if request.auto_fov:
            moge = node("moge","LoadMoGeModel",model_name=weights["moge"])
            geometry = node("camera","MoGeInference",moge_model=moge,image=images["front"],
                            resolution_level=9,fov_x_degrees=0.,batch_size=1,force_projection=True,apply_mask=True,refine_steps=3)
            fov = node("fov","MoGeGeometryToFOV",moge_geometry=geometry,axis="horizontal",unit="degrees")
        cond = node("conditioning","Pixal3DConditioning",clip_vision_model=vision,image=images["front"],camera_angle_x=fov)
    negative = ["conditioning",1]
    empty = node("empty","EmptyTrellis2LatentStructure",batch_size=1)
    struct_cfg = node("structure_cfg","CFGOverride",model=model,cfg=1.,start_percent=.667,end_percent=1.)
    struct_rescale = node("structure_rescale","RescaleCFG",model=struct_cfg,multiplier=.7)
    struct_model = node("structure_schedule","ModelSamplingSD3",model=struct_rescale,shift=5.)
    shape_cfg = node("shape_cfg","CFGOverride",model=model,cfg=1.,start_percent=.769,end_percent=1.)
    shape_model = node("shape_rescale","RescaleCFG",model=shape_cfg,multiplier=.5)
    def sample(name, sampler_model, positive, neg, latent, steps, cfg, scheduler="normal"):
        return node(name,"KSampler",model=sampler_model,positive=positive,negative=neg,latent_image=latent,
                    seed=request.seed,steps=steps,cfg=cfg,sampler_name="euler",scheduler=scheduler,denoise=1.)
    structure = sample("structure",struct_model,cond,negative,empty,request.structure_steps,request.guidance)
    voxel = node("structure_decode","VaeDecodeStructureTrellis2",samples=structure,vae=shape_vae,resolution="32")
    stage = node("shape_stage","Trellis2ShapeStage",positive=cond,negative=negative,voxel=voxel)
    shape = sample("shape",shape_model,stage,["shape_stage",1],["shape_stage",2],request.shape_steps,request.guidance)
    positive, neg = stage, ["shape_stage",1]
    if request.resolution > 512:
        positive = node("upsample_stage","Trellis2UpsampleStage",positive=stage,negative=neg,shape_latent=shape,
                        vae=shape_vae,target_resolution=request.resolution)
        neg = ["upsample_stage",1]
        shape = sample("upsample",shape_model,positive,neg,["upsample_stage",2],request.upsample_steps,request.guidance,"simple")
    mesh = node("shape_decode","VaeDecodeShapeTrellis",samples=shape,vae=shape_vae)
    node("save_master","SaveGLB",mesh=mesh,filename_prefix=prefix+"/master")
    working = mesh
    if request.remesh:
        working = node("remesh","RemeshMesh",mesh=working,resolution=request.remesh_resolution,
            sign_mode="solid",band=1.,project_back=0.,fix_poles=False,smooth_iters=0,
            drop_small_components=0.,precluster_max_verts=0,
            **{"sign_mode.fill":20.,"sign_mode.qef":request.remesh_qef})
    if request.faces:
        working = node("decimate","DecimateMesh",mesh=working,target_face_count=request.faces,placement_mode="midpoint")
    result_node = "save_master"
    if request.texture:
        tex_stage = node("texture_stage","Trellis2TextureStage",positive=positive,negative=neg,shape_latent=shape)
        tex = sample("texture",model,tex_stage,["texture_stage",1],["texture_stage",2],request.texture_steps,request.texture_guidance)
        tex_vae = node("texture_vae","VAELoader",vae_name=weights["texture_vae"])
        colors = node("texture_decode","VaeDecodeTextureTrellis",samples=tex,vae=tex_vae,shape_subdivides=["shape_decode",1])
        uv = node("unwrap","UnwrapMesh",mesh=working,segmenter="pec",resolution=request.texture_size,padding=1,weld_distance=0.)
        baked = node("bake","BakeTextureFromVoxel",mesh=uv,voxel_colors=colors,reference_mesh=mesh,texture_size=request.texture_size)
        painted = node("material","ApplyTextureToMesh",mesh=uv,base_color=baked,metallic=["bake",1],roughness=["bake",2])
        node("save_result","SaveGLB",mesh=painted,filename_prefix=prefix+"/asset")
        result_node = "save_result"
    elif working != mesh:
        node("save_result","SaveGLB",mesh=working,filename_prefix=prefix+"/asset")
        result_node = "save_result"
    return graph, {"master":"save_master","result":result_node}


def check_graph(graph, object_info):
    """Fail before queueing if nodes, checkpoint selections or inputs are missing."""
    problems = []
    for ident,node in graph.items():
        kind = node["class_type"]
        if kind not in object_info:
            problems.append(f"Missing node {kind}; update ComfyUI core / inspect its startup log.")
            continue
        schema = {k:dict(v) for k,v in object_info[kind].get("input",{}).items() if k in ("required","optional")}
        # V3 dynamic combo fields use dotted keys in API-format prompts.
        for category in ("required","optional"):
            for key,spec in list(schema.get(category,{}).items()):
                if spec[0] == "COMFY_DYNAMICCOMBO_V3":
                    options = spec[1]["options"]
                    choice = next((o for o in options if o["key"]==node["inputs"].get(key)),None)
                    if choice is None:
                        problems.append(f"{ident}: unsupported {key} choice.")
                    else:
                        for group in ("required","optional"):
                            schema.setdefault(group,{}).update({key+"."+k:v for k,v in choice["inputs"].get(group,{}).items()})
        for key,spec in schema.get("required",{}).items():
            if key not in node["inputs"]:
                problems.append(f"{ident}: required input {key} is missing (node schema changed).")
        for key,value in node["inputs"].items():
            spec = schema.get("required",{}).get(key,schema.get("optional",{}).get(key))
            if spec is None:
                problems.append(f"{ident}: unsupported input {key} (node schema changed).")
            # LoadImage accepts uploaded subfolder paths through VALIDATE_INPUTS;
            # its UI combo is a root-only snapshot taken before our upload.
            elif kind != "LoadImage" and not isinstance(value,list):
                options = spec[0] if isinstance(spec[0],list) else spec[1].get("options") if len(spec)>1 and spec[0]=="COMBO" else None
                if options is not None and value not in options:
                    problems.append(f"{ident}: {key}={value!r} is unavailable; install/select its checkpoint.")
    if problems:
        raise ValueError("ComfyUI preflight failed:\n"+"\n".join(problems))
    return True
