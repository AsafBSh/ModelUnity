"""Real CPU mesh contracts, including private failure publication and UV seams."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import trimesh

from scripts.export_contracts import load_static_master
from scripts.workbench.optimization import optimize_mesh, assert_material_preserved, surface_error_metrics
from scripts.workbench.schema import OptimizationRequest
from scripts.workbench.projects import ProjectStore, digest
from scripts.workbench.jobs import JobQueue
from scripts.workbench.pipelines import execute


def seamed_panels():
    """Adjacent panels share positions but use distinct atlas islands at the seam."""
    vertices, faces, uv = [], [], []
    n = 10
    for panel in range(2):
        offset = len(vertices)
        for y in range(n+1):
            for x in range(n+1):
                vertices.append([panel-1+x/n, y/n, 0])
                uv.append([panel*.6+x/n*.4, y/n])
        for y in range(n):
            for x in range(n):
                a = offset+y*(n+1)+x
                faces.extend([[a,a+1,a+n+1],[a+1,a+n+2,a+n+1]])
    mesh = trimesh.Trimesh(vertices=vertices,faces=faces,process=False)
    albedo = np.zeros((16,16,3),dtype=np.uint8)
    albedo[:,:8] = [210,80,40];albedo[:,8:] = [40,160,220]
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv,
        material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(albedo),
            metallicRoughnessTexture=Image.new("RGB",(16,16),(240,80,30)),
            normalTexture=Image.new("RGB",(16,16),(128,128,255)),
            baseColorFactor=[.8,.9,1,1],metallicFactor=.7,roughnessFactor=.6,doubleSided=True))
    return mesh


class OptimizationTests(unittest.TestCase):
    def test_settings_reject_invalid_counts_nonfinite_and_truthy_strings(self):
        for options in ({"target":0},{"target":2.5},{"max_passes":4},{"max_passes":True},
                        {"max_bounds_change":float("nan")},{"max_surface_error":float("inf")},{"strict_budget":"false"}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                OptimizationRequest(**options)
        self.assertIsInstance(OptimizationRequest(target=80.,max_passes=2.).target,int)

    def test_empty_and_nonfinite_geometry_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"finite, nonempty"):
            optimize_mesh(trimesh.Trimesh(),OptimizationRequest())
        mesh=trimesh.creation.box();mesh.vertices[0,0]=float("nan")
        with self.assertRaisesRegex(ValueError,"finite, nonempty"):
            optimize_mesh(mesh,OptimizationRequest())

    def test_real_reduction_preserves_seam_islands_and_all_pbr_pixels(self):
        mesh=seamed_panels();old_faces=mesh.faces.copy();old_uv=mesh.visual.uv.copy()
        reduced,report=optimize_mesh(mesh,OptimizationRequest(target=80,strict_budget=True,preserve_boundary=True))
        self.assertLessEqual(len(reduced.faces),80)
        self.assertTrue(report["target_met"])
        self.assertTrue(1<=len(report["passes"])<=3)
        wedges=np.asarray(reduced.visual.uv)[reduced.faces]
        self.assertTrue(np.all((wedges[:,:,0].max(axis=1)<=.40001)|(wedges[:,:,0].min(axis=1)>=.59999)),
                        "A triangle crosses the two UV islands")
        assert_material_preserved(mesh,reduced)
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"optimized.glb";reduced.export(path)
            assert_material_preserved(mesh,load_static_master(path))
        np.testing.assert_array_equal(mesh.faces,old_faces)
        np.testing.assert_array_equal(mesh.visual.uv,old_uv)

    def test_winding_repair_changes_only_copy_and_keeps_uvs(self):
        mesh=seamed_panels();mesh.faces[0]=mesh.faces[0][::-1]
        self.assertFalse(mesh.is_winding_consistent)
        old_faces=mesh.faces.copy();old_uv=mesh.visual.uv.copy()
        repaired,report=optimize_mesh(mesh,OptimizationRequest(target=len(mesh.faces)))
        self.assertTrue(repaired.is_winding_consistent)
        self.assertGreater(report["winding_faces_reoriented_before"],0)
        self.assertEqual(report["passes"],[])
        np.testing.assert_array_equal(repaired.vertices,mesh.vertices)
        np.testing.assert_array_equal(repaired.visual.uv,old_uv)
        np.testing.assert_array_equal(mesh.faces,old_faces)

    def test_winding_is_checked_again_after_native_decimation(self):
        mesh=seamed_panels();flipped=mesh.copy();flipped.faces[0]=flipped.faces[0][::-1]
        with patch("scripts.lod_export._decimate_keep_uv",return_value=flipped):
            repaired,report=optimize_mesh(mesh,OptimizationRequest(target=80))
        self.assertTrue(repaired.is_winding_consistent)
        self.assertGreater(report["winding_faces_reoriented_after"],0)

    def test_broken_or_missing_uvs_cannot_silently_keep_textured_material(self):
        mesh=seamed_panels();mesh.visual.uv[0,0]=float("nan")
        with self.assertRaisesRegex(ValueError,"Invalid UV"):
            optimize_mesh(mesh,OptimizationRequest(target=80))
        mesh=seamed_panels();mesh.visual.uv=None
        with self.assertRaisesRegex(ValueError,"requires valid UVs"):
            optimize_mesh(mesh,OptimizationRequest(target=80))

    def test_geometry_path_keeps_small_disconnected_closed_detail(self):
        body=trimesh.creation.box().subdivide().subdivide()
        antenna=trimesh.creation.box(extents=[.005,.005,.04]).subdivide().subdivide()
        antenna.apply_translation([0,0,.52])
        mesh=trimesh.util.concatenate([body,antenna])
        reduced,report=optimize_mesh(mesh,OptimizationRequest(target=80))
        self.assertEqual(report["result"]["components"],2)
        self.assertTrue(reduced.is_watertight)
        self.assertLessEqual(len(reduced.faces),80)
        self.assertGreater(reduced.bounds[1,2],.53)

    def test_uv_fallback_is_rejected_unless_explicitly_enabled(self):
        mesh=seamed_panels();fallback=mesh.copy()
        fallback.metadata["modelunify_uv_method"]="KDTree fallback (may show texture seams)"
        with patch("scripts.lod_export._decimate_keep_uv",return_value=fallback):
            with self.assertRaisesRegex(ValueError,"UV preservation failed"):
                optimize_mesh(mesh,OptimizationRequest(target=80))
            _,report=optimize_mesh(mesh,OptimizationRequest(target=80,allow_uv_fallback=True))
            self.assertIn("KDTree",report["uv_fallback"])
            self.assertTrue(any("UV fallback" in w for w in report["warnings"]))

    def test_changed_texture_pixels_are_detected(self):
        mesh=seamed_panels();result=mesh.copy()
        result.visual.material=mesh.visual.material.copy()
        result.visual.material.metallicRoughnessTexture=Image.new("RGB",(16,16),"black")
        with self.assertRaisesRegex(ValueError,"metallicRoughnessTexture"):
            assert_material_preserved(mesh,result)

    def test_bounds_guard_rejects_large_deformation(self):
        mesh=seamed_panels();deformed=mesh.copy();deformed.vertices[:,0]*=2
        deformed.metadata["modelunify_uv_method"]="pymeshlab texture-aware"
        with patch("scripts.lod_export._decimate_keep_uv",return_value=deformed):
            with self.assertRaisesRegex(ValueError,"Bounds change"):
                optimize_mesh(mesh,OptimizationRequest(target=80,max_bounds_change=1))

    def test_surface_guard_rejects_deformation_even_when_bounds_match(self):
        mesh=trimesh.creation.box().subdivide().subdivide()
        mesh.visual=trimesh.visual.TextureVisuals(uv=mesh.vertices[:,:2]+.5,
            material=seamed_panels().visual.material)
        deformed=mesh.copy()
        center=np.all(np.isclose(deformed.vertices,[0,0,.5]),axis=1)
        self.assertTrue(center.any());deformed.vertices[center,2]=0
        np.testing.assert_array_equal(mesh.bounds,deformed.bounds)
        with patch("scripts.lod_export._decimate_keep_uv",return_value=deformed):
            with self.assertRaisesRegex(ValueError,"Sampled surface error"):
                optimize_mesh(mesh,OptimizationRequest(target=80))

    def test_surface_distances_are_repeatable_and_work_without_rtree(self):
        source=trimesh.creation.box();result=source.copy();result.apply_translation([.1,0,0])
        reference=surface_error_metrics(source,result,samples=16)
        self.assertAlmostEqual(reference["max_percent"],100*.1/np.sqrt(3),places=6)
        self.assertEqual(reference,surface_error_metrics(source,result,samples=16))
        with patch("trimesh.proximity.closest_point",side_effect=ModuleNotFoundError("rtree")):
            fallback=surface_error_metrics(source,result,samples=16)
        self.assertIn("naive",fallback["method"])
        self.assertAlmostEqual(reference["max_percent"],fallback["max_percent"],places=6)
        self.assertAlmostEqual(reference["rms_percent"],fallback["rms_percent"],places=6)

    def test_strict_budget_failure_keeps_accepted_asset_and_publishes_nothing(self):
        mesh=seamed_panels()
        with TemporaryDirectory() as tmp:
            root=Path(tmp);master=root/"master.glb";mesh.export(master);before=digest(master)
            store=ProjectStore(root/"projects");project=store.create("Strict budget")
            manifest=store.snapshot(project,{}, {},master);accepted=manifest["accepted"]
            owned=store.own_file(project,master)
            queue=JobQueue(root/"queue.sqlite3",store,execute)
            job=queue.submit(project,"Optimize",{"mesh":str(store.resolve(project,owned)),
                "settings":{"optimization":{"target":1,"strict_budget":True,"preserve_boundary":True}}})
            queue.run(queue.get(job))
            self.assertEqual(queue.get(job)["state"],"failed")
            self.assertIn("Strict triangle budget",queue.get(job)["message"])
            self.assertIsNone(store.load(project)["preview"])
            self.assertEqual(store.load(project)["accepted"],accepted)
            self.assertFalse((project/"jobs"/job).exists())
            self.assertEqual(digest(master),before)

    def test_real_pipeline_report_retains_requested_target_and_serialized_maps(self):
        mesh=seamed_panels()
        with TemporaryDirectory() as tmp:
            root=Path(tmp);master=root/"master.glb";mesh.export(master);before=digest(master)
            output,report=execute("Optimize",{"mesh":str(master),"settings":{
                "optimization":{"target":80,"strict_budget":True,"preserve_boundary":True}}},root/"job",lambda *_:None)
            self.assertTrue(report["optimization"]["target_met"])
            self.assertEqual(report["lods"]["levels"][0]["target_faces"],80)
            self.assertEqual(report["lods"]["master"]["triangles"],400)
            saved=json.loads((output.parent/"optimization_report.json").read_text())
            self.assertEqual(saved["result"]["triangles"],len(load_static_master(output).faces))
            assert_material_preserved(load_static_master(master),load_static_master(output))
            self.assertEqual(digest(master),before)

    def test_pipeline_rejects_uv_loss_at_serialization_boundary(self):
        from scripts import export_contracts
        def broken_reload(path):
            mesh=export_contracts.load_static_master(path)
            if Path(path).name=="Model_0.glb":mesh.visual.uv=None
            return mesh
        with TemporaryDirectory() as tmp:
            root=Path(tmp);master=root/"master.glb";seamed_panels().export(master)
            with patch("scripts.workbench.pipelines.load_static_master",side_effect=broken_reload):
                with self.assertRaisesRegex(ValueError,"round-trip lost valid UVs"):
                    execute("Optimize",{"mesh":str(master),"settings":{"optimization":{"target":80,"preserve_boundary":True}}},
                            root/"job",lambda *_:None)


if __name__=="__main__":unittest.main()
