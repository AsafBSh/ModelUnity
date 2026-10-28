"""Explicit optional-runtime provisioning, including embeddable Windows bundles."""
from pathlib import Path, PurePosixPath
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import base64
from urllib.request import urlopen
import zipfile

SIZES={"trellis":5253048192,"pixal":5584555824,"pixal_mv":5584555824,"shape_vae":1095844024,
       "texture_vae":948461364,"vision":1215214176,"moge":661859924}


def selected_keys(selection):
    if selection not in ("trellis","pixal","pixal-mv","all"):raise ValueError("Unknown model selection.")
    keys=["shape_vae","texture_vae","vision"]
    keys+= ["trellis","pixal","pixal_mv","moge"] if selection=="all" else [selection.replace("-","_")]
    if selection=="pixal":keys.append("moge")
    return keys


def plan(config,selection,skip_models=False):
    from scripts.comfyui_workflows import WEIGHTS
    from scripts.comfyui_host import SOURCES
    host=config.path(config.server_dir);parent=host.parent
    existing=parent
    while not existing.exists():existing=existing.parent
    free=shutil.disk_usage(existing).free;models=[];missing=0
    selected=selected_keys(selection)
    for key in [] if skip_models else selected:
        filename=config.weights.get(key,WEIGHTS[key]);path=host/"models"/SOURCES[key][1]/filename
        present=path.is_file() and path.stat().st_size>=SIZES[key]
        models.append({"model":key,"file":str(path),"installed":present,"estimated_bytes":SIZES[key]})
        if not present:missing+=SIZES[key]
    runtime_python=config.path(config.python_exe)
    torch_lib=runtime_python.parent.parent/"Lib/site-packages/torch/lib/torch_cuda.dll"
    runtime=runtime_python.is_file() and (host/"main.py").is_file() and torch_lib.is_file()
    required=missing+(2 if runtime else 14)*1024**3
    errors=[];warnings=[];gpu=[]
    try:
        probe=subprocess.run(["nvidia-smi","--query-gpu=name,driver_version,memory.total","--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=15,
            **({"creationflags":subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {}))
        if probe.returncode:raise RuntimeError(probe.stderr.strip())
        for line in probe.stdout.splitlines():
            name,driver,memory=[p.strip() for p in line.split(",")]
            gpu.append({"name":name,"driver":driver,"vram_mib":int(memory)})
        if not gpu:errors.append("No NVIDIA GPU detected.")
        if gpu and any(int(g["driver"].split(".")[0])<580 for g in gpu):errors.append("The selected CUDA 13 runtime requires an R580-or-newer NVIDIA driver family; update the driver and verify CUDA readiness.")
    except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:errors.append("Cannot verify NVIDIA driver: "+str(exc))
    if free<required:errors.append(f"Insufficient free space: {free/1024**3:.1f} GiB available, {required/1024**3:.1f} GiB estimated needed including scratch/headroom.")
    if os.name!="nt":warnings.append("Windows is the primary validation target; this runtime/installer path is not a Linux support certification.")
    warnings.append("Upstream checkpoint licenses apply. VRAM capacity does not guarantee a selected resolution will fit.")
    return {"ready":not errors,"errors":errors,"warnings":warnings,"selection":selection,"runtime_installed":runtime,
        "runtime_python":str(config.path(config.python_exe)),"host_directory":str(host),"gpu":gpu,
        "free_bytes":free,"estimated_required_bytes":required,"models":models,
        "driver_check":"Driver family check plus post-install torch CUDA probe; https://docs.nvidia.com/cuda/archive/13.0.3/cuda-toolkit-release-notes/index.html"}


def download(url,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix(path.suffix+".part")
    try:
        with urlopen(url,timeout=60) as source,temporary.open("wb") as target:shutil.copyfileobj(source,target,1024*1024)
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)
    return path


def install_source(host,revision):
    host=Path(host).resolve();host.parent.mkdir(parents=True,exist_ok=True)
    archive=download(f"https://github.com/Comfy-Org/ComfyUI/archive/{revision}.zip",host.parent/f"ComfyUI-{revision}.zip")
    prefix=f"ComfyUI-{revision}"
    with tempfile.TemporaryDirectory(prefix="source-",dir=host.parent) as temporary:
        root=Path(temporary).resolve()
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                name=PurePosixPath(item.filename)
                if name.is_absolute() or ".." in name.parts or "\\" in item.filename or not name.parts or name.parts[0]!=prefix:
                    raise ValueError("Unsafe ComfyUI archive path.")
                destination=(root/Path(*name.parts)).resolve()
                if not destination.is_relative_to(root) or (item.external_attr>>16)&0o170000==0o120000:raise ValueError("Unsafe archive member.")
                if item.is_dir():destination.mkdir(parents=True,exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    with bundle.open(item) as source,destination.open("wb") as target:shutil.copyfileobj(source,target)
        extracted=(root/prefix).resolve()
        if not extracted.is_relative_to(root) or host.exists():raise ValueError("Source destination already exists or is unsafe; nothing overwritten.")
        extracted.rename(host)
    (host/"modelunify_source.json").write_text(json.dumps({"revision":revision,"source":"Comfy-Org/ComfyUI"}),encoding="utf-8")


def base_python(parent):
    embedded=Path(sys.executable).with_name(f"python{sys.version_info.major}{sys.version_info.minor}._pth").is_file()
    if not embedded and importlib.util.find_spec("venv") and importlib.util.find_spec("ensurepip"):return Path(sys.executable)
    if os.name!="nt":raise ValueError("A full Python with venv/ensurepip is required for this runtime.")
    target=Path(parent).resolve()/"base_python311";python=target/"python.exe"
    if python.is_file():return python
    # Reuse a registered full Python without requiring Python/Git on PATH and
    # without invoking a same-version installer in maintenance mode.
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive,r"Software\Python\PythonCore\3.11\InstallPath") as key:
                try:candidate=Path(winreg.QueryValueEx(key,"ExecutablePath")[0])
                except OSError:candidate=Path(winreg.QueryValueEx(key,"")[0])/"python.exe"
            if candidate.is_file():
                subprocess.run([str(candidate),"-c","import venv,ensurepip,sys; assert sys.version_info[:2]==(3,11)"],
                    check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                return candidate
        except (OSError,subprocess.CalledProcessError):pass
    installer=download("https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe",Path(parent)/"python-3.11.9-amd64.exe")
    # Execute only a valid PSF-signed installer; never change global PATH/launcher.
    quoted=str(installer).replace("'","''")
    command="$s=Get-AuthenticodeSignature -LiteralPath '"+quoted+"'; if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notlike '*Python Software Foundation*') { exit 1 }"
    flags={"creationflags":subprocess.CREATE_NO_WINDOW}
    subprocess.run(["powershell","-NoProfile","-NonInteractive","-EncodedCommand",base64.b64encode(command.encode("utf-16le")).decode()],check=True,**flags)
    subprocess.run([str(installer),"/quiet","InstallAllUsers=0",f"TargetDir={target}","PrependPath=0","Include_launcher=0",
        "AssociateFiles=0","Shortcuts=0","Include_test=0","Include_doc=0","Include_tcltk=0","Include_pip=1"],check=True,**flags)
    if not python.is_file():raise RuntimeError("Private Python installation did not produce an interpreter.")
    return python
