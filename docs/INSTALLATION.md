# Install ModelUnify on Windows

Use Windows x64, CPython 3.11 x64 and an NVIDIA CUDA GPU for AI inference.
Edge or Chrome is needed for the dedicated workbench window. CPU mesh tools do
not require NVIDIA; CPU diffusion is very slow. AMD/Intel GPU inference is unwired.

## Create the main environment

From the repository root in PowerShell:

```powershell
.\setup_windows.ps1 -PythonExe 'C:\path\to\Python311\python.exe'
```

This installs the root requirements with their Windows/CUDA constraints. The main
stack uses Torch 2.5.1+cu124, torchvision 0.20.1+cu124, torchaudio 2.5.1+cu124 and
Gradio 6.17.3. Do not install upstream training/demo requirement sets over it.

An existing environment is preserved. To explicitly reconcile its dependencies:

```powershell
.\setup_windows.ps1 -RepairDependencies
.venv/Scripts/python.exe -m pip check
```

If an existing interpreter is broken, retain it and choose another environment
with `-Environment .venv-new -PythonExe <full Python 3.11 path>`. Launchers default
to .venv; use the chosen environment's interpreter explicitly when different.

## Install selected models

Launch the GUI, choose **Models**, and install the checkpoints needed for your
workflow. The [Models workspace](MODEL_WEIGHTS.md#use-the-models-workspace) shows
live progress, verification, dependencies and storage. Weights are not part of Git.
For TRELLIS.2/Pixal3D use its **Install / repair ComfyUI runtime** and **Verify
ComfyUI runtime** actions; keep that environment separate from the main one.
Existing meshes can be edited and exported without restoring AI weights.

## Enable PBR painting

Hunyuan Paint requires NVIDIA CUDA, compiled custom_rasterizer, RealESRGAN and
its Hunyuan/DINO checkpoints. Build native extensions with VS2022 C++ tools and
a CUDA Toolkit matching the main Torch runtime, using `build_paint_extensions.bat`.
The optional mesh-inpaint native module accelerates seam processing; its Python
fallback does not make painting CPU-capable. Keep the vendored Windows patches.

On a 12 GB GPU enable low_vram_mode with mmgp. Actual memory depends on the chosen
settings and workload. Compatible prebuilt modules on an existing workstation
can continue to work; native binaries and Python environments are excluded from Git.

## Launch and check

```powershell
.venv/Scripts/python.exe -m scripts.launch_workbench --check
.venv/Scripts/python.exe -m scripts.workbench_preview --check
.\run_modelunify.bat
```

The first two commands do not run inference. The detailed environment check is
`scripts/check_environment.py --ui`; add `--require-paint` only after installing
paint prerequisites and weights. Check the model-specific readiness before real
generation. See [OPERATING_GUIDE.md](OPERATING_GUIDE.md) for the GUI workflow.

GLB is the preferred exchange format. MAX conversion additionally requires
external Blender and the io_scene_max extension; conversion can flatten hierarchy
or lose UVs. The asset-specific FBX helper is not a general ingest command.
