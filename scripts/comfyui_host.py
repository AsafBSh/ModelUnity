"""Install, inspect and manage ModelUnify's separate local ComfyUI host.

Explicit setup only: the GUI never installs code or checkpoints on Generate.
Run with the ModelUnify interpreter, not ComfyUI's interpreter.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from scripts.engine_comfyui import ComfyEngine, config_from_dict, start_host, stop_host
from scripts.comfyui_workflows import BACKENDS, WEIGHTS, ComfyRequest

COMFY_REVISION = "7a28332047b6af638dc6c7f72ef3481a718769fd"
SOURCES = {
    "trellis":("Comfy-Org/TRELLIS.2","diffusion_models"),
    "pixal":("Comfy-Org/Pixal3D","diffusion_models"),
    "pixal_mv":("Comfy-Org/Pixal3D","diffusion_models"),
    "shape_vae":("Comfy-Org/Pixal3D","vae"),
    "texture_vae":("Comfy-Org/Pixal3D","vae"),
    "vision":("Comfy-Org/Pixal3D","clip_vision"),
    "moge":("Comfy-Org/MoGe","geometry_estimation"),
}


def load_config():
    import yaml
    return config_from_dict(yaml.safe_load((ROOT/"config.yaml").read_text(encoding="utf-8")))


def setup(config):
    """Idempotent private installation; never pip-install into the app environment."""
    host = config.path(config.server_dir)
    python = config.path(config.python_exe)
    if python.resolve() == Path(sys.executable).resolve():
        raise ValueError("Choose a separate ComfyUI Python environment in config.yaml.")
    host.parent.mkdir(parents=True,exist_ok=True)
    if not host.exists():
        from scripts.comfyui_install import install_source
        install_source(host,COMFY_REVISION)
    elif not (host/"main.py").is_file():
        raise ValueError("Configured ComfyUI directory exists but has no main.py; it was not overwritten.")
    if not python.exists():
        env_root = python.parent.parent
        if env_root.exists() and any(env_root.iterdir()):
            raise ValueError("Configured Python environment is nonempty but has no interpreter; choose a fresh path.")
        from scripts.comfyui_install import base_python
        subprocess.run([str(base_python(host.parent)),"-m","venv",str(env_root)],check=True)
    run = lambda args:subprocess.run([str(python),"-m","pip",*args,"--disable-pip-version-check","--no-cache-dir"],check=True)
    run(["install","torch==2.14.1","torchvision==0.29.1","--index-url","https://download.pytorch.org/whl/cu130"])
    run(["install","-r",str(host/"requirements.txt")])
    # Native mesh I/O and CPU UV/baking nodes lazy-load these dependencies.
    run(["install","trimesh","scikit-image","scikit-learn","huggingface-hub"])
    subprocess.run([str(python),"-c","import torch; assert torch.cuda.is_available(), 'CUDA unavailable: verify NVIDIA driver'; print(torch.cuda.get_device_name(0))"],check=True)
    print("Isolated ComfyUI runtime installed. Check NVIDIA driver compatibility with CUDA 13.0.")


def download_models(config, selection):
    from huggingface_hub import HfApi, hf_hub_download
    from scripts.workbench.projects import atomic_json
    keys = ["shape_vae","texture_vae","vision"]
    keys += ["trellis","pixal","pixal_mv","moge"] if selection=="all" else [selection.replace("-","_")]
    if selection=="pixal":
        keys.append("moge")
    models = config.path(config.server_dir)/"models"
    models.mkdir(parents=True,exist_ok=True)
    manifest_path = models/"modelunify_downloads.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    api, revisions = HfApi(),{}
    for key in keys:
        repo,subfolder = SOURCES[key]
        filename = config.weights.get(key,WEIGHTS[key])
        if filename != WEIGHTS[key]:
            raise ValueError(f"Custom checkpoint {key}: place it manually in models/{subfolder}; download uses official names only.")
        revisions.setdefault(repo,api.model_info(repo).sha)
        remote = subfolder+"/"+filename
        print(f"Downloading {repo}/{remote} at {revisions[repo]}",flush=True)
        path = hf_hub_download(repo,remote,revision=revisions[repo],local_dir=models)
        manifest[key] = {"repo":repo,"revision":revisions[repo],"filename":remote,"bytes":Path(path).stat().st_size}
        atomic_json(manifest_path,manifest)
    print("Selected weights installed. Their upstream model licenses still apply.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["plan","setup","download","start","status","stop"])
    parser.add_argument("--model",choices=["trellis","pixal","pixal-mv","all"],default="trellis",
                        help="setup/download: checkpoints to install; status: model to check")
    parser.add_argument("--skip-models",action="store_true",help="Install runtime without multi-GB weights")
    args = parser.parse_args()
    config = load_config()
    if args.action in ("plan","setup","download"):
        from scripts.comfyui_install import plan
        report=plan(config,args.model,args.skip_models)
        print(json.dumps(report,indent=2),flush=True)
        if args.action=="plan":return 0 if report["ready"] else 1
        if report["errors"]:raise ValueError("Setup preflight failed: "+" ".join(report["errors"]))
    if args.action=="setup":
        from filelock import FileLock
        lock=config.path(config.server_dir).parent/"setup.lock";lock.parent.mkdir(parents=True,exist_ok=True)
        with FileLock(str(lock),timeout=0):
            setup(config)
            if not args.skip_models:download_models(config,args.model)
    elif args.action=="download":
        from filelock import FileLock
        lock=config.path(config.server_dir).parent/"setup.lock";lock.parent.mkdir(parents=True,exist_ok=True)
        with FileLock(str(lock),timeout=0):download_models(config,args.model)
    elif args.action=="start":
        print(json.dumps(start_host(config),indent=2))
    elif args.action=="stop":
        print(stop_host(config))
    else:
        request = ComfyRequest(backend=BACKENDS[0] if args.model in ("trellis","all") else BACKENDS[1],multiview=args.model=="pixal-mv")
        result = ComfyEngine(config).readiness(request)
        print(json.dumps(result,indent=2))
        return 0 if result["ready"] else 1
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (ValueError,RuntimeError,subprocess.CalledProcessError,TimeoutError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(1)
