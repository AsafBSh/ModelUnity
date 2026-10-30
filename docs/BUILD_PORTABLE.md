# Building a Windows portable bundle

The root sources are authoritative. Never edit generated `dist/app` copies.
The builder uses the version in `scripts/_version.py`, Python 3.11.9 x64,
CUDA torch 2.5.1+cu124 and the same Gradio 6.17.3 dependency constraints as
the supported source installation. It includes `scripts/`, **`tools/`** (including InstaLOD staging
and recipes), vendored sources/licenses, assets, documentation and config.

```powershell
# Read-only: prints resolved paths and packaging choices; creates nothing.
.\build_portable.ps1 -PlanOnly
# Fresh release directory; an existing directory/archive is always refused.
.\build_portable.ps1 -OutputDirectory dist/release-candidate-001 -SkipArchive
# Faster development copy; not proof of a reproducible release.
.\build_portable.ps1 -FromVenv -OutputDirectory dist/dev-001 -SkipArchive
```

Outputs must be new directories under this workspace's `dist/`. The builder
never recursively cleans an old bundle, scratch directory, model cache, or user
results. Each build gets unique scratch space. Archive paths follow the chosen
output directory. Do not delete old distributions before inspecting their user
inputs/results/caches and backing them up. The optional installer preserves
generated models, inputs, checkpoints and caches on uninstall.

Default packaging is **without native paint support**. Learned weights/checkpoints and native
artifacts are excluded from the source copy. In v1.12, users install and verify
models explicitly from the **Models** workspace before inference. Startup and
inference do not install missing models.
Paint is an explicit build choice:

```powershell
.\build_portable.ps1 -IncludePaint -PaintWheelDirectory C:\build\paint-wheels `
  -OutputDirectory dist/paint-release-001 -SkipArchive
```

For a clean paint build, provide a custom rasterizer wheel for **CPython 3.11
win_amd64**, compiled against the selected torch/CUDA ABI. Build native code
with VS2022 C++ tools and CUDA Toolkit **12.4**; the installed 12.6 toolkit
must not be silently substituted. `build_paint_extensions.bat` discovers tools
and checks the toolkit match. Keep vendor Windows patches. An optional matching
`mesh_inpaint_processor.cp311-win_amd64.pyd` from DifferentiableRenderer is
copied explicitly when paint is selected; otherwise its Python fallback is used.

`-IncludePaint` also requires the external
`vendor/Hunyuan3D-2.1/hy3dpaint/ckpt/RealESRGAN_x4plus.pth` checkpoint, which is
copied explicitly. This legacy packaging prerequisite is separate from the
workbench's verified model registry; install the required Hunyuan/DINO and
support weights through **Models** before using paint. Review each source/weight license before redistribution; no license
is changed by packaging. `-FromVenv -IncludePaint` copies installed native
packages and is useful for local testing, but remains a development shortcut.
Paint requires NVIDIA CUDA; there is no CPU/AMD/Intel GPU painting fallback.

For local validation, an already working rasterizer can also be exported to a
wheel without recompiling it:

```powershell
.venv/Scripts/python.exe tools/packaging/export_paint_wheel.py --output .runtime/paint-wheels
```

This requires the validated Windows x64 CPython 3.11 / torch 2.5.1+cu124 runtime.
The wheel includes the upstream license, native-file hashes and binary-reuse
provenance. It is **not** a fresh CUDA source build or evidence for other ABIs.
Pass that directory to `-PaintWheelDirectory` for a new `-IncludePaint` build.

Before archiving, the builder runs `pip check` and offline copied-source UI
construction. Paint builds additionally require paint prerequisite imports and
the checkpoint. The editable hy3dgen finder is rewritten for relocation;
the engine also prioritizes the vendor directory beside the copied source.
Only `__pycache__` is trimmed; runtime-imported package tests are retained.
7-Zip is needed unless `-SkipArchive` is passed. MSVC/CUDA Toolkit are needed
to build native wheels, not to execute already compatible binaries.

Release validation still requires a **clean** build, moving the bundle to a
different path, launching without the development venv/PATH, and real shape and
paint inference on a clean Windows/NVIDIA machine. Check `instalod-stage --help`
and a temporary staging operation in the copied app. Confirm user data stays
inside the intended bundle directories. Inno Setup (`packaging/installer.iss`)
and a clean-machine installer/uninstaller test are separate optional checks.
Use `packaging/build_installer.ps1 -ISCC <path-to-ISCC.exe>`; it reads the
version from `scripts/_version.py` and accepts `-BundleDirectory` for a fresh
release candidate. `-PlanOnly` prints its inputs without compiling. Direct
ISCC calls must provide the same `MyAppVersion` definition explicitly.
Neither `-PlanOnly` nor import checks establish release portability.

The v1.12 Models workspace requires a fresh portable validation pass, including
downloads, cancellation/resume, model-folder selection and runtime verification
after relocation. Existing published bundles are unchanged by source updates.

After validating a candidate, create a fresh archive without QA/user data:

```powershell
.\packaging\archive_candidate.ps1 -BundleDirectory 'dist/release-candidate-001' `
  -OutputArchive dist/ModelUnify-release-candidate-001.7z
```

This preserves the candidate folder, refuses existing output archives, excludes
projects/inputs/outputs/caches/window profiles/Studio inboxes, verifies CRCs and
checks for unexpected user-data entries, then writes a SHA-256 companion file.

Portable `run.bat` keeps Hugging Face modules, Torch, Hunyuan, rembg, matplotlib,
Numba and temporary caches under the bundle. `run.bat --check` reports the active
paths. `--server --port 7862` runs in the foreground for Ctrl+C shutdown. The
default application-window server stays alive after the window closes.
## Optional Comfy runtime delivery

New builds include `Setup ComfyUI.bat`; Inno tasks offer TRELLIS.2, Pixal single,
Pixal fixed-orbit multiview or all. Runtime source, packages and weights are
installed explicitly after the base application, never into its embedded Python.
The private full-Python bootstrap supports a machine without Python/Git on PATH;
see COMFYUI.md for preflight, signature verification and separate validation gates.
Installer tasks require interactive setup; silent setup does not start downloads.

`packaging/build_installer.ps1 -OutputName 'ModelUnify-release-candidate-001-Setup'`
selects a fresh plain output name. Existing installers/bundles are preserved.
Compilation still requires Inno Setup; a plan-only check is not compilation.

