"""The parameter contract shared by services, presets and model inspectors."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from math import isfinite

VIEWS = ("front", "left", "back", "right")
SHAPE_KEYS = ["t_steps", "t_guidance", "t_octree", "t_dense", "t_bounds", "t_bg",
              "t_seed", "t_faces", "t_planar", "m_steps", "m_octree", "m_guidance",
              "m_chunks", "m_level", "m_seed", "m_faces", "m_bake", "m_paint",
              "c_multiview", "c_resolution", "c_seed", "c_structure_steps", "c_shape_steps",
              "c_upsample_steps", "c_texture_steps", "c_guidance", "c_texture_guidance",
              "c_texture", "c_texture_size", "c_fov", "c_auto_fov", "c_remesh",
              "c_remesh_resolution", "c_remesh_qef", "c_faces", "c_guard_bounds", "c_guard_surface", "c_guard_strict"]
PAINT_KEYS = ["p_views", "p_resolution", "p_render", "p_texture", "p_exponent",
              "p_merge", "p_remesh", "p_maps", "p_low", "normal"]
TRIPOSG_PRESETS = {"Fast": dict(steps=25, guidance=7., octree=8, faces=15000),
                   "Balanced": dict(steps=50, guidance=7., octree=9, faces=25000),
                   "HQ": dict(steps=75, guidance=8.5, octree=10, faces=50000)}
HUNYUAN_MV_PRESETS = {"Fast": dict(steps=25, octree=256, guidance=4., chunks=10000),
                      "Balanced": dict(steps=50, octree=380, guidance=5., chunks=20000),
                      "HQ": dict(steps=75, octree=512, guidance=6., chunks=30000)}
PAINT_PRESETS = {"Speed": dict(views=4, resolution=256, render_size=512, texture_size=1024),
                 "Balanced": dict(views=6, resolution=512, render_size=1024, texture_size=2048),
                 "HQ": dict(views=8, resolution=512, render_size=1024, texture_size=4096)}

# UI labels, limits, units and help originate here and are validated again on execution.
PARAMETERS = {
 "t_steps": (15, 75, 1, "Diffusion steps", "Denoising iterations; more steps increase runtime."),
 "t_guidance": (1, 15, .5, "Guidance scale", "Image conditioning strength; excessive guidance can distort geometry."),
 "t_octree": (7, 10, 1, "Octree depth", "Hierarchical extraction depth; higher values need more memory."),
 "t_dense": (6, 9, 1, "Dense octree depth", "Coarse extraction depth; effective value is capped by octree depth."),
 "t_bounds": (.5, 2, .05, "Extraction bounds", "Half-width of the SDF cube; small bounds may clip the object."),
 "m_steps": (15, 75, 1, "Diffusion steps", "Denoising iterations for multi-view shape generation."),
 "m_octree": (256, 512, 4, "Octree resolution", "Volume extraction resolution, distinct from TripoSG depth."),
 "m_guidance": (1, 15, .5, "Guidance scale", "Strength of conditioning on the supplied directions."),
 "m_level": (-.5, .5, .01, "Marching-cubes level", "Isosurface threshold; changes the extracted surface."),
 "p_views": (4, 8, 1, "Baking views", "Virtual projection views, not additional user photographs."),
 "p_resolution": (256, 512, 64, "Diffusion resolution", "Pixels per diffusion view; distinct from the final atlas."),
 "p_exponent": (1, 8, 1, "Bake exponent", "Weight exponent used to combine projected texture views."),
}


def checked_number(value, low, high, name, integer=False):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric.")
    number = float(value)
    if not isfinite(number) or not low <= number <= high or (integer and int(number) != number):
        raise ValueError(f"{name} must be {'an integer ' if integer else ''}between {low} and {high}.")
    return int(number) if integer else number


@dataclass(frozen=True)
class Preparation:
    provider: str = "none"
    model: str = "u2net"
    size: int = 1024
    margin: float = .05
    crop: str = ""
    background: str = "transparent"
    preserve_alpha: bool = True
    alpha_matting: bool = False
    foreground: int = 240
    background_threshold: int = 10
    erode: int = 10
    postprocess: bool = False
    execution: str = "CPUExecutionProvider"
    manual_alpha_digests: tuple = ()

    def __post_init__(self):
        import re
        if not isinstance(self.manual_alpha_digests, (tuple,list)) or len(self.manual_alpha_digests)>64 or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for v in self.manual_alpha_digests):
            raise ValueError('Invalid manual mask image fingerprints.')
        if self.provider not in ("none", "rembg", "rmbg"):
            raise ValueError("Choose keep alpha, rembg or RMBG-1.4.")
        if self.model not in ("u2net", "u2netp", "isnet-general-use", "silueta"):
            raise ValueError("Unsupported rembg model.")
        if self.background not in ("transparent", "white", "black"):
            raise ValueError("Invalid background output.")
        if self.execution not in ("CPUExecutionProvider", "CUDAExecutionProvider"):
            raise ValueError("Unsupported ONNX execution provider.")
        checked_number(self.size, 256, 2048, "Output size", True)
        checked_number(self.margin, 0, .4, "Padding margin")
        for name, value in (("Foreground threshold", self.foreground), ("Background threshold", self.background_threshold)):
            checked_number(value, 0, 255, name, True)
        checked_number(self.erode, 0, 100, "Erosion size", True)
        if self.background_threshold >= self.foreground:
            raise ValueError("Background threshold must be less than foreground threshold.")
        if self.provider != "rembg" and (self.alpha_matting or self.postprocess):
            raise ValueError("Alpha matting and mask postprocessing require rembg.")

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ShapeRequest:
    backend: str = "Hunyuan3D-2mv"
    steps: int = 50
    guidance: float = 5.
    seed: int = 12345
    faces: int = 20000
    octree: int = 380
    dense: int = 8
    bounds: float = 1.25
    chunks: int = 20000
    level: float = 0.
    bake_view: str = "front"
    box_v: float = 1.01

    def __post_init__(self):
        if self.backend not in ("TripoSG 1.5B", "Hunyuan3D-2mv"):
            raise ValueError("Unknown shape backend.")
        checked_number(self.steps, 15, 75, "Diffusion steps", True)
        checked_number(self.guidance, 1, 15, "Guidance")
        checked_number(self.seed, 0, 2**63 - 1, "Seed", True)
        checked_number(self.faces, -1, 10_000_000, "Face target", True)
        if self.faces == 0:
            raise ValueError("Face target must be positive or -1 to retain geometry.")
        if self.backend == "TripoSG 1.5B":
            checked_number(self.octree, 7, 10, "Octree depth", True)
            checked_number(self.dense, 6, 9, "Dense depth", True)
            checked_number(self.bounds, .5, 2, "Bounds")
        else:
            checked_number(self.octree, 256, 512, "Octree resolution", True)
            checked_number(self.chunks, 1, 1_000_000, "Decoder chunks", True)
            checked_number(self.level, -.5, .5, "MC level")
            checked_number(self.box_v, .5, 2, "Bounding box scale")
        if self.bake_view not in (*VIEWS, "none"):
            raise ValueError("Invalid projection view.")

    @classmethod
    def from_settings(cls, backend, p):
        from scripts.comfyui_workflows import BACKENDS, ComfyRequest
        if backend in BACKENDS:
            return ComfyRequest.from_settings({**p,"backend":backend})
        single = backend == "TripoSG 1.5B"
        prefix = "t_" if single else "m_"
        def integer(value):
            return checked_number(value,-1,2**63-1,"Integer model parameter",True)
        return cls(backend=backend, steps=integer(p[prefix+"steps"]), guidance=float(p[prefix+"guidance"]),
                   seed=integer(p[prefix+"seed"]), faces=integer(p[prefix+"faces"]), octree=integer(p[prefix+"octree"]),
                   dense=integer(p.get("t_dense", 8)), bounds=float(p.get("t_bounds", 1.25)),
                   chunks=integer(p.get("m_chunks", 20000)), level=float(p.get("m_level", 0)),
                   box_v=float(p.get("m_box", 1.01)),
                   bake_view=("front" if p.get("t_planar") else "none") if single else p.get("m_bake", "front"))


@dataclass(frozen=True)
class OptimizationRequest:
    target: int = 8000
    max_passes: int = 3
    repair_winding: bool = True
    preserve_boundary: bool = False
    strict_budget: bool = False
    allow_uv_fallback: bool = False
    max_bounds_change: float = 5.0
    max_surface_error: float = 2.0
    protected_box: str = ""
    protected_faces: str = ""
    sharp_angle: float = 0.0

    def __post_init__(self):
        object.__setattr__(self,'sharp_angle',checked_number(self.sharp_angle,0,180,'Protected sharp-edge angle'))
        if not isinstance(self.protected_box,str) or not isinstance(self.protected_faces,str):raise ValueError('Protected selections must be text.')
        object.__setattr__(self, "target", checked_number(self.target, 1, 10_000_000, "Optimization target", True))
        object.__setattr__(self, "max_passes", checked_number(self.max_passes, 1, 3, "Optimization passes", True))
        object.__setattr__(self, "max_bounds_change", checked_number(self.max_bounds_change, 0, 100, "Bounds change (%)"))
        object.__setattr__(self, "max_surface_error", checked_number(self.max_surface_error, 0, 100, "Sampled surface error (%)"))
        for key in ("repair_winding", "preserve_boundary", "strict_budget", "allow_uv_fallback"):
            if not isinstance(getattr(self, key), bool):
                raise ValueError(f"{key} must be a boolean.")


@dataclass(frozen=True)
class PaintRequest:
    views: int = 6
    resolution: int = 512
    render_size: int = 1024
    texture_size: int = 2048
    exponent: int = 4
    merge: str = "fast"
    remesh: bool = True
    maps: bool = False
    low_vram: bool = True
    normal: str = "low"

    def __post_init__(self):
        checked_number(self.views, 4, 8, "Baking views", True)
        checked_number(self.exponent, 1, 8, "Bake exponent", True)
        if self.resolution not in (256, 320, 384, 448, 512):
            raise ValueError("Invalid paint diffusion resolution.")
        if self.render_size not in (512, 1024, 2048, 4096) or self.texture_size not in (1024, 2048, 4096, 8192):
            raise ValueError("Unsupported render/atlas resolution.")
        if self.merge not in ("fast", "max") or self.normal not in ("off", "low", "medium", "high"):
            raise ValueError("Invalid texture merge or normal baker.")

    @classmethod
    def from_settings(cls, p):
        def integer(key):
            return checked_number(p[key],1,8192,key,True)
        return cls(views=integer("p_views"), resolution=integer("p_resolution"), render_size=integer("p_render"),
                   texture_size=integer("p_texture"), exponent=integer("p_exponent"), merge=p["p_merge"],
                   remesh=bool(p["p_remesh"]), maps=bool(p["p_maps"]), low_vram=bool(p["p_low"]), normal=p["normal"])
