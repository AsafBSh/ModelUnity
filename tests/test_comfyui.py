"""ComfyUI graph bindings, local HTTP transport and failure isolation. No AI weights."""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import json
import unittest
from unittest.mock import patch
import trimesh
from PIL import Image

from scripts.comfyui_workflows import BACKENDS, ComfyRequest, WEIGHTS, build_workflow, check_graph
from scripts.engine_comfyui import ComfyClient, ComfyConfig, ComfyError, ComfyEngine
from scripts.workbench.schema import ShapeRequest
from scripts.workbench.projects import ProjectStore


class GraphTests(unittest.TestCase):
    def test_single_and_multiview_conditioning_are_model_specific(self):
        for backend,multi,kind,weight in ((BACKENDS[0],False,"Trellis2Conditioning","trellis"),
                (BACKENDS[1],False,"Pixal3DConditioning","pixal"),(BACKENDS[1],True,"Pixal3DMultiViewConditioning","pixal_mv")):
            with self.subTest(backend=backend,multi=multi):
                request=ComfyRequest(backend=backend,multiview=multi,remesh=False,faces=0)
                graph,_=build_workflow(request,{"front":"front.png",**({"left":"left.png"} if multi else {})},"modelunify/test")
                self.assertEqual(graph["conditioning"]["class_type"],kind)
                self.assertEqual(graph["model"]["inputs"]["unet_name"],WEIGHTS[weight])
                self.assertEqual("camera" in graph,backend==BACKENDS[1] and not multi)
                self.assertNotIn("remesh",graph)
                self.assertNotIn("decimate",graph)

    def test_stage_parameters_reach_the_correct_nodes(self):
        request=ComfyRequest(backend=BACKENDS[1],auto_fov=False,resolution=1536,structure_steps=15,
            shape_steps=26,upsample_steps=19,texture_steps=17,guidance=8.2,texture_guidance=2.3,seed=987,
            texture_size=4096,fov=43.)
        graph,_=build_workflow(request,{"front":"f.png"},"modelunify/test")
        for name,steps,cfg in (("structure",15,8.2),("shape",26,8.2),("upsample",19,8.2),("texture",17,2.3)):
            self.assertEqual(graph[name]["inputs"]["steps"],steps)
            self.assertEqual(graph[name]["inputs"]["seed"],987)
            self.assertEqual(graph[name]["inputs"]["cfg"],cfg)
        self.assertEqual(graph["upsample_stage"]["inputs"]["target_resolution"],1536)
        self.assertEqual(graph["bake"]["inputs"]["texture_size"],4096)
        self.assertEqual(graph["conditioning"]["inputs"]["camera_angle_x"],43.)
        self.assertNotIn("moge",graph)

    def test_shape_only_and_512_do_not_execute_unused_stages(self):
        graph,outputs=build_workflow(ComfyRequest(resolution=512,texture=False,remesh=False,faces=0),{"front":"f.png"},"modelunify/test")
        self.assertNotIn("upsample",graph)
        self.assertNotIn("texture",graph)
        self.assertNotIn("texture_vae",graph)
        self.assertEqual(outputs["result"],outputs["master"])

    def test_working_cleanup_preserves_raw_master_and_bakes_against_it(self):
        graph,outputs=build_workflow(ComfyRequest(remesh_resolution=512,remesh_qef=True,faces=200000),{"front":"f.png"},"modelunify/test")
        self.assertEqual(graph["save_master"]["inputs"]["mesh"],["shape_decode",0])
        self.assertEqual(graph["remesh"]["inputs"]["resolution"],512)
        self.assertTrue(graph["remesh"]["inputs"]["sign_mode.qef"])
        self.assertEqual(graph["decimate"]["inputs"]["target_face_count"],200000)
        self.assertEqual(graph["unwrap"]["inputs"]["mesh"],["decimate",0])
        self.assertEqual(graph["bake"]["inputs"]["reference_mesh"],["shape_decode",0])
        self.assertNotEqual(outputs["result"],outputs["master"])

    def test_malformed_settings_rejected_and_retained_toggle_inert(self):
        for kwargs in ({"resolution":768},{"seed":float("nan")},{"shape_steps":0},{"texture":"false"},{"multiview":True}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):ComfyRequest(**kwargs)
        shape=ShapeRequest.from_settings(BACKENDS[0],{"c_multiview":True})
        self.assertFalse(shape.multiview)
        with self.assertRaises(ValueError):build_workflow(shape,{"front":"f.png","left":"l.png"},"modelunify/test")

    def test_node_schema_and_missing_weights_fail_preflight(self):
        graph={"a":{"class_type":"UNETLoader","inputs":{"unet_name":"missing.safetensors"}}}
        for info in ({},{"UNETLoader":{"input":{"required":{"unet_name":[["installed.safetensors"]]}}}},
                     {"UNETLoader":{"input":{"required":{"unet_name":["COMBO",{"options":["installed.safetensors"]}]}}}}):
            with self.assertRaises(ValueError):check_graph(graph,info)

    def test_saved_projects_restore_comfy_controls(self):
        with TemporaryDirectory() as folder:
            store=ProjectStore(folder);project=store.create("Comfy")
            settings={"backend":BACKENDS[1],"c_multiview":True,"c_shape_steps":28,"c_resolution":1536}
            store.snapshot(project,settings,{"front":Image.new("RGB",(8,8))})
            self.assertEqual(store.load(project)["settings"],settings)

    def test_uploaded_subfolder_image_is_not_rejected_by_stale_ui_combo(self):
        check_graph({"image":{"class_type":"LoadImage","inputs":{"image":"modelunify/new.png"}}},
            {"LoadImage":{"input":{"required":{"image":[["old.png"]]}}}})

    def test_failure_releases_only_an_owned_idle_host(self):
        engine=ComfyEngine(ComfyConfig())
        with patch.object(engine,"_generate",side_effect=ValueError("failed")), \
                patch("scripts.engine_comfyui._owned_process",return_value=object()), \
                patch.object(engine.client,"call",side_effect=[{"queue_running":[],"queue_pending":[]},{}]) as call:
            with self.assertRaisesRegex(ValueError,"failed"):engine.generate({},ComfyRequest(),"unused",lambda *a:None)
            self.assertEqual(call.call_args_list[-1].args,("/free",{"unload_models":True,"free_memory":True}))
        with patch("scripts.engine_comfyui._owned_process",return_value=None),patch.object(engine.client,"call") as call:
            self.assertFalse(engine._release_idle());call.assert_not_called()

    def test_other_pending_jobs_prevent_global_unload(self):
        engine=ComfyEngine(ComfyConfig())
        with patch("scripts.engine_comfyui._owned_process",return_value=object()), \
                patch.object(engine.client,"call",return_value={"queue_pending":[[1,"other-prompt"]]}) as call:
            self.assertFalse(engine._release_idle())
            self.assertEqual(call.call_count,1)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.folder=Path(self.temp.name)
        self.glb=trimesh.creation.box().export(file_type="glb")
        self.requests=[];self.mode="ok";self.history_count=0
        outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,data,code=200):
                payload=data if isinstance(data,bytes) else json.dumps(data).encode()
                self.send_response(code);self.end_headers();self.wfile.write(payload)
            def do_POST(self):
                data=self.rfile.read(int(self.headers.get("Content-Length",0)))
                outer.requests.append((self.path,data))
                if self.path=="/prompt":
                    self.reply({"error":"missing node"},400) if outer.mode=="reject" else self.reply({"prompt_id":"ours","node_errors":{}})
                elif self.path=="/upload/image":self.reply({"name":"image.png","subfolder":"modelunify"})
                elif self.path=="/free":self.reply(b"")
                elif self.path.startswith("/api/jobs/") and outer.mode=="old":self.reply({},404)
                else:self.reply({"cancelled":True})
            def do_GET(self):
                if self.path=="/system_stats":self.reply({"system":{},"devices":[]})
                elif self.path.startswith("/history/"):
                    outer.history_count+=1
                    if outer.mode in ("waiting","old"):self.reply({})
                    elif outer.mode=="failed":self.reply({"ours":{"status":{"status_str":"error","messages":[["execution_error",{"exception_message":"GPU OOM"}]]}}})
                    else:
                        record={"filename":"asset.glb","subfolder":"modelunify/test","type":"output"}
                        self.reply({"ours":{"status":{"completed":True},"outputs":{"save":{"3d":[record]}}}})
                elif self.path.startswith("/view?"):self.reply(b"broken" if outer.mode=="truncated" else outer.glb)
                else:self.reply({},404)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.config=ComfyConfig(url=f"http://127.0.0.1:{self.server.server_port}",poll_interval=.05,job_timeout=.1)
        self.client=ComfyClient(self.config)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def execute(self,checkpoint=lambda *args:None):
        return self.client.execute({"save":{"class_type":"SaveGLB","inputs":{}}},{"result":"save"},self.folder,"modelunify/test",checkpoint)

    def test_successful_http_glb_roundtrip_and_provenance(self):
        uploaded,sha=self.client.upload(Image.new("RGB",(8,8)),"test")
        self.assertEqual(uploaded,"modelunify/image.png");self.assertEqual(len(sha),64)
        paths,report=self.execute()
        mesh=trimesh.load(paths["result"],force="mesh")
        self.assertEqual(len(mesh.faces),12)
        self.assertEqual(report["prompt_id"],"ours")
        self.assertTrue((self.folder/"comfy_workflow.json").is_file())
        self.assertTrue((self.folder/"comfy_history.json").is_file())

    def test_server_error_does_not_publish_an_artifact(self):
        for mode in ("reject","failed","truncated"):
            with self.subTest(mode=mode):
                self.mode=mode
                with self.assertRaises(ComfyError):self.execute()
                self.assertFalse((self.folder/"asset.glb").exists())

    def test_timeout_and_cancel_only_address_our_prompt(self):
        self.mode="waiting"
        with self.assertRaises(TimeoutError):self.execute()
        self.assertIn("/api/jobs/ours/cancel",[p for p,d in self.requests])
        self.assertNotIn("/interrupt",[p for p,d in self.requests])

    def test_cooperative_cancel_keeps_original_exception_and_deletes_only_own_job_on_old_host(self):
        self.mode="old"
        class Cancelled(Exception):pass
        def checkpoint(message,progress):
            if message.startswith("ComfyUI processing"):raise Cancelled("user cancelled")
        with self.assertRaises(Cancelled):self.execute(checkpoint)
        deletion=[json.loads(d) for p,d in self.requests if p=="/queue"]
        self.assertEqual(deletion,[{"delete":["ours"]}])
        self.assertNotIn("/interrupt",[p for p,d in self.requests])

    def test_unrelated_artifacts_and_traversal_rejected(self):
        for filename,subfolder in (("../a.glb","modelunify/test"),("a.glb","../test"),("a.glb","other-job"),("a.obj","modelunify/test")):
            with self.subTest(filename=filename,subfolder=subfolder),self.assertRaises(ComfyError):
                self.client.download({"filename":filename,"subfolder":subfolder,"type":"output"},self.folder/"bad.glb","modelunify/test")

    def test_nonlocal_endpoints_rejected(self):
        for url in ("http://example.com:8188","https://localhost:8188","http://user:pass@localhost:8188","http://localhost:8188/other"):
            with self.subTest(url=url),self.assertRaises(ValueError):ComfyConfig(url=url)

    def test_empty_success_response_from_free_is_valid(self):
        self.assertEqual(self.client.call("/free",{"unload_models":True,"free_memory":True}),{})


if __name__=="__main__":unittest.main()
