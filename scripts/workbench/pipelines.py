"""UI-independent, serialized operations. All outputs are private job artifacts."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json
from PIL import Image
from scripts.gpu_lifecycle import operation
from scripts.export_contracts import load_static_master, mesh_status
from . import runtime
from .schema import Preparation, ShapeRequest, PaintRequest, OptimizationRequest, VIEWS
from .preparation import prepare, composite
from .projects import atomic_json


def paint_mesh(path, reference, request, output, checkpoint):
    from scripts.engine_paint import Hunyuan3DPainter, PaintConfig, rasterizer_ready
    if not rasterizer_ready():
        raise RuntimeError("PBR paint requires the compiled NVIDIA CUDA rasterizer.")
    checkpoint("Loading paint model", .48)
    painter = Hunyuan3DPainter(PaintConfig(max_num_view=request.views, resolution=request.resolution,
        use_remesh=request.remesh, render_size=request.render_size, texture_size=request.texture_size,
        bake_exp=request.exponent, merge_method=request.merge, save_separate_maps=request.maps,
        low_vram_mode=request.low_vram,
        safe_cpu_checkpoint_io=runtime.CFG.get("model",{}).get("paint",{}).get("safe_cpu_checkpoint_io",True)))
    painter.load()
    checkpoint("Painting PBR channels", .55)
    painter.paint(str(path), composite(reference), str(output))
    report = {"requested":asdict(request), "mmgp_active":painter.last_mmgp_applied,
              "effective_baking_views":painter.last_view_count,"export_atlas_downsample_factor":2,
              "windows_safe_checkpoint_io":painter.cfg.safe_cpu_checkpoint_io,"warnings":list(painter.load_warnings)}
    painter.unload()
    checkpoint("Normal map", .85)
    if request.normal != "off":
        from .normals import _embed_normal_map_in_glb
        normal = _embed_normal_map_in_glb(output, request.normal)
        detail = output.with_suffix(".normal_bake.json")
        report["normal"] = json.loads(detail.read_text()) if detail.exists() else {"requested":request.normal,"actual":"skipped or failed"}
        if normal is None:
            report["warnings"].append("Normal bake skipped, already present, or failed; inspect the resulting maps.")
    return report


@operation()
def execute(stage, request, folder, checkpoint):
    """Execute a frozen request; caller publishes only after the final checkpoint."""
    from scripts.lod_export import make_lod_set, make_textured_lod_set
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    settings = request["settings"]
    checkpoint("Validating immutable inputs", .02)
    report = {"stage":stage, "requested":settings, "warnings":[]}
    report["model_configuration"]=runtime.CFG.get("model",{})
    source = request.get("mesh")
    if source:
        report["source_inspection"] = mesh_status(load_static_master(source))
        atomic_json(folder / "source_inspection.json", report["source_inspection"])
        print("[Workbench] Source inspection:", json.dumps(report["source_inspection"]), flush=True)
    output = folder / "asset.glb"
    from scripts.comfyui_workflows import BACKENDS, ComfyRequest
    chained = False
    shape = None
    if stage=="Generate":
        from .input_readiness import check_inputs
        report["input_readiness"]=check_inputs(settings,request.get("images",{}))
        if report["input_readiness"]["errors"]:raise ValueError("Input checks: "+" ".join(report["input_readiness"]["errors"]))
        report["warnings"].extend(report["input_readiness"]["warnings"])
    if stage == "Generate" and settings["backend"] in BACKENDS:
        from scripts.engine_comfyui import engine_from_config
        shape = ComfyRequest.from_settings(settings)
        from .diagnostics import cleanup_settings
        bounds_limit,surface_limit,guard_strict=cleanup_settings(settings)
        prep = Preparation(**settings.get("preparation",{}))
        directions = VIEWS if shape.multiview else ("front",)
        views = {}
        input_sizes = set()
        if shape.multiview and prep.crop.strip():
            raise ValueError("Pixal3D fixed-orbit multiview requires matched framing; individual crop is disabled. Prepare aligned views first.")
        for direction in directions:
            path = request.get("images",{}).get(direction)
            if not path:
                continue
            checkpoint(f"Preparing {direction} for ComfyUI",.06)
            with Image.open(path) as original:
                input_sizes.add(original.size)
                image,mask,info = prepare(original,prep,runtime.ROOT,runtime.CFG)
            image.save(folder/f"{direction}_prepared.png")
            mask.save(folder/f"{direction}_mask.png")
            views[direction] = composite(image,"black")
            report.setdefault("preparation",{})[direction] = info
        if shape.multiview and len(input_sizes)>1:
            raise ValueError("Pixal3D multiview requires equally sized, consistently framed views; align the originals before generating.")
        output,report["comfyui"] = engine_from_config(runtime.CFG).generate(views,shape,folder,checkpoint)
        report["warnings"].extend(report["comfyui"].get("warnings",[]))
        if shape.multiview:
            report["warnings"].append("Pixal3D uses a fixed 90-degree orbit and shared FOV, not estimated arbitrary photo poses. Verify framing, proportions and dimensions.")
        report["warnings"].append("ComfyUI master.glb retains decoded geometry. Asset scale is normalized; set measured dimensions before BMS export.")
        if shape.remesh or shape.faces:
            report["warnings"].append("Working-mesh cleanup changes geometry/topology; compare thin parts and openings against the retained raw master and reference images.")
            from .optimization import bounds_change_percent,surface_error_metrics
            master=load_static_master(folder/"master.glb");working=load_static_master(output)
            guard={"bounds_change_percent":bounds_change_percent(master,working),"bounds_limit_percent":bounds_limit,"surface_limit_percent":surface_limit,
                "strict":guard_strict,"warnings":[]}
            try:guard["surface_error"]=surface_error_metrics(master,working,samples=256)
            except (ModuleNotFoundError,MemoryError) as exc:
                guard["surface_error"]={"unavailable":str(exc)};guard["warnings"].append("Sampled surface comparison unavailable; no accuracy claim can be made.")
            if guard["bounds_change_percent"]>bounds_limit:guard["warnings"].append("Cleanup exceeds the selected bounds-change limit.")
            if guard["surface_error"].get("max_percent",0)>surface_limit:guard["warnings"].append("Cleanup exceeds the selected sampled surface-error limit; inspect thin parts and openings.")
            atomic_json(folder/"cleanup_comparison.json",guard);report["cleanup_comparison"]=guard
            if guard["strict"] and guard["warnings"]:raise ValueError(" ".join(guard["warnings"])+" No preview published; raw master retained.")
            report["warnings"].extend(guard["warnings"])
            del master,working
    elif stage == "Generate":
        shape = ShapeRequest.from_settings(settings["backend"], settings)
        prep = Preparation(**settings.get("preparation", {}))
        views = {}
        for direction in (("front",) if shape.backend == "TripoSG 1.5B" else VIEWS):
            path = request["images"].get(direction)
            if path:
                checkpoint(f"Preparing {direction}", .08)
                with Image.open(path) as original:
                    image, mask, info = prepare(original, prep, runtime.ROOT, runtime.CFG)
                views[direction] = image
                image.save(folder / f"{direction}_prepared.png")
                mask.save(folder / f"{direction}_mask.png")
                report.setdefault("preparation", {})[direction] = info
        if not views or (shape.backend == "TripoSG 1.5B" and "front" not in views):
            raise ValueError("Upload at least one valid view; TripoSG requires the single input image.")
        engine = runtime.shape_engine(shape.backend == "TripoSG 1.5B")
        from scripts.gpu_lifecycle import register
        register(engine)  # Cached engines must also be cleaned up after failed runs.
        checkpoint("Shape diffusion and surface extraction", .2)
        if shape.backend == "TripoSG 1.5B":
            mesh = engine.generate(composite(views["front"]), seed=shape.seed, num_inference_steps=shape.steps,
                guidance_scale=shape.guidance, faces=-1, octree_depth=shape.octree,
                dense_octree_depth=shape.dense, bounds=shape.bounds, remove_background=False, rmbg_backend="none")
            report["effective_dense_depth"] = min(shape.dense, shape.octree)
        else:
            mesh = engine.generate_multiview(views, seed=shape.seed, num_inference_steps=shape.steps,
                octree_resolution=shape.octree, num_chunks=shape.chunks, guidance_scale=shape.guidance,
                mc_level=shape.level, box_v=shape.box_v, preprocessed=True)
        engine.unload()
        mesh.export(folder/"master.glb")
        report["warnings"].append("master.glb preserves decoded geometry before decimation, planar projection or paint. Compare thin details against it.")
        checkpoint("Shape complete; releasing GPU ownership", .43)
        chained = settings.get("m_paint", False) and shape.backend != "TripoSG 1.5B"
        if not chained:
            from scripts.engine import decimate, export_glb_and_obj
            from scripts.texture import planar_project_front
            if shape.faces > 0:
                mesh = decimate(mesh, shape.faces)
            if shape.bake_view != "none":
                selected = shape.bake_view if shape.bake_view in views else next(iter(views))
                axes = {"front":"+z", "left":"-x", "back":"-z", "right":"+x"}
                mesh = planar_project_front(mesh, composite(views[selected]), front_axis=axes[selected])
                report["projection_view"] = selected
            export_glb_and_obj(mesh, output)
        else:
            white = folder / "white.glb"
            mesh.export(white)
            report["paint"] = paint_mesh(white, views.get("front", next(iter(views.values()))),
                                        PaintRequest.from_settings(settings), output, checkpoint)
    elif stage=='Rebake':
        from .uv_rebake import rebake
        if not source:raise ValueError('Load a target mesh before UV repair/rebaking.')
        high=load_static_master(request.get('high_mesh') or source)
        report['high_source_inspection']=mesh_status(high)
        target=load_static_master(source)
        rebuilt,detail=rebake(target,high,checkpoint=checkpoint,**settings['rebake'])
        rebuilt.export(output)
        reloaded=load_static_master(output)
        import numpy as np
        if len(reloaded.faces)!=len(target.faces) or not np.allclose(reloaded.bounds,target.bounds,atol=1e-5):
            raise ValueError('UV repair changed geometry bounds or triangle count during serialization.')
        from .materials import _extract_textures
        if set(detail['maps'])-set(_extract_textures(reloaded)):
            raise ValueError('GLB round-trip lost a rebaked map.')
        report['rebake']=detail;report['warnings'].extend(detail['warnings'])
    elif stage=="Scale":
        from .scaling import ScaleRequest,scale_mesh
        from .optimization import assert_material_preserved
        scale_request=ScaleRequest(**settings["scale"])
        master=load_static_master(source);scaled,report["scale"]=scale_mesh(master,scale_request)
        scaled.export(output);reloaded=load_static_master(output)
        import numpy as np
        if not np.allclose(np.ptp(reloaded.bounds,axis=0),report["scale"]["dimensions_metres"],rtol=1e-5,atol=1e-6):raise ValueError("GLB round-trip changed measured scale; no preview published.")
        if len(reloaded.faces)!=len(master.faces):raise ValueError("Scaling changed triangle count; no preview published.")
        assert_material_preserved(master,reloaded)
        report["warnings"].append("Scaled working copy uses metres, Y-up and +Z forward. Accuracy depends on your supplied measurement.")
    elif stage == "Texture":
        if not source or not request["images"].get("reference"):
            raise ValueError("Load a mesh and upload a texture reference first.")
        with Image.open(request["images"]["reference"]) as reference:
            report["paint"] = paint_mesh(source, reference, PaintRequest.from_settings(settings), output, checkpoint)
    elif stage in ("Optimize", "Export"):
        if not source:
            raise ValueError("Load or generate a mesh first.")
        checkpoint("UV-aware decimation and export", .15)
        if stage == "Optimize":
            import numpy as np
            from .optimization import optimize_mesh, assert_material_preserved, bounds_change_percent, surface_error_metrics
            request_settings = OptimizationRequest(**settings["optimization"])
            master = load_static_master(source)
            optimized, optimization_report = optimize_mesh(master, request_settings, checkpoint)
            # The job folder remains private until every check passes. Serialize
            # without a second decimation; the report retains the user's target.
            targets = [("Model_0", max(request_settings.target, len(optimized.faces)))]
            result = make_lod_set(optimized, "lods", targets, folder, normal_baker="off")
            reloaded = load_static_master(result / "Model_0.glb")
            serialized_status = mesh_status(reloaded)
            if len(reloaded.faces) != len(optimized.faces):
                raise ValueError("GLB round-trip changed the optimized triangle count; no preview published.")
            if optimization_report.get('protected_faces'):
                from .protection import selected_faces
                protected=master.triangles[selected_faces(master,request_settings)]
                if not np.array_equal(reloaded.triangles[:len(protected)].astype('float32'),protected.astype('float32')):
                    raise ValueError('GLB round-trip changed protected triangle positions/winding.')
                optimization_report['protected_roundtrip_float32_exact']=True
            if optimization_report["result"]["uv_valid"] and not serialized_status["uv_valid"]:
                raise ValueError("GLB round-trip lost valid UVs; no preview published.")
            if not optimization_report["uv_fallback"]:
                assert_material_preserved(master, reloaded)
            serialized_shift = bounds_change_percent(master,reloaded)
            if serialized_shift > request_settings.max_bounds_change + 1e-5:
                raise ValueError("GLB round-trip exceeds the optimization bounds limit; no preview published.")
            if request_settings.repair_winding and not reloaded.is_winding_consistent:
                raise ValueError("GLB round-trip lost consistent winding; no preview published.")
            optimization_report["result"] = serialized_status
            optimization_report["bounds_change_percent"] = serialized_shift
            serialized_surface = surface_error_metrics(master,reloaded)
            if serialized_surface["max_percent"] > request_settings.max_surface_error + 1e-5:
                raise ValueError("GLB round-trip exceeds the sampled surface-error limit; no preview published.")
            optimization_report["surface_error"] = serialized_surface
            report["optimization"] = optimization_report
            report["warnings"].extend(optimization_report["warnings"])
            atomic_json(result / "optimization_report.json", optimization_report)
            lod_report = json.loads((result / "lod_report.json").read_text())
            lod_report["source"] = str(source)
            lod_report["master"] = report["source_inspection"]
            lod_report["levels"][0].update(target_faces=request_settings.target,
                master_no_op=len(reloaded.faces)==len(master.faces),
                uv_method=optimization_report["uv_method"],uv_fallback=optimization_report["uv_fallback"])
            atomic_json(result / "lod_report.json", lod_report)
        else:
            s = settings["export"]
            targets = runtime._build_lod_targets(s["count"], *s["budgets"])
            if s["shared"]:
                result = make_textured_lod_set(source, "lods", targets, folder, normal_baker=settings["normal"])
            else:
                result = make_lod_set(load_static_master(source), "lods", targets, folder, normal_baker=settings["normal"])
        output = result / "Model_0.glb"
        report["lods"] = json.loads((result / "lod_report.json").read_text())
        if stage == "Export" and settings["export"].get("distances"):
            from .schema import checked_number
            distances = [checked_number(v,1,10000000,"LOD distance",True) for v in settings["export"]["distances"][:len(targets)]]
            if len(distances)!=len(targets) or any(a>=b for a,b in zip(distances,distances[1:])):
                raise ValueError("LOD distances must be positive, increasing and match the selected level count.")
            parent = result / "bms_template" / "Parent.dat"
            if parent.exists():
                lines=parent.read_text(encoding="utf-8").splitlines()
                index=0
                for i,line in enumerate(lines):
                    if line.startswith("AddLOD"):
                        lines[i]=f"AddLOD      = {targets[index][0]}.bml {distances[index]}";index+=1
                parent.write_text("\n".join(lines)+"\n",encoding="utf-8")
            atomic_json(result / "lod_distances.json",{"distances_ft":distances,"metres_per_mesh_unit":settings["export"].get("metres_per_unit",1),
                "note":"Planning distances only. Parent dimensions and final mesh scale still require measurement in Blender/3ds Max before BMS."})
        if stage=="Export":
            from .export_package import build_package
            report['package']=build_package(result,settings)
            report['warnings'].extend(report['package']['warnings'])
            from .scaling import bms_readiness
            report["bms_readiness"]=bms_readiness(load_static_master(output),settings["export"])
            atomic_json(result/"bms_readiness.json",report["bms_readiness"])
    elif stage == "Surface":
        import argparse
        from scripts.enhance_model import enhance
        from scripts.lod_export import _extract_textures
        staged = folder / "input"
        staged.mkdir()
        mesh = load_static_master(source)
        maps = _extract_textures(mesh)
        for key in ("albedo", "metallic_roughness"):
            if key not in maps:
                raise ValueError(f"Surface enhancement requires UVs and a {key} image.")
            maps[key].save(staged / f"{key}.png")
        mesh.export(staged / "master.glb")
        s = settings["surface"]
        checkpoint("Surface enhancement / normal / AO / ARMW", .2)
        destination = folder / "enhanced"
        enhance(argparse.Namespace(input=staged / "master.glb", output=destination,
            resolution=int(s["resolution"]), normal=s["normal"], delight_strength=s["delight"],
            ao_rays=int(s["rays"]), up_axis=s["axis"], material_name=s["material"], armw=s["armw"],
            mesh_mode=s["mode"], target_faces=int(s["target"])))
        candidates = list(destination.glob("*.glb"))
        if len(candidates) != 1:
            raise RuntimeError("Enhancement did not produce exactly one GLB.")
        output = candidates[0]
    else:
        raise ValueError(f"Unknown stage: {stage}")
    checkpoint("Validating output", .95)
    report["result_inspection"] = mesh_status(load_static_master(output))
    if stage == "Generate" and not chained and hasattr(shape,"faces") and shape.faces > 0:
        achieved = report["result_inspection"]["triangles"]
        report["requested_shape_faces"] = shape.faces
        if achieved > shape.faces:
            report["warnings"].append(f"Shape: {achieved} achieved / {shape.faces} requested; target not reached.")
    if not report["result_inspection"]["winding_consistent"]:
        report["warnings"].append("Mesh winding is inconsistent; inspect face orientation and normals before export.")
    from scripts.lod_export import _extract_textures
    report["effective_texture_sizes"] = {key:list(image.size) for key,image in _extract_textures(load_static_master(output)).items()}
    if stage == "Generate" and isinstance(shape,ComfyRequest) and shape.texture:
        state = report["result_inspection"]
        if not state["uv_valid"] or not {"baseColorTexture","metallicRoughnessTexture"}.issubset(state["textures"]):
            raise ValueError("ComfyUI PBR output is missing UVs or base-color/metallic-roughness maps; no preview published.")
    report["warnings"].extend(report.get("paint",{}).get("warnings",[]))
    for level in report.get("lods",{}).get("levels",[]):
        if stage != "Optimize" and level["achieved_faces"]>level["target_faces"]:
            report["warnings"].append(f"{level['lod']}: {level['achieved_faces']} achieved / {level['target_faces']} requested; target not reached.")
        if level.get("uv_fallback"):
            report["warnings"].append(f"{level['lod']}: UV fallback {level['uv_fallback']}")
    atomic_json(folder / "operation.json", report)
    return output, report
