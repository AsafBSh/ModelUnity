"""Prevent a portable launcher from adopting a development or unrelated server."""
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock
from contextlib import redirect_stdout

from scripts import launch_workbench as launcher
from scripts.app_identity import instance_marker


class LauncherIdentityTests(unittest.TestCase):
    def test_failed_connect_socket_is_not_reused_for_bind_probe(self):
        class WindowsSocket:
            def __init__(self):self.connected=False
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def settimeout(self,*_):pass
            def connect_ex(self,*_):self.connected=True;return 1
            def bind(self,*_):
                if self.connected:raise OSError('Failed connect has already assigned a local endpoint')
        with patch('socket.socket',side_effect=WindowsSocket):
            self.assertEqual(launcher.available_port(),7861)

    def test_reserved_windows_port_is_not_treated_as_free(self):
        with patch.object(launcher,'identity',return_value=False),patch('socket.socket') as sock:
            sock.return_value.__enter__.return_value.connect_ex.return_value=1
            def bind(address):
                if address[1]==7861:raise PermissionError('Windows reserved this port')
            sock.return_value.__enter__.return_value.bind.side_effect=bind
            self.assertEqual(launcher.available_port(),7862)

    def test_reconnects_to_owned_server_in_fallback_range(self):
        with patch.object(launcher,'identity',side_effect=lambda port:port==17861),patch('socket.socket') as sock:
            sock.return_value.__enter__.return_value.connect_ex.side_effect=lambda address:0 if address[1]==17861 else 1
            self.assertEqual(launcher.available_port(),17861)

    def test_default_port_skips_another_installation_and_reconnects(self):
        with patch.object(launcher,"identity",side_effect=lambda port:port==7863), patch("socket.socket") as sock:
            sock.return_value.__enter__.return_value.connect_ex.side_effect=lambda address:1 if address[1]==7862 else 0
            self.assertEqual(launcher.available_port(),7863)

    def identity(self, head):
        response = io.BytesIO(json.dumps({"title":"ModelUnify · Mesh Workbench", "head":head}).encode())
        with patch.object(launcher,"urlopen",return_value=response):
            return launcher.identity(7861)

    def test_reuses_only_the_same_installation(self):
        self.assertTrue(self.identity(instance_marker(launcher.ROOT)))
        self.assertFalse(self.identity(instance_marker(launcher.ROOT / "another-installation")))

    def test_title_alone_and_missing_marker_are_insufficient(self):
        self.assertFalse(self.identity(""))
        self.assertFalse(self.identity(None))
        with patch.object(launcher,"urlopen",return_value=io.BytesIO(b"[]")):
            self.assertFalse(launcher.identity(7861))

    def test_occupied_foreign_port_is_never_adopted_or_overwritten(self):
        with patch.object(launcher,"identity",return_value=False), \
             patch.object(launcher,"browser_path",return_value=Path("browser.exe")), \
             patch("socket.socket") as sock, patch.object(launcher.subprocess,"Popen") as spawn:
            sock.return_value.__enter__.return_value.connect_ex.return_value=0
            with self.assertRaisesRegex(RuntimeError,"another.*installation"):
                launcher.main(["--port","7861"])
            spawn.assert_not_called()

    def test_foreground_mode_uses_the_selected_port_without_a_browser(self):
        with patch.object(launcher,"browser_path",return_value=None), \
             patch.object(launcher.subprocess,"call",return_value=0) as call:
            self.assertEqual(launcher.main(["--server","--port","7871"]),0)
            self.assertEqual(call.call_args.args[0], [launcher.sys.executable,"-u",
                str(launcher.ROOT / "scripts/workbench_preview.py"),"--port","7871","--no-open"])

    def test_wait_reports_elapsed_time_until_server_is_ready(self):
        output = io.StringIO()
        process = Mock()
        process.poll.return_value = None
        with patch.object(launcher,"identity",side_effect=[False,False,True]), \
             patch.object(launcher.time,"monotonic",side_effect=[100,105,110]), \
             patch.object(launcher.time,"sleep") as sleep, redirect_stdout(output):
            launcher.wait_for_server(process,7861,Path("server.log"))
        self.assertIn("5s elapsed",output.getvalue())
        self.assertIn("10s elapsed",output.getvalue())
        self.assertEqual(sleep.call_count,2)

    def test_failed_startup_points_to_current_log(self):
        process = Mock()
        process.poll.return_value = 1
        with patch.object(launcher,"identity",return_value=False):
            with self.assertRaisesRegex(RuntimeError,"startup failed.*server.log"):
                launcher.wait_for_server(process,7861,Path("server.log"))

    def test_slow_startup_times_out_without_terminating_server(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(launcher,"identity",return_value=False), \
             patch.object(launcher.time,"monotonic",side_effect=[100,341]):
            with self.assertRaisesRegex(TimeoutError,"still starting.*server.log"):
                launcher.wait_for_server(process,7861,Path("server.log"))
        process.terminate.assert_not_called()

    def test_check_stays_json_only(self):
        output = io.StringIO()
        with patch.object(launcher,"identity",return_value=True), \
             patch.object(launcher,"browser_path",return_value=Path("browser.exe")), redirect_stdout(output):
            self.assertEqual(launcher.main(["--check","--port","7861"]),0)
        self.assertTrue(json.loads(output.getvalue())["server_running"])

    def test_new_server_uses_unbuffered_output_and_marks_log(self):
        with TemporaryDirectory() as folder, \
             patch.object(launcher,"RUNTIME",Path(folder)), \
             patch.object(launcher,"identity",return_value=False), \
             patch.object(launcher,"browser_path",return_value=None), \
             patch.object(launcher,"wait_for_server") as wait, \
             patch("socket.socket") as sock, \
             patch.object(launcher.subprocess,"Popen") as spawn, \
             patch("webbrowser.open",return_value=True):
            sock.return_value.__enter__.return_value.connect_ex.return_value=1
            spawn.return_value.pid=1234
            self.assertEqual(launcher.main(["--browser","--port","7861"]),0)
            self.assertEqual(spawn.call_args.args[0][:2],[launcher.sys.executable,"-u"])
            wait.assert_called_once_with(spawn.return_value,7861,Path(folder)/"server.log")
            self.assertIn(f"ModelUnify v{launcher.MODELUNIFY_VERSION} startup",(Path(folder)/"server.log").read_text())

    def test_ready_server_is_reused_without_spawning_another(self):
        with TemporaryDirectory() as folder, \
             patch.object(launcher,"RUNTIME",Path(folder)), \
             patch.object(launcher,"identity",return_value=True), \
             patch.object(launcher,"browser_path",return_value=None), \
             patch.object(launcher.subprocess,"Popen") as spawn, \
             patch("webbrowser.open",return_value=True), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(launcher.main(["--browser","--port","7861"]),0)
            spawn.assert_not_called()
            self.assertIn("Reusing",output.getvalue())
            self.assertIn("Workbench ready: http://127.0.0.1:7861",output.getvalue())


if __name__ == "__main__":
    unittest.main()
