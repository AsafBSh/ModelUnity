"""Reference heuristics, UV geometry, measured scaling and prompt isolation."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import zipfile
import numpy as np
from PIL import Image, ImageDraw
import trimesh
from scripts.workbench.input_readiness import check_inputs, mask_metrics, overlay
from scripts.workbench.diagnostics import diagnose
from scripts.workbench.scaling import ScaleRequest, scale_mesh, bms_readiness
from scripts.workbench.preparation import prepare
from scripts.workbench.schema import Preparation
from scripts.comfyui_progress import LiveProgress
from scripts.comfyui_install import install_source, selected_keys, plan, base_python
from scripts.workbench.projects import ProjectStore,digest


def plane(stacked=False):
    vertices=[[0,0,0],[1,0,0],[1,1,0],[0,1,0]]
    faces=[[0,1,2],[0,2,3]];uv=[[0,0],[1,0],[1,1],[0,1]]
    if stacked:faces=[[0,1,2],[0,1,2]]
    mesh=trimesh.Trimesh(vertices,faces,process=False)
    mesh.visual=trimesh.visual.TextureVisuals(uv=uv,material=trimesh.visual.material.PBRMaterial(
        baseColorTexture=Image.new('RGB',(32,32),(60,140,180)),
        metallicRoughnessTexture=Image.new('RGB',(32,32),(255,180,0))))
    return mesh


class InputChecks(TestCase):
    def test_single_model_ignores_other_directions(self):
        good=Image.new('RGB',(256,256),'black')
        r=check_inputs({'backend':'TripoSG 1.5B'},{'left':good})
        self.assertFalse(r['ready']);self.assertIn('Front',' '.join(r['errors']))
        r=check_inputs({'backend':'TripoSG 1.5B'},{'front':good,'left':good})
        self.assertEqual(list(r['views']),['front']);self.assertTrue(r['ready'])

    def test_empty_mask_rejected_and_input_unchanged(self):
        image=Image.new('RGBA',(256,256),(40,100,70,0));before=image.tobytes()
        self.assertFalse(check_inputs({}, {'front':image})['ready'])
        with TemporaryDirectory() as tmp,self.assertRaisesRegex(ValueError,'foreground'):
            prepare(image,Preparation(size=256),Path(tmp),{})
        self.assertEqual(image.tobytes(),before)

    def test_background_warning_and_framing(self):
        r=check_inputs({'preparation':{'provider':'none'}},{'front':Image.new('RGB',(256,256),'white')})
        self.assertTrue(any('background' in w for w in r['warnings']))
        image=Image.new('RGBA',(256,256),(0,0,0,0))
        ImageDraw.Draw(image).rectangle((64,32,191,223),fill=(40,100,70,255))
        self.assertEqual(mask_metrics(image)['bbox'],[64,32,192,224])
        before=image.tobytes();self.assertEqual(overlay(image).size,image.size);self.assertEqual(image.tobytes(),before)

    def test_fixed_orbit_checks_do_not_claim_calibration(self):
        settings={'backend':'Pixal3D · ComfyUI','c_multiview':True,'preparation':{'crop':'0,0,200,200'}}
        r=check_inputs(settings,{'front':Image.new('RGB',(256,256)),'right':Image.new('RGB',(512,512))})
        self.assertFalse(r['ready']);self.assertFalse(r['alignment_verified']);self.assertEqual(len(r['errors']),2)


class UVDiagnostics(TestCase):
    def test_shared_edges_not_reported_as_overlap(self):
        r,images=diagnose(plane(),128)
        self.assertEqual(r['uv']['overlap_pixels'],0)
        self.assertAlmostEqual(r['uv']['stretch_anisotropy_median'],1.)
        self.assertAlmostEqual(r['uv']['texels_per_mesh_unit_median'],32.)
        self.assertGreater(r['uv']['coverage_fraction'],.95)
        self.assertTrue(all(i.size==(128,128) for i in images))

    def test_stacked_faces_and_stretch_detected(self):
        mesh=plane(True);mesh.visual.uv[:,0]*=.1
        r,_=diagnose(mesh,128)
        self.assertGreater(r['uv']['overlap_pixels'],100)
        self.assertGreater(r['uv']['stretch_anisotropy_median'],9.)

    def test_missing_invalid_degenerate_and_work_budget(self):
        mesh=trimesh.creation.box();r,images=diagnose(mesh)
        self.assertIsNone(r['uv']);self.assertEqual(images,(None,None,None))
        mesh=plane();mesh.visual.uv[:]=0
        r,_=diagnose(mesh);self.assertEqual(r['uv']['degenerate_tested_faces'],2)
        mesh.visual.uv[0,0]=float('nan');self.assertIsNone(diagnose(mesh)[0]['uv'])
        r,_=diagnose(plane(True),128,raster_budget=17000)
        self.assertTrue(r['uv']['raster_budget_limited']);self.assertEqual(r['uv']['raster_tested_faces'],1)


class Scaling(TestCase):
    def test_measured_scale_orientation_pivot_and_glb_roundtrip(self):
        mesh=trimesh.creation.box(extents=[2,4,6]);mesh.apply_translation([10,20,30])
        mesh.visual=trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices),2)),material=plane().visual.material)
        before=mesh.vertices.copy()
        result,r=scale_mesh(mesh,ScaleRequest(axis='Y',metres=12,source_up='Z',source_forward='+X'))
        np.testing.assert_array_equal(mesh.vertices,before)
        np.testing.assert_allclose(np.ptp(result.bounds,axis=0),[8,12,4])
        self.assertEqual(result.bounds[0,1],0);self.assertEqual(r['metres_per_unit'],1)
        with TemporaryDirectory() as tmp:
            file=Path(tmp)/'scaled.glb';result.export(file)
            restored=trimesh.load(file,force='mesh',process=False)
            np.testing.assert_allclose(restored.bounds,result.bounds,atol=1e-5)
            np.testing.assert_array_equal(np.asarray(restored.visual.material.baseColorTexture),np.asarray(mesh.visual.material.baseColorTexture))

    def test_bad_scale_and_readiness(self):
        for kw in ({'metres':float('nan')},{'source_up':'Y','source_forward':'+Y'},{'axis':'XY'}):
            with self.assertRaises(ValueError):ScaleRequest(**kw)
        with self.assertRaisesRegex(ValueError,'zero extent'):scale_mesh(plane(),ScaleRequest(axis='Z'))
        for budgets in ([100,200],[float('nan')],[True],['wrong']):
            r=bms_readiness(plane(),{'count':len(budgets),'budgets':budgets})
            self.assertEqual(r['status'],'invalid');self.assertFalse(r['final_game_ready'])
        r=bms_readiness(plane(),{'count':1,'budgets':[100],'metres_per_unit':.01,'distances':['wrong']})
        self.assertEqual(r['status'],'invalid');np.testing.assert_allclose(r['dimensions_metres'],[.01,.01,0])
        r=bms_readiness(plane(),{'count':2,'budgets':[40000,8000]})
        self.assertTrue(any('duplicate/no-op' in e for e in r['errors']))


class NativeProgress(TestCase):
    def test_only_own_prompt_events_and_finite_steps(self):
        live=LiveProgress('http://127.0.0.1:8188','c',{'shape':{'class_type':'Sampler'},'save':{'class_type':'SaveGLB'}})
        live.prompt_id='own'
        live.ingest({'type':'progress','data':{'prompt_id':'foreign','node':'shape','value':9,'max':10}})
        self.assertIsNone(live.step)
        live.ingest({'type':'progress','data':{'prompt_id':'own','node':'shape','value':5,'max':10}})
        self.assertIn('step 5/10',live.poll()[0])
        live.ingest({'type':'progress','data':{'prompt_id':'own','node':'shape','value':float('nan'),'max':10}})
        self.assertEqual(live.step,5)
        live.ingest({'type':'executing','data':{'prompt_id':'own','node':'save'}})
        self.assertEqual(live.completed,{'shape'});self.assertIsNone(live.step)
        live.sample_memory({'devices':[{'torch_vram_total':100,'torch_vram_free':40}]})
        live.sample_memory({'devices':[{'torch_vram_total':100,'torch_vram_free':80}]})
        self.assertEqual(live.snapshot()['sampled_peak_host_torch_allocated_bytes'],60)


class WorkbenchIntegration(TestCase):
    def test_scale_job_preserves_source_and_publishes_measured_copy(self):
        from scripts.workbench.jobs import JobQueue
        from scripts.workbench.pipelines import execute
        with TemporaryDirectory() as tmp:
            root=Path(tmp);store=ProjectStore(root/'projects');folder=store.create('Measured')
            source=root/'original.glb';plane().export(source);before=digest(source)
            manifest=store.snapshot(folder,{}, {},source)
            q=JobQueue(root/'jobs.sqlite3',store,execute)
            job=q.submit(folder,'Scale',{'settings':{'scale':{'axis':'X','metres':7,'pivot':'center'}},'mesh':str(store.resolve(folder,manifest['source']))})
            q.run(q.get(job));state=q.get(job)
            self.assertEqual(state['state'],'completed',state['message'])
            result=trimesh.load(state['result'],force='mesh',process=False)
            self.assertAlmostEqual(np.ptp(result.bounds,axis=0)[0],7.)
            self.assertEqual(before,digest(source));self.assertIsNotNone(result.visual.material.metallicRoughnessTexture)
            report=json.loads((Path(state['result']).parent/'operation.json').read_text())
            self.assertEqual(report['scale']['metres_per_unit'],1.)

    def test_raw_comparison_follows_owned_parent_not_latest_generation(self):
        from scripts import workbench_service as svc
        with TemporaryDirectory() as tmp:
            store=ProjectStore(Path(tmp)/'projects');folder=store.create('Compare')
            first=folder/'jobs/first';first.mkdir(parents=True)
            plane().export(first/'asset.glb');plane(True).export(first/'master.glb')
            store.add_version(folder,first/'asset.glb','Generate','first',{})
            store.accept(folder)
            frozen=store.own_file(folder,first/'asset.glb','job_inputs')
            derived=folder/'jobs/derived';derived.mkdir();plane().export(derived/'asset.glb')
            store.add_version(folder,derived/'asset.glb','Scale','derived',{'mesh':frozen,'mesh_version':'jobs/first/asset.glb'})
            other=folder/'jobs/unrelated';other.mkdir();plane().export(other/'asset.glb');plane().export(other/'master.glb')
            store.add_version(folder,other/'asset.glb','Generate','other',{})
            with patch.object(svc,'STORE',store):
                assets=svc.comparison_assets(str(folder),str(derived/'asset.glb'),None)
            self.assertEqual(Path(assets['raw']),first/'master.glb')

    def test_strict_cleanup_rejects_changed_shape_keeps_raw(self):
        from scripts.workbench.pipelines import execute
        from scripts.workbench.benchmarking import benchmark_settings
        with TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'input.png';Image.new('RGB',(256,256)).save(image)
            def generate(views,shape,folder,checkpoint):
                raw=trimesh.creation.box();raw.export(folder/'master.glb')
                changed=raw.copy();changed.apply_scale(.1);changed.export(folder/'asset.glb')
                return folder/'asset.glb',{'warnings':[]}
            from unittest.mock import Mock
            engine=Mock();engine.generate.side_effect=generate
            settings=benchmark_settings('trellis',preparation={'provider':'none','size':256});settings['c_guard_strict']=True
            with patch('scripts.engine_comfyui.engine_from_config',return_value=engine),self.assertRaisesRegex(ValueError,'No preview published'):
                execute('Generate',{'settings':settings,'images':{'front':str(image)}},root/'job',lambda *args:None)
            self.assertTrue((root/'job/master.glb').exists())
            self.assertTrue((root/'job/cleanup_comparison.json').exists())

    def test_gui_benchmark_preflights_before_creating_projects(self):
        from scripts import workbench_service as svc
        with TemporaryDirectory() as tmp:
            store=ProjectStore(Path(tmp)/'projects')
            with patch.object(svc,'STORE',store),self.assertRaises(ValueError):
                svc.queue_benchmark('Test',{}, {'left':Image.new('RGB',(256,256))},['hunyuan','triposg'],'quick',20000)
            self.assertEqual(store.choices(),[])


class SourceInstaller(TestCase):
    def test_plan_rejects_missing_disk_and_old_driver_without_writes(self):
        from scripts.engine_comfyui import ComfyConfig
        from unittest.mock import Mock
        with TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=ComfyConfig(server_dir=str(root/'ComfyUI'),python_exe=str(root/'python/Scripts/python.exe'))
            probe=Mock(returncode=0,stdout='NVIDIA fixture, 555.10, 12288',stderr='')
            with patch('scripts.comfyui_install.shutil.disk_usage',return_value=Mock(free=1024)),patch('scripts.comfyui_install.subprocess.run',return_value=probe):
                r=plan(cfg,'trellis')
            self.assertFalse(r['ready']);self.assertTrue(any('driver' in e for e in r['errors']));self.assertTrue(any('space' in e for e in r['errors']))
            self.assertEqual(list(root.iterdir()),[])

    def test_unsigned_python_installer_never_executed(self):
        import subprocess,sys
        with TemporaryDirectory() as tmp:
            root=Path(tmp);embedded=root/'python.exe';embedded.with_name('python311._pth').write_text('.')
            installer=root/'installer.exe';installer.write_bytes(b'fixture')
            with patch.object(sys,'executable',str(embedded)),patch('winreg.OpenKey',side_effect=OSError),\
                 patch('scripts.comfyui_install.download',return_value=installer),\
                 patch('scripts.comfyui_install.subprocess.run',side_effect=subprocess.CalledProcessError(1,'signature')) as run,\
                 self.assertRaises(subprocess.CalledProcessError):base_python(root/'runtime')
            self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.args[0][0],'powershell')

    def test_pinned_archive_and_existing_destination_preserved(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'source.zip';host=root/'ComfyUI'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('ComfyUI-abc/main.py','print(1)')
            with patch('scripts.comfyui_install.download',return_value=archive):install_source(host,'abc')
            self.assertEqual(json.loads((host/'modelunify_source.json').read_text())['revision'],'abc')
            with patch('scripts.comfyui_install.download',return_value=archive),self.assertRaises(ValueError):install_source(host,'abc')
            self.assertEqual((host/'main.py').read_text(),'print(1)')

    def test_traversal_rejected(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'source.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('ComfyUI-abc/../../escape.py','bad')
            with patch('scripts.comfyui_install.download',return_value=archive),self.assertRaises(ValueError):install_source(root/'host','abc')
            self.assertFalse((root/'escape.py').exists())
        self.assertIn('pixal_mv',selected_keys('pixal-mv'));self.assertNotIn('moge',selected_keys('pixal-mv'))
