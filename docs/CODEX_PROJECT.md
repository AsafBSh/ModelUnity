# ModelUnify: current Codex handoff

Updated **2026-10-28**. Version source: `scripts/_version.py` (1.11.2). Start with
`AGENTS.md`, this file and `config.yaml`. Source lives in root scripts/tools/
packaging; dist is generated. Do not commit or publish without an explicit request.

On 2026-10-28 the maintainer authorized removing all downloaded project AI weights
and publishing source to https://github.com/AsafBSh/ModelUnity. Environments,
native modules and assets remain. See MODEL_WEIGHTS.md for restoration and
OPERATING_GUIDE.md for practical use. The weight-free CPU suite passed 122 tests
and the UI constructed with 376 components/70 events. This does not validate AI
inference without weights. See WORKSPACE_CLEANUP_20261028.md and CONTRIBUTING.md.

Every delivered change set now requires a version bump and a dated entry in
`CHANGELOG.md`; see the versioning rule in `AGENTS.md`. Existing v1.0 portable
packages retain their original labels and contents until explicitly rebuilt.
Workspace storage maintenance is recorded in `WORKSPACE_CLEANUP.md`; generated
archives are retained even when their redundant extracted copies are removed.
The 2026-10-26 cleanup subsequently retires old release runtimes and installer
duplicates, keeping one verified RC2 archive plus compact source-history deltas
and unique-file overlays. See `WORKSPACE_CLEANUP_20261026.md`. Restore old builds
from the archive when needed; root sources and environments remain installed.
The historical source deltas depend on the retained RC2 base archive. Preserve
that base or rebase the source snapshots before retiring it in a future cleanup.

The six workbench priorities now have implementations and **97 passing tests**.
The v1.11.0 accuracy/authoring additions are documented in `ACCURACY_AUTHORING.md`:
pixel-bound manual masks, orthographic reference overlays, protected reduction,
queued xatlas/CPU PBR rebaking, and general interchange/static BMS handoff.
The current full suite has **122 passing tests**; 97 is the historical baseline.
These CPU tools do not change inference vendor support. Preserve the restored
windowed layout. The BMS handoff is static/single-slot/single-skin only, authors
no BML or DDS, and never edits global theater DAT files or installs an object.
Per-LOD MTI slot order must be checked against the external exporter's actual BML.
See `ACCURACY_AUTHORING_VALIDATION.md` for the real brush/picking/queue/export
browser run, lossless mask fingerprint check, high-DPI layout and redraw evidence.
The real quick benchmark completed **12/12** tank/hangar/F-15 jobs; inspect its
mask-loss and cleanup warnings before drawing quality conclusions. See
`WORKBENCH_INSPECTION_VALIDATION.md` and `BENCHMARK_WORKBENCH_20261021.md`.
Viewport redraw is separate from slow inspector callbacks; comparison camera
restoration uses Babylon's target clone flag to avoid recomputing saved framing.

## Product and launch

The v1.10.0 GUI redesign was rejected by the user and reverted in v1.10.2.
The previous windowed Mesh Workbench is restored, including its original header,
asset toolbar, settings, viewport controls, PBR/Texture/Mesh inspector order and
visual styling. Do not reapply the rejected mockup/design guidance. The separate
legacy Gradio UI is not the interface the user requested to restore.
Keep the v1.10.1 startup/progress fix. See `GUI_REVERT_VALIDATION.md`.

Local image-to-3D and PBR tool. Falcon BMS is the main workflow; presentation,
printing and game prototyping also matter. Windows/NVIDIA CUDA is supported.
Shape CPU fallback is slow; paint needs CUDA/native rasterizer/RealESRGAN.
AMD ROCm and Intel XPU are not wired. The 12 GB RTX 3500 Ada is a validation target.

`run_modelunify.bat` opens the CAD workbench in a private Edge/Chrome application
window, localhost 7861. Closing the window leaves jobs/server running.
`--browser` uses a browser tab; `--legacy` or `run_webui.bat` keeps the original UI
on 7860. `run_workbench_preview.bat --no-open` runs a visible server session.
The v1.10.1 launcher prints immediate startup/progress messages and elapsed time;
cold library loading was observed to take about 100 seconds on this machine.
Child output is unbuffered in `.runtime/workbench_preview/server.log`.

## Source map

- `scripts/workbench/{input_readiness,diagnostics,scaling,benchmarking}.py`:
  input/mask checks, bounded UV overlap/stretch/density heatmaps, measured copy-only
  transforms and intermediate BMS readiness, shared reproducible benchmark settings.
- `scripts/benchmark_suite.py`, `benchmarks/objects.json`: real four-generator
  tank/hangar/jet benchmark via the existing queue; manual scores are never invented.
- `scripts/comfyui_progress.py`, `comfyui_install.py`: prompt-scoped live events,
  sampled host memory, disk/driver plan and pinned isolated optional installation.
  New native Generate jobs also retain raw `master.glb` before postprocessing.

- `scripts/engine_comfyui.py`, `comfyui_workflows.py`, `comfyui_host.py`: isolated
  local ComfyUI hosting, native TRELLIS.2 / Pixal3D graphs, explicit runtime/weight
  setup and API transport. Workbench Generate and CLI `comfy` use the same pipeline.
  No Comfy packages are imported into the main application. See `docs/COMFYUI.md`.
  Runtime/weights live in ignored `.runtime/comfyui`; source and portable runtimes
  remain independent. Pixal multiview is fixed-orbit and uses separate weights.

- `scripts/workbench_preview.py`: Gradio CAD shell, one persistent viewer,
  model-aware inputs/advanced controls, projects, Surface Lab, LODs and jobs.
- `scripts/workbench/layout.py`: client-only draggable/keyboard side-panel
  dividers, width constraints, local profile persistence and reset. The viewer's
  ResizeObserver redraws without replacing the canvas or resetting its camera.
- `scripts/workbench_service.py`: thin UI adapters; never imports web_ui.
- `scripts/workbench/`: schema, projects, preparation, pipelines, queue, isolated
  worker, runtime configuration, materials, offline Babylon viewer and normal embedding.
- `scripts/launch_workbench.py`: dedicated application-window/server launcher.
- `scripts/app_identity.py`: installation ownership marker; another bundle must
  never attach to this source server. Default ports are selected automatically.
- `scripts/validate_workbench.py`: repeatable real jobs with diagnostic settings.
- `scripts/workbench/optimization.py`: bounded CPU optimization, winding repair,
  budget/UV/material/bounds guards. `scripts/validate_optimization.py` compares
  one-pass and bounded runs on a kept-intact static master in fresh output paths.
- `scripts/generate_3d.py`: existing CLI; `scripts/web_ui.py`: retained legacy UI.
- `scripts/engine.py`: TripoSG single-image; `engine_hunyuan.py`: Hunyuan 1–4 views;
  `engine_paint.py`: mesh/reference PBR. All load weights on demand.
- `scripts/gpu_lifecycle.py`: serialization and owned-resource cleanup.
- `scripts/checkpoint_io.py`: scoped Windows DINO checkpoint-read workaround.
- `scripts/export_contracts.py`, `lod_export.py`: static-master validation,
  staged LOD publication, actual reduction/UV/map reporting, intermediate BMS exports.
- `scripts/enhance_model.py`: normals/AO/image-based delight/ARMW enhancement.
- `scripts/preprocess.py`, `texture.py`: existing preparation and planar projection.
- `scripts/max_to_glb.py`: external Blender/MAX ingest; FBX helper is asset-specific.
- `scripts/deploy_bms.py`: deployment of finished BML assets; never run implicitly.
- `tools/instalod/`: Studio inbox/outbox workflow; no licensed Pipeline CLI wrapper.
- `build_portable.ps1`, `packaging/`: fresh-output portable/installer production.

## State and invariants

- Projects own images, masks, source meshes, settings, versions and run provenance
  under `projects/`; artifact references are relative. Runtime queue/presets/logs/
  viewer cache/window profile default to `.runtime/workbench_preview/`. Paths are configurable.
- Queue project/result locations are stored relative to the project root, with
  migration of legacy absolute records. Public queue rows resolve at the current
  location, so queued jobs and completed previews survive moving a whole bundle.
- Operations use immutable frozen inputs and publish previews only after validation.
  Accept creates a checkpoint; discard retains history. Originals remain intact.
- Babylon preview updates must call `details.markSceneMutated()` after setting
  scene properties so the idle viewer redraws without camera interaction.
- Optimize allows at most three passes without relaxing safety parameters;
  strict budgets and attribute/bounds failures publish no preview. Winding
  repair does not make non-manifold meshes manifold. UV fallback needs opt-in.
  A deterministic bidirectional sampled surface-error guard defaults to 2% of
  source diagonal; the numeric-only 2,000-face residential result failed visual
  review (5.585%) and is rejected. The working 7,999-face candidate is ~0.290%.
- Background preparation is explicit for both shape models. Hunyuan's preprocessed
  path bypasses hidden removal; TripoSG receives a white composite.
- GPU/native jobs run in separate Python processes. Cancel is cooperative at safe
  boundaries. Native failure must leave the UI alive with a failed job/log.
- Hunyuan low_cpu_mem_init avoids temporary model/conditioner CPU weights.
  VAE encoder weights missing upstream retain ordinary initialization. Unload drops
  ownership directly; do not copy the entire model to CPU merely to delete it.
- Windows worker output is UTF-8. The DINO NumPy checkpoint workaround preserves
  tensor values and restores the Transformers loader after its scoped call.
- LOD input is one static mesh/material. Reject animation/skins, inspect hierarchy,
  UVs/maps, bounds/winding/components before processing and report conversion losses.
  Lower levels must reduce faces; report UV fallback/no-op honestly. Final BML/DDS
  and authoritative BMS dimensions remain external.
- Keep `.venv`, weights, vendor patches/licenses and package test modules. Never
  import `_bake_prototype.py` for discovery; it has destructive import side effects.

## Validation and remaining work

Use `.venv/Scripts/python.exe` explicitly. It works under the owning Windows user;
older sandbox diagnostics incorrectly suggested its base Python was missing.
Gradio is pinned to 6.17.3, torch to the CUDA 12.4 stack. Do not install upstream
training requirements over this environment. Existing native modules work; rebuilding
requires Toolkit 12.4 rather than the installed 12.6.
The painter's inference class itself requires pytorch-lightning; do not remove
that dependency as training-only. `check_environment.py` now imports the lazy
model class too. Generation target misses and inconsistent winding are warnings,
retained in history and shown on otherwise completed jobs.

- `.venv/Scripts/python.exe -m unittest tests.test_launcher tests.test_workbench tests.test_readiness tests.test_optimization`
- `node tests/workbench_browser.cjs` and `--layout-only --high-dpi` against port 7861;
  `MODELUNIFY_TEST_URL` selects a portable server, `MODELUNIFY_TEST_MESH` supplies
  an explicit GLB through the real upload control.
- `node tests/workbench_viewer_browser.cjs` verifies actual display/lighting image
  changes with a stationary camera and returns to idle (no inference).
- `node tests/workbench_layout_browser.cjs` verifies real pointer/keyboard sizing,
  persistence, reset/cancel, narrow-window clamping, full-height divider hit targets,
  one viewport and unchanged camera/asset. Uses an isolated browser profile.
- `node tests/workbench_optimization_browser.cjs` exercises strict misses,
  bounded success and failure isolation using the residential fixture through
  actual GUI/isolated jobs. See `docs/OPTIMIZATION_VALIDATION.md`.
- `python -m scripts.workbench_preview --check` / `scripts.launch_workbench --check`
- `python -m scripts.validate_workbench --front photo.png --output NEW_FOLDER
  --repeat 2 --paint --backend multiview --offline`

The latest regression baseline is **97 tests**; older validation reports retain
their historical counts. See [WORKBENCH_VALIDATION.md](WORKBENCH_VALIDATION.md),
[WORKBENCH_INSPECTION_VALIDATION.md](WORKBENCH_INSPECTION_VALIDATION.md) and
[WORKBENCH_RC2_DELIVERY.md](WORKBENCH_RC2_DELIVERY.md) for evidence and release gates.
The v1.0 portable RC2 uses clean packages and a validated native paint wheel;
shape and four-view→PBR passed after relocation. Clean-machine and production-quality
validation remain separate. Never copy generated bundles back over root source.

The 2026-10-20 driver loss recovered. ComfyUI validation on 2026-10-21 detected
the RTX 3500 Ada with driver 596.72. ModelUnify uses torch 2.5.1+cu124; isolated
ComfyUI uses torch 2.14.1+cu130. Keep those environments separate. All three Comfy
generator variants completed real 512 inference; TRELLIS.2 PBR and a queued GUI
job completed too. These checks do not certify production accuracy. See
`COMFYUI.md` and `.runtime/comfyui/validation` for details.

Storage maintenance preserves original assets and uses transparent Windows
compression; see [WORKSPACE_CLEANUP.md](WORKSPACE_CLEANUP.md). Archives retain
their historical version labels. Re-extract a retained portable archive into a
new folder before using it; root `run_modelunify.bat` is the development launcher.

Detailed guides: [WORKBENCH.md](WORKBENCH.md), [DEVELOPMENT.md](DEVELOPMENT.md),
[MODEL_ROADMAP.md](MODEL_ROADMAP.md), [BMS_WORKFLOW.md](BMS_WORKFLOW.md),
[BUILD_PORTABLE.md](BUILD_PORTABLE.md), [READINESS_VALIDATION.md](READINESS_VALIDATION.md).
