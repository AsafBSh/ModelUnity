"""Launch ModelUnify in a dedicated Windows application window.

Uses the installed Edge/Chrome engine in app mode, with a private profile.
The local server persists when the window closes so queued work can finish.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import yaml
from urllib.request import urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from scripts.app_identity import instance_marker
from scripts._version import MODELUNIFY_VERSION
_config=yaml.safe_load((ROOT/"config.yaml").read_text(encoding="utf-8"))
RUNTIME = ROOT / _config.get("paths",{}).get("workbench_runtime_dir",".runtime/workbench_preview")

def browser_path():
    candidates = []
    for variable in ("PROGRAMFILES(X86)","PROGRAMFILES","LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.extend((Path(base)/"Microsoft/Edge/Application/msedge.exe",Path(base)/"Google/Chrome/Application/chrome.exe"))
    candidates.extend(Path(p) for name in ("msedge","google-chrome","chromium","chromium-browser") if (p:=shutil.which(name)))
    return next((path for path in candidates if path.is_file()),None)

def identity(port):
    try:
        with urlopen(f"http://127.0.0.1:{port}/config",timeout=2) as response:
            config = json.load(response)
            return (isinstance(config,dict) and config.get("title") == "ModelUnify · Mesh Workbench"
                    and instance_marker(ROOT) in (config.get("head") or ""))
    except (URLError,TimeoutError,OSError,ValueError):
        return False

def process_options():
    return {"creationflags":subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {"start_new_session":True}

def available_port():
    """Reconnect to this installation, or find a free local application port."""
    import socket
    first_free = None
    # Hyper-V/Windows can reserve an unoccupied port: connect_ex alone cannot
    # distinguish that from a bindable socket. Keep a second application range.
    for port in (*range(7861,7882),*range(17861,17882)):
        with socket.socket() as sock:
            sock.settimeout(.5)
            occupied = sock.connect_ex(("127.0.0.1",port)) == 0
        if not occupied:
            try:
                # A failed connect may already bind a Windows socket to an
                # ephemeral local endpoint. Bind using a fresh socket instead.
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1",port))
            except OSError:
                continue
            first_free = first_free or port
        if occupied and identity(port):
            return port
    if first_free is not None:
        return first_free
    raise RuntimeError("No bindable workbench port is available. Choose a free --port.")

def startup_status(message):
    print(f"ModelUnify: {message}", flush=True)


def wait_for_server(process, port, log_path, timeout=240):
    """Keep a cold startup visible while the UI imports its local libraries."""
    started = time.monotonic()
    last_report = -5.0
    while not identity(port):
        if process.poll() is not None:
            raise RuntimeError(f"Workbench startup failed. See {log_path}")
        elapsed = time.monotonic() - started
        if elapsed >= timeout:
            raise TimeoutError(f"Workbench is still starting. See {log_path}")
        if elapsed - last_report >= 5:
            startup_status(f"Loading workbench... {elapsed:.0f}s elapsed. First startup can take a few minutes.")
            last_report = elapsed
        time.sleep(.5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,help="Fixed local port; otherwise reconnect or choose an available port from 7861")
    parser.add_argument("--browser",action="store_true",help="Open in the default browser instead of an application window")
    parser.add_argument("--legacy",action="store_true",help="Launch the original UI on port 7860")
    parser.add_argument("--server",action="store_true",help="Run a foreground workbench server without opening a window; Ctrl+C stops it")
    parser.add_argument("--check",action="store_true",help="Report launcher readiness without starting the server")
    args = parser.parse_args(argv)
    if args.port is not None and not 1<=args.port<=65535:
        parser.error("--port must be between 1 and 65535")
    if not args.check:
        startup_status(f"v{MODELUNIFY_VERSION} - checking the local server...")
    args.port = args.port if args.port is not None else available_port()
    browser = browser_path()
    if args.check:
        print(json.dumps({"python":sys.executable,"root":str(ROOT),"window_engine":str(browser) if browser else None,
                          "port":args.port,"server_running":identity(args.port),
                          "cache_paths":{key:os.environ[key] for key in ("HF_HOME","HF_MODULES_CACHE","TORCH_HOME",
                              "HY3DGEN_MODELS","U2NET_HOME","MPLCONFIGDIR","NUMBA_CACHE_DIR","TEMP") if key in os.environ}},indent=2))
        return 0 if browser or args.browser or args.server else 1
    if args.legacy:
        return subprocess.call([sys.executable,str(ROOT/"scripts"/"launch_webui.py")],cwd=ROOT)
    if args.server:
        return subprocess.call([sys.executable,"-u",str(ROOT/"scripts"/"workbench_preview.py"),
                                "--port",str(args.port),"--no-open"],cwd=ROOT)
    if not browser and not args.browser:
        raise RuntimeError("Install Microsoft Edge or Chrome for the application window, or use --browser.")
    RUNTIME.mkdir(parents=True,exist_ok=True)
    if not identity(args.port):
        # A bound unrelated application must never be mistaken for ModelUnify.
        import socket
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1",args.port))==0:
                raise RuntimeError(f"Port {args.port} is occupied by another app or ModelUnify installation. Choose another --port.")
        log_path = RUNTIME/"server.log"
        startup_status("Starting local UI, mesh tools and GPU libraries...")
        startup_status(f"Live startup log: {log_path}")
        with log_path.open("ab") as log:
            log.write(f"\n--- ModelUnify v{MODELUNIFY_VERSION} startup on port {args.port} ---\n".encode("utf-8"))
            log.flush()
            process = subprocess.Popen([sys.executable,"-u",str(ROOT/"scripts"/"workbench_preview.py"),"--port",str(args.port),"--no-open"],
                                       cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,**process_options())
        (RUNTIME/"server.pid").write_text(str(process.pid))
        wait_for_server(process,args.port,log_path)
    else:
        startup_status(f"Reusing this installation's running server on port {args.port}.")
    url = f"http://127.0.0.1:{args.port}/?__theme=dark"
    startup_status(f"Workbench ready: {url}")
    if args.browser:
        import webbrowser
        webbrowser.open(url)
    else:
        subprocess.Popen([str(browser),"--app="+url,"--user-data-dir="+str(RUNTIME/"window-profile"),
                          "--no-first-run","--disable-background-mode","--window-size=1440,960",
                          "--class=ModelUnify"],cwd=ROOT)
    startup_status("Window opened. Jobs continue on the local server after closing the window.")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ModelUnify: {exc}",file=sys.stderr)
        if os.name=="nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,str(exc),"ModelUnify startup",0x10)
        raise SystemExit(1)
