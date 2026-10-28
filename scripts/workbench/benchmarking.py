"""Shared reproducible shape settings for GUI/CLI generator comparisons."""
from scripts.comfyui_workflows import BACKENDS as COMFY

MODELS={"triposg":"TripoSG 1.5B","hunyuan":"Hunyuan3D-2mv","trellis":COMFY[0],"pixal":COMFY[1]}


def benchmark_settings(model,profile="quick",faces=20000,preparation=None):
    if model not in MODELS or profile not in ("quick","quality"):raise ValueError("Unknown benchmark model/profile.")
    from scripts.workbench.schema import checked_number
    faces=checked_number(faces,1,10000000,"Benchmark face budget",True)
    quick=profile=="quick"
    return {"backend":MODELS[model],"preparation":preparation or {"provider":"rembg","size":1024},
        "t_steps":15 if quick else 50,"t_guidance":7.,"t_octree":7 if quick else 9,"t_dense":6 if quick else 8,
        "t_bounds":1.25,"t_seed":42,"t_faces":faces,"t_planar":False,"t_bg":"none",
        "m_steps":15 if quick else 50,"m_octree":256 if quick else 380,"m_guidance":5.,"m_chunks":20000,
        "m_level":0.,"m_box":1.01,"m_seed":42,"m_faces":faces,"m_bake":"none","m_paint":False,
        "c_multiview":False,"c_resolution":512 if quick else 1024,"c_seed":42,
        "c_structure_steps":12,"c_shape_steps":20,"c_upsample_steps":12,"c_texture_steps":12,
        "c_guidance":7.5,"c_texture_guidance":1.,"c_texture":False,"c_texture_size":1024 if quick else 2048,
        "c_fov":20.,"c_auto_fov":True,"c_remesh":True,"c_remesh_resolution":512 if quick else 768,
        "c_remesh_qef":False,"c_faces":faces,"c_guard_bounds":5.,"c_guard_surface":2.,"c_guard_strict":False}
