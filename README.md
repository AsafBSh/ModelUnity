# ModelUnify — Integrated 3D AI Creation

> Product name: **ModelUnify v1.11.2**. See [release history](CHANGELOG.md).
> Existing v1.0 portable builds retain their original version until rebuilt.
> This repo folder may still be named `3D AI Generator`.

Start with the [practical operating guide](docs/OPERATING_GUIDE.md) or its
[Word edition](docs/ModelUnify_Operating_Guide.docx). Downloaded model weights,
Python runtimes and generated/private assets are excluded from Git. Restore
selected models using [MODEL_WEIGHTS.md](docs/MODEL_WEIGHTS.md); existing mesh
inspection and CPU tools remain usable without AI checkpoints. Fresh clones need
the environment setup in [DEVELOPMENT.md](docs/DEVELOPMENT.md).

New accuracy/authoring tools: manual mask correction, reference silhouette
overlays, protected optimization, UV repair/PBR rebaking and general/static-BMS
export handoff. See the [usage and limitations guide](docs/ACCURACY_AUTHORING.md).

Turn satellite and/or ground-level photos of a building (or any object) into
a 3D mesh. **Primary workflow:** Falcon BMS custom objects (LOD export → `.bml`).
**Also supports:** 3D presentation, 3D printing, and gaming asset prototyping.

**Shape generation and PBR texturing:**

| Backend | Input | Best for | Repo |
|---|---|---|---|
| **TripoSG 1.5B** (VAST-AI / Tripo AI) | Single image | Highest geometric fidelity from one shot | [VAST-AI/TripoSG](https://huggingface.co/VAST-AI/TripoSG) |
| **Hunyuan3D-2mv** (Tencent) | **1–4 views** (front / left / back / right) | Buildings — fuses ground + satellite views into one mesh | [tencent/Hunyuan3D-2mv](https://huggingface.co/tencent/Hunyuan3D-2mv) |
| **Hunyuan3D-2.1 Paint** (Tencent) | Mesh + reference image | Albedo + metallic/roughness PBR textures (NVIDIA CUDA only) | [upstream](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1) |
| **TRELLIS.2 via ComfyUI** | Single image | Shape + optional PBR; retained raw geometry | [setup](docs/COMFYUI.md) |
| **Pixal3D via ComfyUI** | Single image or 1–4 fixed-orbit views | Camera-aware shape + optional PBR | [setup](docs/COMFYUI.md) |

Runs locally on **NVIDIA CUDA GPUs** (6–32 GB VRAM depending on pipeline).
Developed and tested on an **RTX 3500 Ada (12 GB)**; see `config.yaml` for
low-VRAM options. **Windows is the native platform.** AMD and Intel GPU
inference are not supported today (CPU fallback is very slow).

| Platform / GPU | Support |
|---|---|
| Windows + NVIDIA CUDA | Full (native) |
| Linux + NVIDIA CUDA | Untested; some future models may be Linux-first |
| AMD / Intel GPU | Not supported |
| CPU only | Configurable (`device: cpu`) but impractically slow |

For AI assistants and contributors: see **`AGENTS.md`** and **`docs/MODEL_ROADMAP.md`**.

---

The [CAD Mesh Workbench](docs/WORKBENCH.md) adds a single inspection viewport,
model-specific advanced controls, full saved projects, checkpoints and a
persistent job queue. `run_modelunify.bat` opens a separate Edge/Chrome application
window; `--browser` and `--legacy` remain available.

**TRELLIS.2 / Pixal3D hosting:** select the ComfyUI backend in Generate. Install its
separate Windows/NVIDIA runtime with `.venv/Scripts/python.exe -m scripts.comfyui_host setup --model all`.
This downloads multi-GB weights without changing the existing model environment.
Original research stacks are Linux-first; this integration uses native ComfyUI
core on Windows. AMD/Intel GPU support is unvalidated. See [hosting, controls and limits](docs/COMFYUI.md).

## What's in the box

| Component | Purpose |
|---|---|
| `scripts/generate_3d.py` | CLI: info, single, batch, bms-lods, multiview, multiview-bms-lods, paint, multiview-textured, instalod-stage |
| `scripts/web_ui.py` | Gradio web UI at http://127.0.0.1:7860 (4 tabs: Preprocess / TripoSG / Multi-view / Paint PBR) |
| `scripts/preprocess.py` | Square-pad / crop / bg-remove satellite shots |
| `scripts/deploy_bms.py` | Copy a finished BML asset into a Falcon BMS theater |
| `scripts/engine.py` | Shared TripoSG pipeline (single-image backend) |
| `scripts/engine_hunyuan.py` | Shared Hunyuan3D-2mv pipeline (multi-view backend) |
| `scripts/texture.py` | Planar texture projection from source image |
| `vendor/TripoSG/` | Upstream TripoSG repo (kept patchable, see Notes) |
| `vendor/Hunyuan3D-2/` | Upstream Hunyuan3D-2 repo (installed as editable `hy3dgen` pkg) |
| `config.yaml` | Per-machine settings — **edit me** |
| `docs/BMS_WORKFLOW.md` | Step-by-step path from generated `.glb` to in-game `.bml` |

---

## Quick start

```powershell
# 1. First-time setup: provide an installed CPython 3.11 x64 executable
.\setup_windows.ps1 -PythonExe C:\path\to\Python311\python.exe
# Then activate (or invoke .venv/Scripts/python.exe explicitly)
.\activate.ps1

# 2. Sanity check (also confirms CUDA is wired up)
python scripts\generate_3d.py info

# 3a. Single-image (TripoSG) — drop a clean square photo into inputs\satellite\
python scripts\generate_3d.py single inputs\satellite\hangar.png

# 3b. Multi-view (Hunyuan3D-2mv) — fuse up to 4 photos of the same object
python scripts\generate_3d.py multiview `
       --front inputs\ground\hangar_front.jpg `
       --left  inputs\ground\hangar_left.jpg `
       --back  inputs\satellite\hangar_top.jpg `
       --name  hangar_01

# 4. Open the CAD Mesh Workbench in its own application window
.\run_modelunify.bat
# Original interface during migration: .\run_webui.bat
```

The **first** TripoSG generation downloads ~3 GB of weights into
`pretrained_weights/`. The **first** Hunyuan3D-2mv generation downloads
~5 GB to the HuggingFace cache (`%USERPROFILE%\.cache\huggingface\`).
After that, every run is local.

---

## End-to-end workflow for Falcon BMS

```
┌──────────────────────────┐   ┌──────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
│ 1–4 photos of building   │ → │ preprocess.py    │ → │ generate_3d.py       │ → │ Model_0..6.glb       │
│ (satellite + ground)     │   │ (crop + square)  │   │ multiview-bms-lods   │   │ bms_template/        │
│                          │   │                  │   │                      │   │   Parent.dat         │
│                          │   │                  │   │                      │   │   materials.mtl(JSON)│
└──────────────────────────┘   └──────────────────┘   └──────────────────────┘   └────────┬─────────────┘
                                                                                          │
                                                                                          ▼
                       ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
                       │ deploy_bms.py    │ ← │ BMS Blender Plg  │ ← │ Blender import   │
                       │ (copy to theater)│   │ → .bml + .mtl    │   │ + cleanup + PBR  │
                       └──────────────────┘   └──────────────────┘   └──────────────────┘
```

See [`docs/BMS_WORKFLOW.md`](docs/BMS_WORKFLOW.md) for the Blender step by step.

---

## Picking the right backend

| Situation | Use |
|---|---|
| You have exactly one good photo | **TripoSG** (`single`, `bms-lods`) — highest single-image fidelity |
| You have a satellite shot + 1–3 ground/side photos of the same building | **Hunyuan3D-2mv** (`multiview`, `multiview-bms-lods`) |
| You want to test fast on a folder of photos | **TripoSG batch** (`batch`) |

## Tips for getting good buildings

Both models work much better when the inputs are **square, tight-cropped, and
background-free**. Use the preprocessor:

```powershell
python scripts\preprocess.py prep IMAGE --remove-bg --size 1024
# or whole folder:
python scripts\preprocess.py batch inputs\satellite_raw --remove-bg --size 1024 --output-dir inputs\satellite
```

For **multi-view (Hunyuan3D-2mv)**:

- Views should be roughly **orthogonal** — front / left side / back / right side.
- They don't all have to be the same kind of source — a satellite "top-down"
  can act as the `back` view if you don't have a true back photo (results vary).
- 2 views (front + side) is typically enough for a recognizable building;
  3 views adds clear improvement; 4 views adds polish.
- Use **the same scale** across views (don't mix a tight crop with a wide shot).

For **single-image (TripoSG)**:

- A 3/4 oblique shot (think Google Earth tilted view) beats pure top-down
  satellite by a wide margin — top-down alone has no facade info, so
  TripoSG invents it.

The shape models produce geometry. Planar projection is an optional placeholder;
**Multi-view → Paint** and the **Paint PBR** tab run Hunyuan3D-2.1 to generate
PBR textures. Paint requires compiled CUDA extensions, the RealESRGAN
checkpoint, and cached/downloaded Hunyuan/DINO weights. CPU painting is unsupported.
See [development setup](docs/DEVELOPMENT.md) for the supported Gradio 6 stack.
Enhancement preserves a supplied master and writes GLB/maps/report to a fresh
folder; OBJ/DDS enhancement export is not implemented. `.max` ingest requires
external Blender + `io_scene_max`; inspect with `max_to_glb.py --inspect` first.
The FBX helper uses `fbxloader` and is asset-specific, outside the general CLI.

---

## Common CLI recipes

```powershell
# Preprocess a folder of raw photos
python scripts\preprocess.py batch inputs\satellite_raw --remove-bg --size 1024 `
       --output-dir inputs\satellite

# --- Single-image (TripoSG) ---
python scripts\generate_3d.py single   inputs\satellite\hangar.png --steps 60 --faces 25000
python scripts\generate_3d.py batch    inputs\satellite --pattern "*.png"
python scripts\generate_3d.py bms-lods inputs\satellite\hangar.png --name hangar_01

# --- Multi-view (Hunyuan3D-2mv) ---
python scripts\generate_3d.py multiview `
       --front inputs\ground\hangar_front.jpg `
       --left  inputs\ground\hangar_left.jpg  `
       --back  inputs\satellite\hangar_top.jpg `
       --name  hangar_mv_01

python scripts\generate_3d.py multiview-bms-lods --name hangar_mv_01 `
       --front inputs\ground\hangar_front.jpg `
       --left  inputs\ground\hangar_left.jpg  `
       --back  inputs\satellite\hangar_top.jpg

# After Blender BML export, push into BMS (parent-id must be unused in the DB)
python scripts\deploy_bms.py bms_export\hangar_mv_01 --parent-id 12345
```

---

## Configuration (`config.yaml`)

Most things you might want to change live here:

- **`model.triposg.dtype`** — `float16` (default, ~6 GB VRAM) or `float32`
  (better quality, ~10 GB VRAM — still fits your 12 GB).
- **`defaults.num_inference_steps`** — 25 for fast drafts, 50–75 for final.
- **`bms_lods.*`** — face-count targets for each Falcon BMS LOD.
- **`bms.bms_install`** — your Falcon BMS root. Required only for
  `deploy_bms.py`.
- **`bms.theater`** — e.g. `KoreaKTO`, `Balkans`, etc.

---

## Hardware and validation

Windows with NVIDIA CUDA is primary. The RTX 3500 Ada (12 GB) is the reference
target; VRAM use depends on settings. Shape has a slow CPU fallback; paint
requires CUDA and mmgp on constrained cards. AMD/Intel GPU paths are not wired.
Torch includes its CUDA 12.4 runtime; compiling native extensions separately
requires matching CUDA Toolkit and VS Build Tools. See [setup](docs/DEVELOPMENT.md).

Run `scripts/check_environment.py --ui` for offline prerequisite checks and
`python -m unittest discover -s tests -v` for synthetic export/deployment tests.
Use the [benchmark harness](docs/BENCHMARK.md) for repeated GPU measurements.
Help/import checks do not establish inference quality or clean-build portability.

LOD export preserves the source master and reports geometry/material/UV state.
Model_0 may retain the full master without reduction; each lower LOD must have
fewer faces. Infeasible or achieved duplicate levels fail before publication.
Use `--lod-count 3` or `--lod-faces 628,300,120` on BMS CLI commands to fit the
actual mesh. Existing asset directories are refused; choose a fresh name.
`lod_report.json` records target/achieved counts and UV fallbacks. Model_0 is
reserialized, not promised byte-identical. Final BML remains external.

Deployment validates before writing; `--dry-run` creates nothing. Occupied
destinations require explicit `--overwrite`; the helper cannot prove a Parent
ID is unused in the BMS database. Always inspect the exporter output first.

TripoSG's optional `diso` decoder remains disabled. FlashVDM/Turbo and new
preprocessing backends remain backlog items, with a [source review](docs/MODEL_ROADMAP.md).

---

## Folder layout

```
3D AI Generator/
├── activate.bat / activate.ps1 / run_webui.bat
├── config.yaml                  # edit for your machine + BMS install
├── requirements.txt
├── AGENTS.md                    # AI assistant / contributor guide
├── docs/
│   ├── BMS_WORKFLOW.md
│   ├── BUILD_PORTABLE.md
│   └── MODEL_ROADMAP.md         # tracked model upgrades & ratings
├── scripts/
│   ├── engine.py                # shared TripoSG runtime
│   ├── generate_3d.py           # CLI
│   ├── web_ui.py                # Gradio UI
│   ├── preprocess.py            # square / crop / bg-remove
│   ├── texture.py               # planar projection
│   └── deploy_bms.py            # copy BML into BMS theater
├── vendor/
│   ├── TripoSG/                 # upstream repo (patched: lazy diso import)
│   └── Hunyuan3D-2/             # upstream repo (installed as editable hy3dgen pkg)
├── inputs/
│   ├── satellite/               # drop top-down / aerial shots here
│   └── ground/                  # drop oblique / side photos here
├── outputs/                     # single-model results (.glb)
├── bms_export/                  # one folder per asset with Model_0..6
├── pretrained_weights/          # auto-downloaded model weights (~3 GB)
└── models_cache/                # HuggingFace cache (auto-created)
```

---

## Credits

- **TripoSG** — Tripo AI & VAST-AI Research ([paper](https://arxiv.org/abs/2502.06608))
- **Hunyuan3D-2 / Hunyuan3D-2mv** — Tencent ([repo](https://github.com/Tencent/Hunyuan3D-2)) — TENCENT HUNYUAN COMMUNITY LICENSE (non-commercial; check the LICENSE file in `vendor/Hunyuan3D-2/` if you plan to redistribute)
- **RMBG-1.4** — Briaai (background removal, used by TripoSG)
- **rembg / u2net** — used by Hunyuan3D-2's background removal
- **BMS Blender Plugin** — [Benchmark Sims](https://github.com/BenchmarkSims/bms-blender-plugin) (required for the final `.glb → .bml` step)
