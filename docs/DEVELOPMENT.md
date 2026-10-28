# Windows development environment

Use CPython **3.11 x64**, NVIDIA CUDA torch **2.5.1+cu124**, torchvision
**0.20.1+cu124**, torchaudio **2.5.1+cu124**, and Gradio **6.17.3**. The UI
and launcher use Gradio 6 APIs. `requirements-windows-lock.txt` constrains the
dependency versions; `requirements-cuda124.txt` protects CUDA wheels during
resolution. `scripts/_version.py` is the application version source.

```powershell
# Fresh environment; use the full path to an installed Python 3.11 interpreter.
.\setup_windows.ps1 -PythonExe 'C:\path\to\Python311\python.exe'
# Existing environment: inspect/save its package state first, then explicitly repair.
.\setup_windows.ps1 -RepairDependencies
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\check_environment.py --ui --require-paint
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Setup never deletes or recreates an existing environment. A broken one can be
preserved while creating another with `-Environment .venv-new`. Launchers use
`.venv` by default; use the other environment's explicit interpreter if chosen.
Do not treat activation as a repair mechanism. If Python reports a missing
base executable, test that executable directly under the owning user: on this
machine the sandbox denied its execution, while `.venv` worked outside it.

The 2026-10-19 repair retained the environment and CUDA packages, changed
`optimum-quanto` from 0.2.7 to **0.2.6** (0.2.7 requires torch >=2.6), and
changed SymPy from 1.14.0 to **1.13.1** (torch's requirement). Prior package
versions are retained locally in `.runtime/development-before.txt`. The signed
Python 3.11.9 installer downloaded during diagnosis is in `.runtime`; it did
not produce a replacement workspace runtime. No system PATH change was made.

Do **not** install the entire upstream requirements files over this environment:
they include conflicting NumPy, Gradio and training/demo pins, `bpy`, and
Linux-focused build dependencies. Root requirements describe the inference
wrapper. Optional FBX-helper dependencies are listed separately in
`requirements-optional.txt`; `.max` needs `olefile`, external Blender, and the
external GPL-2.0 `io_scene_max` extension. The FBX helper uses `fbxloader` and
contains asset-specific code; it is not a supported general ingest command.

Paint needs NVIDIA CUDA, the native custom rasterizer, and the external
`vendor/Hunyuan3D-2.1/hy3dpaint/ckpt/RealESRGAN_x4plus.pth` checkpoint, plus
the Hunyuan/DINO weights downloaded by upstream. Their licenses still apply.
The optional compiled mesh-inpaint module improves the CPU seam stage; its
Python fallback does not make the painter CPU-capable. Windows native builds
use `build_paint_extensions.bat`, which discovers VS Build Tools and requires
a CUDA Toolkit matching torch's **12.4** runtime. This machine currently has
Toolkit **12.6**; importing existing extensions works, but rebuilding against
12.4 requires installing/selecting that toolkit explicitly.

Shape CPU fallback is slow. AMD ROCm and Intel XPU are not integrated. Do not
replace the supported CUDA stack with generic PyPI torch wheels. Existing
vendor patches are required and must be preserved.

## CAD workbench development

Use `run_modelunify.bat` for the dedicated window, or
`.venv/Scripts/python.exe -m scripts.workbench_preview --no-open` for a visible
server session. The original interface remains available with `--legacy` on the
new launcher. See [WORKBENCH.md](WORKBENCH.md) for service ownership, saved
projects, isolated workers, cancellation and validation commands. Do not edit
the generated dist copies. Native workers use UTF-8 logs on Windows.
