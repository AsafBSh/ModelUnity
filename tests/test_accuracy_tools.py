"""Real CPU acceptance checks for the five accuracy/authoring additions."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import numpy as np
from PIL import Image,ImageDraw
import trimesh
from tests.test_optimization import seamed_panels
from scripts.workbench.mask_edit import apply_strokes,image_digest
from scripts.workbench.preparation import prepare
from scripts.workbench.schema import Preparation,OptimizationRequest
from scripts.workbench.reference_alignment import compare_reference
from scripts.workbench.optimization import optimize_mesh
from scripts.workbench.protection import selected_faces
from scripts.workbench.uv_rebake import rebake
from scripts.workbench.export_package import build_package,axis_matrix
from scripts.export_contracts import load_static_master


class MaskTests(unittest.TestCase):
    def test_black_removes_white_restores_rgb_and_original_are_preserved(self):
        original=Image.new('RGBA',(32,24),(110,90,40,0));original.putpixel((2,2),(110,90,40,255))
        layer=Image.new('RGBA',original.size);layer.putpixel((2,2),(0,0,0,255));layer.putpixel((3,3),(255,255,255,255))
        edited=apply_strokes({'background':original,'layers':[layer]})
        self.assertEqual(edited.getpixel((2,2))[3],0);self.assertEqual(edited.getpixel((3,3)),(110,90,40,255))
        self.assertEqual(original.getpixel((2,2))[3],255)

    def test_manual_digest_bypasses_second_removal_after_png_roundtrip(self):
        image=Image.new('RGBA',(32,24),'white');image.putpixel((0,0),(0,0,0,0))
        digest=image_digest(image)
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'reference.png';image.save(path)
            with Image.open(path) as restored:
                prepared,_,report=prepare(restored,Preparation(provider='rembg',preserve_alpha=False,size=256,manual_alpha_digests=[digest]),Path(tmp),{})
        self.assertEqual(report['actual'],'manual corrected alpha');self.assertEqual(prepared.size,(256,256))
        self.assertNotEqual(digest,image_digest(Image.new('RGBA',image.size,'white')))

    def test_empty_masks_and_wrong_layer_dimensions_fail(self):
        with self.assertRaises(ValueError):apply_strokes({'background':Image.new('RGBA',(4,4)),'layers':[]})
        with self.assertRaises(ValueError):apply_strokes({'background':Image.new('RGBA',(4,4),'white'),'layers':[Image.new('RGBA',(8,8))]})


class AlignmentTests(unittest.TestCase):
    def test_known_silhouette_beats_misaligned_view(self):
        mesh=trimesh.Trimesh(vertices=[[-.5,-.5,0],[.5,-.5,0],[.5,.5,0],[-.5,.5,0]],faces=[[0,1,2],[0,2,3]],process=False)
        image=Image.new('RGBA',(512,512));ImageDraw.Draw(image).rectangle((128,128,384,384),fill='white')
        _,good=compare_reference(mesh,image,scale=.5)
        _,bad=compare_reference(mesh,image,scale=.5,offset_x=.2)
        self.assertGreater(good['intersection_over_union'],.98)
        self.assertGreater(good['intersection_over_union'],bad['intersection_over_union'])
        self.assertLess(good['mean_boundary_error_pixels'],bad['mean_boundary_error_pixels'])

    def test_opaque_reference_and_nonfinite_alignment_rejected(self):
        with self.assertRaises(ValueError):compare_reference(trimesh.creation.box(),Image.new('RGB',(50,50),'white'))
        with self.assertRaises(ValueError):compare_reference(trimesh.creation.box(),Image.new('RGBA',(50,50)),scale=float('nan'))


class ProtectionTests(unittest.TestCase):
    def test_selected_triangles_and_uvs_survive_real_reduction(self):
        source=seamed_panels();original=source.triangles.copy()
        request=OptimizationRequest(target=200,protected_faces='0,1',preserve_boundary=True)
        result,report=optimize_mesh(source,request)
        np.testing.assert_array_equal(result.triangles[:2],original[:2])
        np.testing.assert_array_equal(source.triangles,original)
        np.testing.assert_array_equal(np.asarray(result.visual.uv)[result.faces[:2]],np.asarray(source.visual.uv)[source.faces[:2]])
        self.assertTrue(report['protected_geometry_exact']);self.assertLess(len(result.faces),len(source.faces))

    def test_bad_box_indices_and_insufficient_budget_rejected(self):
        mesh=seamed_panels()
        for options in [dict(protected_faces='99999'),dict(protected_box='0,0,0,0,1,1'),dict(protected_faces='0,1',target=1)]:
            with self.subTest(options=options),self.assertRaises(ValueError):optimize_mesh(mesh,OptimizationRequest(**options))

    def test_sharp_edge_selection_on_cube(self):
        mesh=trimesh.creation.box()
        self.assertTrue(selected_faces(mesh,OptimizationRequest(sharp_angle=60)).all())


class RebakeTests(unittest.TestCase):
    def test_real_xatlas_rebake_roundtrip_keeps_geometry_and_maps(self):
        source=seamed_panels();old_uv=source.visual.uv.copy()
        result,report=rebake(source,source,resolution=256)
        self.assertEqual(len(result.faces),len(source.faces));np.testing.assert_allclose(result.bounds,source.bounds)
        self.assertLess(report['max_projection_error_percent'],1e-4)
        self.assertGreater(report['coverage_fraction'],.1)
        for key in ['baseColorTexture','metallicRoughnessTexture','normalTexture']:
            self.assertEqual(getattr(result.visual.material,key).size,(256,256))
        albedo=np.asarray(result.visual.material.baseColorTexture)
        self.assertTrue(((albedo[:,:,0]>150)&(albedo[:,:,2]<100)).any())
        self.assertTrue(((albedo[:,:,2]>150)&(albedo[:,:,0]<100)).any())
        np.testing.assert_array_equal(source.visual.uv,old_uv)
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'rebaked.glb';result.export(path);loaded=load_static_master(path)
            self.assertEqual(loaded.visual.material.normalTexture.size,(256,256))

    def test_misaligned_high_mesh_rejected(self):
        source=seamed_panels();target=source.copy();target.apply_translation([0,0,5])
        with self.assertRaisesRegex(ValueError,'projection deviation'):rebake(target,source,resolution=256)


class ExportTests(unittest.TestCase):
    def package(self,path,bms=True):
        return build_package(path,{'export':{'asset_name':'hangar','distances':[500],'metres_per_unit':2,'bms_handoff':bms,'bms_axes':'+Z,-X,-Y','wetness':.25}})

    def test_bms_json_mti_parent_and_pbr_channels_match_staged_geometry(self):
        mesh=seamed_panels();mesh.visual.material.doubleSided=False
        with TemporaryDirectory() as tmp:
            root=Path(tmp);mesh.export(root/'Model_0.glb');report=self.package(root)
            folder=root/'bms_handoff';definitions=json.loads((folder/'Materials.mtl').read_text())['Materials']
            name=(folder/'Model_0.mti').read_text().strip();self.assertEqual(name,definitions[0]['Name'])
            self.assertEqual([v['Slot'] for v in definitions[0]['Textures']],[0,1,2])
            staged=trimesh.load(folder/'geometry/Model_0.obj',force='mesh',process=False)
            np.testing.assert_allclose(staged.bounds,report['bms_bounds_ft'],atol=1e-6)
            dimensions=[float(v) for v in (folder/'Parent.dat').read_text().split('Dimensions = ')[1].splitlines()[0].split()]
            np.testing.assert_allclose(np.array(dimensions[1:]).reshape(3,2).T,staged.bounds,atol=1e-6)
            armw=np.asarray(Image.open(folder/f'{name}_ARMW.png'))
            self.assertTrue(np.all(armw[:,:,3]==63));self.assertTrue(np.all(armw[:,:,0]==255))
            self.assertTrue((root/'interchange/Model_0.mtl').read_text().startswith('newmtl '))
            self.assertFalse(report['bms_ready']);self.assertTrue((root/'NEXT_STEPS_BMS.txt').exists())
            import zipfile
            with zipfile.ZipFile(root/'export_package.zip') as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn('interchange/Model_0.mtl',archive.namelist())
                self.assertIn('bms_handoff/Materials.mtl',archive.namelist())
                self.assertIn('bms_handoff/Model_0.mti',archive.namelist())
                self.assertNotIn('bms_template/Parent.dat',archive.namelist())

    def test_general_export_accepts_two_sided_and_bms_refuses_it(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);seamed_panels().export(root/'Model_0.glb')
            self.assertFalse(self.package(root,bms=False)['bms_ready'])
            self.assertFalse((root/'bms_handoff').exists())
        with TemporaryDirectory() as tmp:
            root=Path(tmp);seamed_panels().export(root/'Model_0.glb')
            with self.assertRaisesRegex(ValueError,'single-sided'):self.package(root)

    def test_axes_refuse_duplicate_or_unknown_components(self):
        for text in ['+X,+X,+Y','X,Y,Z','+X,+Y','+X,+Y,nan']:
            with self.subTest(text=text),self.assertRaises(ValueError):axis_matrix(text)


class PipelineTests(unittest.TestCase):
    def test_rebake_queue_owns_high_source_and_publishes_reproducible_result(self):
        from scripts.workbench.projects import ProjectStore,digest
        from scripts.workbench.jobs import JobQueue
        from scripts.workbench.pipelines import execute
        with TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'supplied.glb';seamed_panels().export(source)
            original=digest(source)
            store=ProjectStore(root/'projects');folder=store.create('Rebake fixture')
            owned=store.own_file(folder,source)
            queue=JobQueue(root/'jobs.sqlite3',store,executor=execute)
            job=queue.submit(folder,'Rebake',{'mesh':str(store.resolve(folder,owned)),'high_mesh':owned,'images':{},
                'settings':{'rebake':{'resolution':256,'padding':4,'max_distance':2}}})
            queue.run(queue.get(job));row=queue.get(job)
            self.assertEqual(row['state'],'completed',row['message'])
            self.assertTrue(Path(row['result']).is_file());self.assertEqual(digest(source),original)
            request=json.loads(row['request']);self.assertFalse(Path(request['high_mesh']).is_absolute())
            self.assertEqual(store.load(folder)['versions'][-1]['stage'],'Rebake')

    def test_protected_optimization_is_checked_after_glb_publication(self):
        from dataclasses import asdict
        from scripts.workbench.pipelines import execute
        with TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.glb';seamed_panels().export(source)
            output,report=execute('Optimize',{'mesh':str(source),'images':{},'settings':{'normal':'off',
                'optimization':asdict(OptimizationRequest(target=200,protected_faces='0,1'))}},root/'job',lambda *_:None)
            self.assertTrue(output.is_file());self.assertTrue(report['optimization']['protected_roundtrip_float32_exact'])

    def test_bms_handoff_through_export_pipeline_uses_selected_distances(self):
        from scripts.workbench.pipelines import execute
        with TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.glb';mesh=seamed_panels();mesh.visual.material.doubleSided=False;mesh.export(source)
            settings={'normal':'off','export':{'count':1,'budgets':[400],'shared':True,'distances':[812],
                'metres_per_unit':1,'asset_name':'building','bms_handoff':True,'bms_axes':'+Z,-X,-Y','wetness':0}}
            output,report=execute('Export',{'mesh':str(source),'images':{},'settings':settings},root/'job',lambda *_:None)
            self.assertTrue((output.parent/'bms_handoff/Materials.mtl').exists())
            self.assertIn('812',(output.parent/'bms_handoff/Parent.dat').read_text())
            self.assertFalse(report['package']['bms_ready'])


if __name__=='__main__':unittest.main()
