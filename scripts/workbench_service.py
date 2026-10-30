"""Thin Gradio adapters over the independent workbench services."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import gradio as gr
import torch

from scripts.workbench import runtime as app
from scripts.export_contracts import load_static_master, mesh_status
from scripts.gpu_lifecycle import operation
from scripts.workbench.materials import _extract_textures
from scripts.workbench.projects import ProjectStore
from scripts.workbench.schema import SHAPE_KEYS, PAINT_KEYS, VIEWS, Preparation
from scripts.workbench.jobs import JobQueue
from scripts.workbench.preparation import prepare, composite
from PIL import Image

ROOT = app.ROOT
STATE_DIR = ROOT / app.CFG.get("paths",{}).get("workbench_runtime_dir",".runtime/workbench_preview")
RESULTS = app.OUT_DIR / "workbench_preview"
LOD_DEFAULTS = [target for _, target in app._bms_lod_targets()]
STORE = ProjectStore(ROOT / app.CFG.get("paths",{}).get("workbench_projects_dir","projects"))
QUEUE = None


def queue():
    global QUEUE
    if QUEUE is None:
        QUEUE = JobQueue(STATE_DIR / "jobs.sqlite3", STORE)
        QUEUE.start()
    return QUEUE


def save_project(project, name, source, current, settings, images):
    folder = STORE.folder(project) if project else STORE.create(name)
    STORE.snapshot(folder, settings, images, source)
    with STORE.edit(folder) as manifest:
        manifest["name"] = name or manifest["name"]
    # Saving a loaded comparison/LOD also owns its bytes; no external path is required.
    if current:
        owned = STORE.own_file(folder,current,"saved_working")
        with STORE.edit(folder) as manifest:
            working = manifest["preview"] or manifest["accepted"]
            if working and Path(current).resolve() != STORE.resolve(folder,working) and Path(current).resolve() != Path(source or current).resolve():
                manifest["preview"] = owned
    return str(folder), str(folder / "project.json"), f"Project saved, including image pixels and owned mesh: `{folder}`"


def open_project(project):
    m = STORE.load(project)
    def path(key):
        return str(STORE.resolve(project, m[key])) if m[key] else None
    images = {k: Image.open(STORE.resolve(project,v["original"])).copy() for k,v in m["inputs"].items()}
    return m, path("source"), path("preview") or path("accepted"), images


def submit(stage, project, name, source, current, settings, images, high_source=None):
    from scripts.model_manager.service import get_manager
    # Fail before saving/queuing when AI prerequisites are absent. CPU tools have
    # an empty model closure and continue to work without any checkpoints.
    try:
        resources = get_manager(ROOT,app.CFG).freeze(stage,settings,images)
    except (ValueError,OSError) as exc:
        raise gr.Error(str(exc)) from None
    if stage=="Generate":
        from scripts.workbench.input_readiness import check_inputs
        readiness=check_inputs(settings,images)
        if readiness["errors"]:raise gr.Error("Input checks: "+" ".join(readiness["errors"]))
    project, _, _ = save_project(project,name,source,current,settings,images)
    m = STORE.load(project)
    if stage in ("Optimize", "Texture", "Export", "Surface", "Scale", "Rebake") and not current:
        raise gr.Error("Open or generate a mesh first.")
    owned = STORE.own_file(project,current,"job_inputs") if current else None
    request = {"settings":settings, "images":{k:str(STORE.resolve(project,v["original"])) for k,v in m["inputs"].items()},
               "mesh":str(STORE.resolve(project,owned)) if owned else None}
    request.update(resources)
    if stage=='Rebake' and high_source:
        high_owned=STORE.own_file(project,high_source,'job_inputs')
        request['high_mesh']=high_owned
    if current:
        try:relative=Path(current).resolve().relative_to(STORE.folder(project)).as_posix()
        except ValueError:relative=None
        if relative and any(v["path"]==relative for v in m["versions"]):request["mesh_version"]=relative
    # Fail malformed settings before spending GPU time or entering the queue.
    from scripts.workbench.schema import ShapeRequest, PaintRequest, OptimizationRequest
    if stage == "Optimize":
        OptimizationRequest(**settings["optimization"])
    if stage=="Scale":
        from scripts.workbench.scaling import ScaleRequest
        ScaleRequest(**settings["scale"])
    if stage == "Generate":
        ShapeRequest.from_settings(settings["backend"], settings)
        Preparation(**settings["preparation"])
        from scripts.comfyui_workflows import BACKENDS
        if settings["backend"] in BACKENDS:
            from scripts.workbench.diagnostics import cleanup_settings
            cleanup_settings(settings)
    if stage == "Texture" or (stage == "Generate" and settings["backend"] == "Hunyuan3D-2mv" and settings.get("m_paint")):
        PaintRequest.from_settings(settings)
    job_id = queue().submit(project,stage,request)
    return project, job_id, f"**{stage} queued** · `{job_id[:10]}` · Cancel is safe at stage boundaries."


def comparison_assets(project,current,source):
    """Resolve only owned version ancestry; never substitute an unrelated raw mesh."""
    result={"result":current,"source":source,"accepted":None,"raw":None}
    if not project:return result
    m=STORE.load(project);folder=STORE.folder(project)
    if m.get("accepted"):result["accepted"]=str(STORE.resolve(folder,m["accepted"]))
    if not current:return result
    versions=m["versions"];by_path={v["path"]:v for v in versions}
    try:relative=Path(current).resolve().relative_to(folder).as_posix()
    except ValueError:return result
    visited=set()
    from scripts.workbench.projects import digest
    for _ in range(len(versions)+1):
        if relative in visited:break
        visited.add(relative);v=by_path.get(relative)
        if v is None:
            try:sha=digest(STORE.resolve(folder,relative))
            except (OSError,ValueError):break
            v=next((row for row in reversed(versions) if row.get("sha256")==sha and row["path"] not in visited),None)
        if not v:break
        candidate=Path(v["path"]).parent/"master.glb"
        if v["stage"]=="Generate" and STORE.resolve(folder,candidate,require=False).is_file():
            result["raw"]=str(STORE.resolve(folder,candidate));break
        relative=v.get("parent")
        if not relative:break
    return result


def preview_asset(project,current,source,kind):
    if kind=="result":return current
    if kind=="source":return source or current
    selected=comparison_assets(project,current,source).get(kind)
    return selected or current


def diagnostics(path,resolution):
    from scripts.workbench.diagnostics import diagnose
    if not path:raise ValueError("Open a mesh before running UV/PBR diagnostics.")
    report,images=diagnose(load_static_master(path),int(resolution))
    return report,*images


def bms_readiness(path,settings):
    from scripts.workbench.scaling import bms_readiness as inspect
    if not path:raise ValueError("Open a mesh before checking BMS readiness.")
    return inspect(load_static_master(path),settings["export"])


def comfy_host(action, settings):
    from scripts.engine_comfyui import config_from_dict, ComfyEngine, start_host, stop_host
    from scripts.comfyui_workflows import ComfyRequest, BACKENDS
    from scripts.model_manager.service import get_manager
    config = config_from_dict(get_manager(ROOT,app.CFG).runtime_configuration(app.CFG))
    if action=="plan":
        from scripts.comfyui_install import plan
        selection="trellis" if settings.get("backend")==BACKENDS[0] else "pixal-mv" if settings.get("c_multiview") else "pixal"
        return plan(config,selection)
    if action == "start":
        start_host(config)
    elif action == "stop":
        return {"message":stop_host(config)}
    if settings.get("backend") not in BACKENDS:
        settings = {**settings,"backend":BACKENDS[0]}
    return ComfyEngine(config).readiness(ComfyRequest.from_settings(settings))


def queue_benchmark(name,settings,images,models,profile,faces):
    """Validate all selections before creating isolated comparison projects."""
    from scripts.workbench.benchmarking import MODELS,benchmark_settings
    from scripts.workbench.input_readiness import check_inputs
    if not models or len(set(models))!=len(models):raise ValueError("Select at least one unique benchmark model.")
    runs=[]
    for model in models:
        selected=benchmark_settings(model,profile,faces,settings.get("preparation"))
        checks=check_inputs(selected,images)
        if checks["errors"]:raise ValueError(MODELS[model]+": "+" ".join(checks["errors"]))
        runs.append((model,selected,checks))
    result=[]
    for model,selected,checks in runs:
        folder=STORE.create(f"{name}_compare_{model}")
        manifest=STORE.snapshot(folder,selected,images)
        request={"settings":selected,"images":{k:str(STORE.resolve(folder,v["original"])) for k,v in manifest["inputs"].items()},
                 "mesh":None,"benchmark":{"profile":profile,"seed":42,"quality_review":"Manual review pending"}}
        job=queue().submit(folder,"Generate",request)
        result.append({"model":MODELS[model],"project":str(folder),"job_id":job,"input_checks":checks})
    return result,f"Queued {len(result)} generator comparisons in separate saved projects. Seed 42; shape only; same preparation and face target. Open each project to review accuracy."


@operation()
def prepared_preview(which, images, settings):
    direction = which.lower()
    prepared, mask, report = prepare(images.get(direction), Preparation(**settings), ROOT, app.CFG)
    return composite(prepared, settings["background"]), mask, json.dumps(report,indent=2)


def assets():
    paths = []
    for folder in (app.OUT_DIR, app.BMS_DIR):
        # One asset-directory level plus enhanced masters, never model caches/vendor.
        paths.extend(folder.glob("*/*.glb"))
        paths.extend(folder.glob("*/enhanced/*.glb"))
    paths.extend(RESULTS.glob("*/*.glb"))
    return [(str(p.relative_to(ROOT)), str(p.resolve())) for p in sorted(set(paths))]


def default_asset():
    candidate = app.BMS_DIR / "residential_5" / "Model_0.glb"
    return str(candidate.resolve()) if candidate.exists() else (assets()[0][1] if assets() else None)


def telemetry():
    disk_free=shutil.disk_usage(ROOT).free/1024**3
    disk = f" · Disk {disk_free:.1f} GiB free" + (" — LOW DISK SPACE" if disk_free<5 else "")
    if not torch.cuda.is_available():
        return "**CPU mode** · Shape fallback is slow. PBR paint requires NVIDIA CUDA. AMD/Intel GPUs are not wired."+disk
    free, total = torch.cuda.mem_get_info()
    gib = 1024 ** 3
    worker=""
    if QUEUE is not None:
        active=next((r for r in QUEUE.rows() if r["state"] in ("running","cancel_pending")),None)
        if active:
            path=STORE.folder(active["project"])/"logs"/(active["id"]+".memory.json")
            if path.exists():
                try:
                    memory=json.loads(path.read_text(encoding="utf-8"))
                    if memory.get("comfy_host"):
                        live=memory["comfy_host"];devices=live.get("host_stats",{}).get("devices",[])
                        allocated=sum(d.get("torch_vram_total",0)-d.get("torch_vram_free",0) for d in devices)
                        worker=f" · Comfy host allocated {allocated/gib:.2f} GiB / sampled peak {live.get('sampled_peak_host_torch_allocated_bytes',0)/gib:.2f} GiB"
                    else:worker=f" · Worker allocated {memory.get('torch_allocated_bytes',0)/gib:.2f} GiB / peak {memory.get('torch_peak_allocated_bytes',0)/gib:.2f} GiB"
                except (OSError,ValueError):pass
    return (f"**{torch.cuda.get_device_name()}** · Device free {free/gib:.1f} / {total/gib:.1f} GiB"+worker+disk)


def inspect_asset(path):
    if not path:
        return "Choose a project mesh or upload a GLB.", {}, [], None
    path = str(Path(path).resolve())
    mesh = load_static_master(path)
    status = mesh_status(mesh)
    status.update(path=path, size_bytes=Path(path).stat().st_size)
    maps = _extract_textures(mesh)
    gallery = []
    for key, image in maps.items():
        gallery.append((image, f"{key} · {image.width} × {image.height}"))
        if key == "metallic_roughness":
            rgb = image.convert("RGB")
            gallery.extend([(rgb.getchannel("G"), "Roughness · G channel"),
                            (rgb.getchannel("B"), "Metallic · B channel")])
    summary = (f"### {Path(path).stem}\n"
               f"**{status['triangles']:,} triangles** · {status['vertices']:,} vertices · "
               f"{status['size_bytes']/1048576:.2f} MiB\n\n"
               f"UVs: **{'valid' if status['uv_valid'] else 'missing / invalid'}** · "
               f"Watertight: **{'yes' if status['watertight'] else 'no'}** · "
               f"Connected components: **{status['components']}**\n\n"
               f"Embedded maps: {', '.join(maps) or 'none'}\n\n`{path}`")
    return summary, status, gallery, path


def _channel_images(path):
    if not path:
        return {}
    maps = _extract_textures(load_static_master(path))
    if "metallic_roughness" in maps:
        packed = maps["metallic_roughness"].convert("RGB")
        maps["roughness"] = packed.getchannel("G")
        maps["metallic"] = packed.getchannel("B")
    return maps


def texture_choices(path):
    return list(_channel_images(path))


def texture_preview(path, channel):
    image = _channel_images(path).get(channel)
    if image is None:
        return None, "This asset has no image for the selected channel."
    return image, (f"**{channel}** · {image.width:,} × {image.height:,} px · mode **{image.mode}**\n\n"
                   "Extracted from the working GLB; this inspector does not modify its textures.")


