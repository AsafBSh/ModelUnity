"""Measured uniform scaling/orientation on a copy and intermediate BMS readiness."""
from dataclasses import dataclass,asdict
import numpy as np
from .schema import checked_number
from .materials import _extract_textures
from scripts.export_contracts import mesh_status


@dataclass(frozen=True)
class ScaleRequest:
    axis: str = "Y"
    metres: float = 1.
    source_up: str = "Y"
    source_forward: str = "+Z"
    pivot: str = "ground center"
    def __post_init__(self):
        if self.axis not in "XYZ" or len(self.axis)!=1 or self.source_up not in ("X","Y","Z"):raise ValueError("Invalid measurement/up axis.")
        if self.source_forward not in ("+X","-X","+Y","-Y","+Z","-Z") or self.source_forward[-1]==self.source_up:raise ValueError("Forward must be perpendicular to source up.")
        if self.pivot not in ("keep","center","ground center"):raise ValueError("Unknown pivot mode.")
        object.__setattr__(self,"metres",checked_number(self.metres,1e-6,1e7,"Measured dimension (metres)"))


def scale_mesh(master,request):
    from .optimization import assert_material_preserved
    result=master.copy();up=np.eye(3)["XYZ".index(request.source_up)]
    forward=np.eye(3)["XYZ".index(request.source_forward[-1])]*(1 if request.source_forward[0]=="+" else -1)
    rotation=np.stack((np.cross(up,forward),up,forward))
    transform=np.eye(4);transform[:3,:3]=rotation;result.apply_transform(transform)
    extent=np.ptp(result.bounds,axis=0)["XYZ".index(request.axis)]
    if extent<=1e-12:raise ValueError("Selected measurement axis has zero extent.")
    factor=request.metres/extent;result.apply_scale(factor)
    offset=np.zeros(3)
    if request.pivot!="keep":
        offset=-result.bounds.mean(0)
        if request.pivot=="ground center":offset[1]=-result.bounds[0,1]
        result.apply_translation(offset)
    assert_material_preserved(master,result)
    return result,{"requested":asdict(request),"uniform_scale":float(factor),"rotation":rotation.tolist(),
        "translation_metres":offset.tolist(),"dimensions_metres":np.ptp(result.bounds,axis=0).tolist(),
        "units":"metres","up_axis":"Y","forward_axis":"+Z","metres_per_unit":1.,
        "limitations":"User-supplied measurement controls accuracy; bounds are not automatic identification of real-world object dimensions."}


def bms_readiness(mesh,settings):
    scale=checked_number(settings.get("metres_per_unit",1),1e-9,1e9,"Metres per unit")
    state=mesh_status(mesh);maps=_extract_textures(mesh);errors=[];warnings=[]
    count=int(checked_number(settings.get("count",1),1,7,"LOD count",True));budgets=settings.get("budgets",[])[:count]
    if len(budgets)!=count:errors.append("Supply one triangle budget per selected LOD.")
    try:
        budgets=[checked_number(v,1,100000000,"LOD budget",True) for v in budgets]
        if any(a<=b for a,b in zip(budgets,budgets[1:])):raise ValueError("LOD budgets must decrease at every lower level.")
    except ValueError as exc:errors.append(str(exc));budgets=[]
    if any(v>=state["triangles"] for v in budgets[1:]):errors.append("Lower LOD budgets at or above the source triangle count would produce duplicate/no-op levels; shorten or reduce the ladder.")
    lod_plan=[{"level":i,"budget":v,"source_triangles":state["triangles"],
        "target_reduction_fraction":max(0,1-v/max(1,state["triangles"]))} for i,v in enumerate(budgets)]
    if not state["uv_valid"]:warnings.append("UVs missing/invalid; shared PBR export requires valid UVs.")
    for name in ("albedo","metallic_roughness"):
        if name not in maps:warnings.append(f"No embedded {name}; complete material preparation before textured BMS conversion.")
    if not state["winding_consistent"]:warnings.append("Inconsistent winding needs review.")
    if state["nonmanifold_edges"]:warnings.append("Indexed non-manifold edges detected; inspect geometry before conversion.")
    distances=settings.get("distances",[])[:count]
    try:
        distances=[checked_number(v,1e-9,1e12,"LOD distance") for v in distances]
        if distances and (len(distances)!=count or any(a>=b for a,b in zip(distances,distances[1:]))):raise ValueError("LOD distances must be positive and increasing, one per selected LOD.")
    except ValueError as exc:errors.append(str(exc));distances=[]
    return {"status":"invalid" if errors else "needs_attention" if warnings else "intermediate_ready",
        "errors":errors,"warnings":warnings,"mesh":state,"dimensions_metres":(np.ptp(mesh.bounds,axis=0)*scale).tolist(),
        "bounds_metres":(mesh.bounds*scale).tolist(),"metres_per_unit":scale,"coordinate_convention":"glTF Y-up; verify asset orientation visually",
        "requested_budgets":budgets,"lod_plan":lod_plan,"distances_feet":distances,"final_game_ready":False,
        "remaining_external_steps":["Convert validated static LODs to BML with the BMS Blender/3ds Max exporter.",
            "Prepare and verify BMS DDS maps/materials and Parent/DOF data.","Review dimensions and LOD transitions in the BMS toolchain before explicit deployment."],
        "limitation":"Indexed topology includes UV seams. This report does not certify printability, exact dimensions, or in-game BMS compatibility."}
