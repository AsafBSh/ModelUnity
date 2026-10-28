"""Focused regressions. All mesh/deployment writes use temporary directories."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import trimesh
from typer.testing import CliRunner

from scripts import deploy_bms, lod_export
from scripts.export_contracts import load_static_master
from scripts.gpu_lifecycle import operation, register


def textured_mesh():
    mesh = trimesh.creation.icosphere(subdivisions=2)
    uv = np.column_stack(
        (
            (np.arctan2(mesh.vertices[:, 0], mesh.vertices[:, 2]) / (2 * np.pi) + 0.5),
            np.arccos(mesh.vertices[:, 1]) / np.pi,
        )
    )
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=uv,
        material=trimesh.visual.material.PBRMaterial(
            baseColorTexture=Image.new("RGB", (16, 16), (90, 130, 70)),
            metallicRoughnessTexture=Image.new("RGB", (16, 16), (255, 100, 40)),
            normalTexture=Image.new("RGB", (16, 16), (128, 128, 255)),
        ),
    )
    return mesh


class ExportTests(unittest.TestCase):
    def test_staging_preserves_existing_master(self):
        from tools.instalod import stage

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.glb"
            textured_mesh().export(source)
            cfg = {"paths": {"instalod_dir": str(root / "studio")}}
            with patch.object(stage, "load_config", return_value=cfg):
                dest = stage.stage_master(name="asset", glb=source)
                before = dest.read_bytes()
                with self.assertRaises(FileExistsError):
                    stage.stage_master(name="asset", glb=source)
                self.assertEqual(dest.read_bytes(), before)
                with self.assertRaises(ValueError):
                    stage.stage_master(name="../escape", glb=source)

    def test_empty_mesh_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "nonempty"):
                lod_export.make_lod_set(
                    trimesh.Trimesh(), "asset", [("Model_0", 100)], tmp
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_roundtrip_preserves_master_maps_and_reduces_lower_lod(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "master.glb"
            textured_mesh().export(master)
            before = hashlib.sha256(master.read_bytes()).digest()
            result = lod_export.make_textured_lod_set(
                master,
                "asset",
                [("Model_0", 40000), ("Model_1", 100)],
                root,
                normal_baker="off",
            )
            report = json.loads((result / "lod_report.json").read_text())
            self.assertEqual(report["levels"][0]["achieved_faces"], 320)
            self.assertLess(report["levels"][1]["achieved_faces"], 320)
            mesh = trimesh.load(result / "Model_0.glb", force="mesh", process=False)
            for key in (
                "baseColorTexture",
                "metallicRoughnessTexture",
                "normalTexture",
            ):
                self.assertIsNotNone(getattr(mesh.visual.material, key))
            np.testing.assert_array_equal(
                np.asarray(mesh.visual.material.metallicRoughnessTexture)[0, 0, :3],
                [255, 100, 40],
            )
            self.assertEqual(before, hashlib.sha256(master.read_bytes()).digest())
            self.assertEqual(
                np.asarray(Image.open(result / "roughness.png"))[0, 0], 100
            )
            self.assertEqual(np.asarray(Image.open(result / "metallic.png"))[0, 0], 40)
            self.assertIn(
                "map_Pr roughness.png", (result / "Materials.mtl").read_text()
            )

    def test_noop_lower_lod_fails_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "duplicate/no-op"):
                lod_export.make_lod_set(
                    textured_mesh(),
                    "asset",
                    [("Model_0", 40000), ("Model_1", 8000)],
                    tmp,
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_failed_decimator_does_not_publish_partial_set(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                lod_export, "_decimate_keep_uv", side_effect=lambda m, t: m.copy()
            ),
        ):
            with self.assertRaisesRegex(ValueError, "duplicate/no-op"):
                lod_export.make_lod_set(
                    textured_mesh(), "asset", [("Model_0", 320), ("Model_1", 50)], tmp
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_existing_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "asset"
            dest.mkdir()
            (dest / "Model_0.glb").write_bytes(b"master")
            with self.assertRaises(FileExistsError):
                lod_export.make_lod_set(
                    textured_mesh(), "asset", [("Model_0", 320)], tmp
                )
            self.assertEqual((dest / "Model_0.glb").read_bytes(), b"master")

    def test_generator_targets_are_not_consumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            master = Path(tmp) / "master.glb"
            textured_mesh().export(master)
            out = lod_export.make_textured_lod_set(
                master, "asset", iter([("Model_0", 320)]), tmp, normal_baker="off"
            )
            self.assertTrue((out / "Model_0.glb").is_file())

    def test_uv_loss_has_flat_colour_and_report(self):
        mesh = textured_mesh()
        with tempfile.TemporaryDirectory() as tmp:
            master = Path(tmp) / "master.glb"
            mesh.export(master)
            reduced = trimesh.creation.icosphere(subdivisions=1)
            with patch.object(lod_export, "_decimate_keep_uv", return_value=reduced):
                out = lod_export.make_textured_lod_set(
                    master,
                    "asset",
                    [("Model_0", 320), ("Model_1", 80)],
                    tmp,
                    normal_baker="off",
                )
            report = json.loads((out / "lod_report.json").read_text())
            self.assertEqual(report["levels"][1]["uv_fallback"], "flat average albedo")
            low = trimesh.load(out / "Model_1.glb", force="mesh", process=False)
            self.assertIsNone(low.visual.material.baseColorTexture)

    def test_multi_instance_scene_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            scene = trimesh.Scene()
            scene.add_geometry(textured_mesh())
            scene.add_geometry(textured_mesh())
            path = Path(tmp) / "scene.glb"
            scene.export(path)
            with self.assertRaisesRegex(ValueError, "one static mesh"):
                load_static_master(path)


class DeploymentTests(unittest.TestCase):
    def fixture(self, tmp):
        root = Path(tmp)
        asset = root / "asset"
        asset.mkdir()
        (asset / "Model_0.bml").write_bytes(b"temporary BML fixture")
        (asset / "Parent.dat").write_bytes(b"fixture")
        (asset / "Materials.mtl").write_text("{}")
        bms = root / "fake-bms"
        (bms / "Data/TerrData/Objects").mkdir(parents=True)
        return asset, bms

    def invoke(self, asset, bms, *extra):
        return CliRunner().invoke(
            deploy_bms.app,
            [str(asset), "--bms-install", str(bms), "--parent-id", "12", *extra],
        )

    def test_valid_dry_run_is_side_effect_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset, bms = self.fixture(tmp)
            before = sorted(str(p.relative_to(bms)) for p in bms.rglob("*"))
            result = self.invoke(asset, bms, "--dry-run")
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Planned", result.output)
            self.assertEqual(
                before, sorted(str(p.relative_to(bms)) for p in bms.rglob("*"))
            )

    def test_invalid_asset_does_not_create_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset, bms = self.fixture(tmp)
            (asset / "Parent.dat").unlink()
            result = self.invoke(asset, bms)
            self.assertNotEqual(result.exit_code, 0)
            self.assertFalse((bms / "Data/TerrData/Objects/Models").exists())

    def test_collision_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset, bms = self.fixture(tmp)
            dest = bms / "Data/TerrData/Objects/Models/12"
            dest.mkdir(parents=True)
            (dest / "Model_0.bml").write_bytes(b"original")
            self.assertNotEqual(self.invoke(asset, bms).exit_code, 0)
            self.assertEqual((dest / "Model_0.bml").read_bytes(), b"original")
            self.assertNotEqual(
                self.invoke(
                    asset, bms, "--obj-folder", "../escape", "--dry-run"
                ).exit_code,
                0,
            )

    def test_copy_to_fake_install_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset, bms = self.fixture(tmp)
            result = self.invoke(asset, bms)
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(
                (bms / "Data/TerrData/Objects/Models/12/Model_0.bml").read_bytes(),
                (asset / "Model_0.bml").read_bytes(),
            )


class LifecycleTests(unittest.TestCase):
    def test_cli_shape_unloads_before_paint_and_after_failures(self):
        from scripts import generate_3d, engine_hunyuan, engine_paint

        events = []

        class Shape:
            def __init__(self):
                register(self)

            def generate_multiview(self, *a, **kw):
                events.append("shape")
                return textured_mesh()

            def unload(self):
                events.append("shape-unload")

        class Painter:
            last_mmgp_applied = True
            load_warnings = []

            def __init__(self, *a, **kw):
                register(self)

            def paint(self, *a):
                self.assert_shape_unloaded = "shape-unload" in events
                if not self.assert_shape_unloaded:
                    raise AssertionError("shape remains loaded")
                events.append("paint")
                raise RuntimeError("paint failure")

            def unload(self):
                events.append("paint-unload")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                engine_hunyuan, "engine_from_config", side_effect=lambda cfg: Shape()
            ),
            patch.object(engine_paint, "Hunyuan3DPainter", Painter),
            patch.object(engine_paint, "rasterizer_ready", return_value=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "paint failure"):
                generate_3d.multiview_textured(
                    name="test",
                    front=Path("synthetic.png"),
                    left=None,
                    back=None,
                    right=None,
                    output_dir=Path(tmp),
                    seed=42,
                    steps=2,
                    octree=128,
                    views=4,
                    resolution=512,
                    no_remesh=False,
                    low_vram=True,
                )
        self.assertLess(events.index("shape-unload"), events.index("paint"))
        self.assertIn("paint-unload", events)

    def test_paint_cleanup_runs_even_if_loading_fails(self):
        from scripts.engine_paint import Hunyuan3DPainter, PaintConfig

        painter = Hunyuan3DPainter(PaintConfig())
        with (
            patch.object(painter, "_paint", side_effect=RuntimeError("partial load")),
            patch.object(painter, "unload") as release,
        ):
            with self.assertRaisesRegex(RuntimeError, "partial load"):
                painter.paint("unused.glb", "unused.png")
            release.assert_called_once()

    def test_paint_refuses_input_collision_before_loading(self):
        from scripts.engine_paint import Hunyuan3DPainter, PaintConfig

        with tempfile.TemporaryDirectory() as tmp:
            master = Path(tmp) / "master.glb"
            textured_mesh().export(master)
            before = master.read_bytes()
            painter = Hunyuan3DPainter(PaintConfig())
            with patch.object(painter, "load") as load:
                with self.assertRaisesRegex(ValueError, "input master"):
                    painter.paint(master, "unused.png", master)
                load.assert_not_called()
            self.assertEqual(master.read_bytes(), before)

    def test_mmgp_release_error_still_drops_pipeline(self):
        from scripts.engine_paint import Hunyuan3DPainter, PaintConfig
        from unittest.mock import Mock

        painter = Hunyuan3DPainter(PaintConfig())
        painter._pipeline = Mock(models={})
        painter._offload = Mock()
        painter._offload.release.side_effect = RuntimeError("release failed")
        painter.unload()
        self.assertIsNone(painter._pipeline)
        self.assertIsNone(painter._offload)

    def test_cleanup_releases_components_held_by_an_upstream_traceback(self):
        from scripts.engine_paint import Hunyuan3DPainter, PaintConfig
        from unittest.mock import Mock

        painter = Hunyuan3DPainter(PaintConfig())
        upstream = Mock()
        model = Mock()
        upstream.models = {"multiview_model": model}
        painter._pipeline = upstream
        painter.unload()
        model.dino_v2.to.assert_called_once_with("cpu")
        model.upsampler.model.to.assert_called_once_with("cpu")
        self.assertEqual(upstream.models, {})
        self.assertIsNone(upstream.render)

    def test_mmgp_default_device_is_restored_after_release(self):
        import torch
        from scripts.engine_paint import Hunyuan3DPainter, PaintConfig

        previous = torch.get_default_device()
        painter = Hunyuan3DPainter(PaintConfig())
        painter._previous_default_device = previous
        try:
            torch.set_default_device("cuda")
            painter.unload()
            self.assertEqual(torch.get_default_device(), previous)
            # Diffusers schedulers must still be able to convert newly created tensors.
            np.asarray(torch.tensor([1.0]))
        finally:
            torch.set_default_device(previous)

    def test_cleanup_after_partial_load_and_error(self):
        events = []

        class Resource:
            def __init__(self):
                register(self)

            def unload(self):
                events.append("unload")

        @operation()
        def run():
            Resource()
            raise RuntimeError("load failed")

        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "load failed"):
                run()
        self.assertEqual(events, ["unload", "unload"])

    def test_ai_normal_fallback_is_reported_and_unloaded(self):
        with (
            patch.object(
                lod_export, "bake_normal_marigold", side_effect=RuntimeError("OOM")
            ),
            patch.object(lod_export, "_unload_marigold_pipe") as release,
        ):
            image = lod_export.bake_normal_map(
                textured_mesh(), Image.new("RGB", (16, 16)), baker="high", uv_size=16
            )
            self.assertEqual(image.info["modelunify_baker"], "low")
            release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
