"""Workbench persistence, cancellation, preparation and real mesh round trips."""
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock
import numpy as np
import trimesh
from PIL import Image, ImageChops
from scripts.workbench.projects import ProjectStore, digest
from scripts.workbench.schema import Preparation, ShapeRequest
from scripts.workbench.preparation import prepare
from scripts.workbench.jobs import JobQueue
from scripts.workbench import viewer

def fixture(path):
    mesh=trimesh.creation.icosphere(subdivisions=2)
    mesh.visual=trimesh.visual.TextureVisuals(uv=(mesh.vertices[:,:2]+1)/2,
        material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.new("RGB",(16,16),(100,160,190)),
            metallicRoughnessTexture=Image.new("RGB",(16,16),(250,80,30))))
    mesh.export(path)
    return mesh

class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=ProjectStore(self.root/"projects");self.project=self.store.create("Test asset")
        self.source=self.root/"master.glb";self.mesh=fixture(self.source)
        self.image=Image.new("RGBA",(64,32),(255,80,40,128))
    def tearDown(self):self.temp.cleanup()

    def test_saved_project_owns_images_mesh_and_clears_views(self):
        m=self.store.snapshot(self.project,{"backend":"Hunyuan3D-2mv"},{"front":self.image,"left":self.image},self.source)
        self.source.unlink()
        restored=Image.open(self.store.resolve(self.project,m["inputs"]["front"]["original"]))
        self.assertIsNone(ImageChops.difference(restored,self.image).getbbox())
        self.assertTrue(self.store.resolve(self.project,m["source"]).exists())
        self.assertNotIn("left",self.store.snapshot(self.project,{}, {"left":None})["inputs"])

    def test_paths_cannot_escape_and_texture_changes_preserve_geometry_state(self):
        with self.assertRaises(ValueError):self.store.resolve(self.project,"../../master.glb")
        self.store.snapshot(self.project,{"normal":"off"},{},self.source)
        with self.store.edit(self.project) as m:
            m["stage_states"]={k:"accepted" for k in ("Inputs","Generate","Texture","Optimize","Export")}
        m=self.store.snapshot(self.project,{"normal":"low"},{})
        self.assertEqual(m["stage_states"]["Generate"],"accepted")
        self.assertIn("stale",m["stage_states"]["Texture"])

    def test_replacing_texture_reference_preserves_accepted_geometry_state(self):
        self.store.snapshot(self.project,{}, {"reference":self.image},self.source)
        with self.store.edit(self.project) as m:m["stage_states"]={k:"accepted" for k in ("Generate","Texture","Surface","Optimize","Export")}
        m=self.store.snapshot(self.project,{}, {"reference":Image.new("RGBA",(64,32),"blue")})
        self.assertEqual(m["stage_states"]["Generate"],"accepted")
        self.assertIn("stale",m["stage_states"]["Texture"])

    def test_accept_discard_preserve_master_and_versions(self):
        before=digest(self.source);m=self.store.snapshot(self.project,{}, {},self.source)
        candidate=self.project/"candidate.glb";self.mesh.export(candidate)
        self.store.add_version(self.project,candidate,"Optimize","job",{})
        self.assertEqual(self.store.load(self.project)["accepted"],m["source"])
        self.store.accept(self.project,"Approved")
        self.assertEqual(self.store.load(self.project)["accepted"],"candidate.glb")
        self.store.discard(self.project)
        self.assertTrue(candidate.exists());self.assertEqual(before,digest(self.source))

    def test_preparation_keeps_alpha_and_validates_crop(self):
        result,mask,report=prepare(self.image,Preparation(size=256,margin=0),self.root,{})
        self.assertEqual(result.size,(256,256));self.assertLess(mask.getextrema()[0],255)
        self.assertEqual(report["actual"],"preserved alpha")
        with self.assertRaises(ValueError):prepare(self.image,Preparation(crop="10,0,2,5"),self.root,{})
        with self.assertRaises(ValueError):Preparation(provider="none",alpha_matting=True)

    def test_cancel_at_safe_boundary_does_not_publish_partial_result(self):
        def executor(stage,request,folder,checkpoint):
            folder.mkdir(parents=True);output=folder/"asset.glb";self.mesh.export(output)
            q.cancel(job);checkpoint("after operation",.9)
            return output,{}
        q=JobQueue(self.root/"jobs.sqlite3",self.store,executor)
        job=q.submit(self.project,"Optimize",{"settings":{}})
        q.update(job,state="running");q.run(q.get(job))
        self.assertEqual(q.get(job)["state"],"cancelled")
        self.assertIsNone(self.store.load(self.project)["preview"])
        self.assertEqual(JobQueue(q.path,self.store).get(job)["state"],"cancelled")
        queued=q.submit(self.project,"Optimize",{});q.cancel(queued)
        self.assertEqual(q.get(queued)["state"],"cancelled")

    def test_completed_job_publishes_owned_preview_and_log(self):
        def executor(stage,request,folder,checkpoint):
            folder.mkdir(parents=True);output=folder/"asset.glb";self.mesh.export(output)
            checkpoint("validate",.95);return output,{"warnings":[]}
        q=JobQueue(self.root/"jobs.sqlite3",self.store,executor)
        job=q.submit(self.project,"Optimize",{"settings":{}});q.run(q.get(job))
        self.assertEqual(q.get(job)["state"],"completed")
        self.assertEqual(self.store.load(self.project)["preview"],f"jobs/{job}/asset.glb")
        self.assertTrue((self.project/"logs"/(job+".jsonl")).exists())

    def test_completed_job_keeps_quality_warnings_visible_and_in_history(self):
        warning="Shape: 320 achieved / 120 requested; target not reached."
        def executor(stage,request,folder,checkpoint):
            folder.mkdir(parents=True);output=folder/"asset.glb";self.mesh.export(output)
            return output,{"warnings":[warning]}
        q=JobQueue(self.root/"jobs.sqlite3",self.store,executor)
        job=q.submit(self.project,"Optimize",{});q.run(q.get(job))
        self.assertEqual(q.get(job)["state"],"completed")
        self.assertIn("Warnings: "+warning,q.get(job)["message"])
        self.assertEqual(self.store.load(self.project)["versions"][-1]["warnings"],[warning])

    def test_channel_view_and_uv_atlas_preserve_original_maps(self):
        before=digest(self.source)
        with patch.object(viewer,"CACHE",self.root/"viewer"):path=viewer.derived(self.source,"Roughness")
        loaded=trimesh.load(path,force="mesh",process=False)
        self.assertTrue(np.all(np.array(loaded.visual.material.baseColorTexture.convert("RGB"))==80))
        atlas,caption=viewer.uv_atlas(self.source)
        self.assertEqual(atlas.size,(1024,1024));self.assertIn("320 faces",caption)
        self.assertEqual(digest(self.source),before)

    def test_queue_and_results_survive_moving_the_entire_bundle(self):
        def executor(stage,request,folder,checkpoint):
            folder.mkdir(parents=True);output=folder/"asset.glb";self.mesh.export(output)
            return output,{}
        q=JobQueue(self.root/"queue/jobs.sqlite3",self.store,executor)
        completed=q.submit(self.project,"Optimize",{});q.run(q.get(completed))
        queued=q.submit(self.project,"Optimize",{})
        with q.connect() as db:
            stored=dict(db.execute("SELECT * FROM jobs WHERE id=?",(completed,)).fetchone())
        self.assertEqual(stored["project"],self.project.name)
        self.assertEqual(stored["result"],f"jobs/{completed}/asset.glb")
        moved=self.root/"Moved App with Spaces";moved.mkdir()
        shutil.move(str(self.store.root),moved/"projects")
        shutil.move(str(q.path.parent),moved/"queue")
        new_store=ProjectStore(moved/"projects")
        new_queue=JobQueue(moved/"queue/jobs.sqlite3",new_store,executor)
        self.assertTrue(Path(new_queue.get(completed)["result"]).is_file())
        new_queue.run(new_queue.get(queued))
        self.assertEqual(new_queue.get(queued)["state"],"completed")
        self.assertEqual(len(new_queue.rows(moved/"projects"/self.project.name)),2)

    def test_legacy_absolute_queue_paths_migrate_after_relocation(self):
        q=JobQueue(self.root/"jobs.sqlite3",self.store)
        job=q.submit(self.project,"Optimize",{})
        result=self.project/"old.glb";self.mesh.export(result)
        with q.connect() as db:
            db.execute("UPDATE jobs SET project=?,result=? WHERE id=?",(str(self.project),str(result),job))
        moved=self.root/"Relocated Projects"
        shutil.move(str(self.store.root),moved)
        new_queue=JobQueue(q.path,ProjectStore(moved))
        self.assertEqual(Path(new_queue.get(job)["project"]),(moved/self.project.name).resolve())
        self.assertEqual(Path(new_queue.get(job)["result"]),(moved/self.project.name/"old.glb").resolve())

    def test_real_optimization_preserves_uv_maps_and_source(self):
        from scripts.workbench.pipelines import execute
        before=digest(self.source)
        output,report=execute("Optimize",{"mesh":str(self.source),"settings":{"optimization":{"target":120}}},
                              self.project/"optimization",lambda *args:None)
        self.assertLess(report["result_inspection"]["triangles"],len(self.mesh.faces))
        self.assertTrue(report["result_inspection"]["uv_valid"])
        self.assertEqual(set(report["source_inspection"]["textures"]),set(report["result_inspection"]["textures"]))
        self.assertEqual(before,digest(self.source));self.assertTrue(output.exists())

    def test_generation_reports_unmet_face_budget_and_inconsistent_winding(self):
        from scripts.workbench.pipelines import execute
        mesh=self.mesh.copy();mesh.faces[0]=mesh.faces[0][::-1]
        engine=Mock();engine.generate.return_value=mesh
        image=self.root/"front.png";self.image.save(image)
        settings={"backend":"TripoSG 1.5B","t_steps":25,"t_guidance":7,"t_seed":42,"t_octree":8,
                  "t_faces":120,"t_planar":False,"preparation":{"provider":"none"}}
        with patch("scripts.workbench.runtime.shape_engine",return_value=engine),patch("scripts.engine.decimate",side_effect=lambda mesh,target:mesh.copy()):
            output,report=execute("Generate",{"settings":settings,"images":{"front":str(image)}},
                                  self.project/"generate",lambda *args:None)
        self.assertEqual(report["result_inspection"]["triangles"],320)
        self.assertTrue(any("320 achieved / 120 requested" in warning for warning in report["warnings"]))
        self.assertTrue(any("winding" in warning for warning in report["warnings"]))
        self.assertTrue(output.is_file())
        self.assertTrue((output.parent/"master.glb").is_file())
        self.assertEqual(engine.generate.call_args.kwargs["faces"],-1)

    def test_hunyuan_prepared_input_bypasses_hidden_remover(self):
        from scripts.engine_hunyuan import HunyuanMVEngine,HunyuanConfig
        engine=HunyuanMVEngine(HunyuanConfig());captured={}
        def pipe(**kwargs):captured.update(kwargs);return [self.mesh]
        engine._pipe=pipe
        with patch.object(engine,"load"),patch.object(engine,"_prep_view",side_effect=AssertionError("hidden remover")):
            engine.generate_multiview({"left":self.image.convert("RGB")},preprocessed=True)
        self.assertEqual(list(captured["image"]),["left"])
        self.assertEqual(captured["image"]["left"].mode,"RGBA")

    def test_numeric_contract_rejects_fractional_and_nonfinite(self):
        with self.assertRaises(ValueError):ShapeRequest(steps=30.5)
        with self.assertRaises(ValueError):ShapeRequest(guidance=float("nan"))

    def test_windows_numpy_checkpoint_reader_preserves_tensor_values(self):
        import torch
        from safetensors.torch import save_file
        from scripts.checkpoint_io import numpy_checkpoint
        path=self.root/"dinov2.safetensors"
        original={"float":torch.arange(20,dtype=torch.float32).reshape(4,5),"half":torch.ones(3,dtype=torch.float16)}
        save_file(original,path)
        actual=numpy_checkpoint(path)
        for key in original:self.assertTrue(torch.equal(original[key],actual[key]))

    def test_checkpoint_loader_scope_restores_transformers_after_failure(self):
        import transformers.modeling_utils as module
        from scripts.checkpoint_io import windows_dino_checkpoint_io
        original=module.safe_load_file
        with self.assertRaisesRegex(RuntimeError,"partial load"):
            with patch("scripts.checkpoint_io.sys.platform","win32"),windows_dino_checkpoint_io():
                self.assertIsNot(module.safe_load_file,original)
                raise RuntimeError("partial load")
        self.assertIs(module.safe_load_file,original)

    def test_additional_png_maps_use_real_packed_channels(self):
        from scripts.engine_paint import _save_png_maps
        paths=_save_png_maps(self.mesh,self.root/"asset.glb")
        self.assertEqual(len(paths),4)
        with Image.open(self.root/"asset_roughness.png") as image:self.assertTrue(np.all(np.asarray(image)==80))
        with Image.open(self.root/"asset_metallic.png") as image:self.assertTrue(np.all(np.asarray(image)==30))

    def test_initialization_restores_default_dtype_after_partial_failure(self):
        import torch
        from scripts.engine_hunyuan import HunyuanMVEngine,HunyuanConfig,Hunyuan3DDiTFlowMatchingPipeline
        previous=torch.get_default_dtype()
        with patch("scripts.engine_hunyuan._load_low_memory",side_effect=RuntimeError("partial load")):
            with self.assertRaisesRegex(RuntimeError,"partial load"):
                HunyuanMVEngine(HunyuanConfig()).load(background=False)
        self.assertEqual(torch.get_default_dtype(),previous)

    def test_missing_frozen_input_is_a_failed_job_without_stopping_dispatch(self):
        q=JobQueue(self.root/"jobs.sqlite3",self.store,lambda *args:None)
        job=q.submit(self.project,"Texture",{"images":{"front":"inputs/missing.png"}})
        q.run(q.get(job))
        self.assertEqual(q.get(job)["state"],"failed")
        self.assertIn("missing",q.get(job)["message"])

    def test_job_freezes_relative_owned_inputs_and_rejects_external_files(self):
        original=self.store.own_file(self.project,self.source)
        q=JobQueue(self.root/"jobs.sqlite3",self.store)
        job=q.submit(self.project,"Optimize",{"mesh":str(self.store.resolve(self.project,original))})
        self.assertEqual(json.loads(q.get(job)["request"])["mesh"],original)
        with self.assertRaises(ValueError):q.submit(self.project,"Optimize",{"mesh":str(self.source)})

if __name__=="__main__":unittest.main()
