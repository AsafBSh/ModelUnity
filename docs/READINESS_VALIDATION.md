# Readiness implementation and validation — 2026-10-19

Version: `scripts/_version.py` → **1.0**. Platform: Windows x64, CPython
3.11.9, RTX 3500 Ada Laptop GPU (12281 MiB), torch 2.5.1+cu124/CUDA 12.4.

## Implemented

- Retained the existing development environment. The configured Python base
  exists and runs under the owning user; sandbox execution restrictions caused
  the apparent missing-runtime failure. Changed only optimum-quanto 0.2.7 →
  0.2.6 and SymPy 1.14.0 → 1.13.1 to resolve real dependency conflicts.
  Prior package state is in `.runtime/development-before.txt`.
- Supported Gradio 6.17.3, explicit CUDA wheel requirements, Windows version
  constraints and a preserving setup script. Upstream training/demo pins are
  not installed over this inference environment. Optional ingest dependencies
  are separate. See [DEVELOPMENT.md](DEVELOPMENT.md).
- Serialized CLI/UI GPU operations with guaranteed owned-resource cleanup;
  shape unloads before paint; paint unloads before AI normals. mmgp manages
  diffusion **and the separate DINO encoder**, releases its offload object and
  restores torch's previous default device. Requested-but-unavailable mmgp
  stops painting with an explicit error. A NumPy/CUDA type error is no longer
  incorrectly diagnosed as OOM. Normal results record requested/actual baker.
- Shared LOD preflight inspects actual geometry, bounds, UVs, materials/maps,
  components and winding. Multi-instance/multi-material and animated/skinned
  masters need an explicit static/atlas conversion first. Master files remain
  intact. Model_0 can retain all geometry; every lower level must reduce faces.
  Sets are staged, round-tripped and published only after count/map validation.
  Existing asset directories are refused. Reports include requested/achieved
  counts and UV fallback. Scalar roughness/metallic sidecars use glTF G/B;
  Wavefront MTL references these scalar maps rather than ambiguous packed RGB.
- Deployment validates required files, contiguous levels, JSON material
  metadata and destination collisions before writing. Dry-run creates no
  directories/files; real copy regressions use a fake temporary BMS tree.
  The helper does not prove a Parent ID is unused or generate final BML.
- Portable packaging includes tools/, shared dependency constraints and an
  explicit paint checkpoint/native binary choice. Existing bundle/archive
  paths are refused; destructive cleanup was removed. Build helpers discover
  tools and check CUDA ABI. Installer version comes from `_version.py` via
  its wrapper; uninstall preserves user results/caches. Ignores cover raw
  inputs, distributions, environments, secrets, weights and native artifacts.
- README, project handoff, BMS/portable guidance and both project workflows
  describe current PBR/UI/import/enhancement capabilities. No speculative
  backend was integrated. The [roadmap](MODEL_ROADMAP.md) has a primary-source
  recheck of FlashVDM/Turbo, Delight and RMBG 2.0 licensing/access.

## Completed checks

- **21 focused unittests passed**, including PBR/GLB round-trips, correct G/B
  extraction, master preservation, duplicate lower levels, failed decimation
  without partial publication, UV loss to average albedo, generator targets,
  multi-instance rejection, overwrite refusal, staging, deployment dry-run and
  fake-install copying, CLI handoff, partial-load cleanup, mmgp-release error
  cleanup, default-device restoration and actual AI-normal fallback reporting.
- Syntax parsed **23** root scripts/tools/tests. New helper/test lint passed.
- `pip check`: no broken requirements. Clean dependency resolution with the
  Windows/CUDA constraints passed without installing CPU torch. A complete
  fresh environment install was not performed.
- Root CLI help/info and helper help checks passed: BMS commands (including
  new count/budget options), multiview-textured, instalod-stage, preprocess,
  max_to_glb, enhance_model, deploy_bms and benchmark.
- Offline UI construction: **332 components**, Gradio 6.17.3. Root checkout
  hy3dgen, paint pipeline, rasterizer, optional compiled mesh-inpaint module,
  RealESRGAN class and checkpoint all available. No browser/server test was
  substituted for an inference check.
- Four PowerShell scripts parsed. Portable `-PlanOnly` and installer
  `-PlanOnly` passed. An attempted default build refused the existing bundle
  **before** cleanup or downloads. The existing distribution was untouched.

## Repeated GPU evidence

Two iterations in one process, offline/cached weights, synthetic RGBA building
image (SHA-256 recorded in the JSON), seed 42, MV 2 steps/octree 128, requested
paint max views 4/resolution 512/render 512/texture 512, Marigold high normals.
This deliberately tests lifecycle, **not production geometry/visual quality**.
The view selector actually produced six views; output maps were 256×256 despite
the requested texture size. Logs preserve those upstream behaviors.

- Iteration 0: **success**, 176.8 s total (shape 35.5, paint 115.6, normal 15.4 s); mmgp=True; normal actual=high; peak torch allocated 6.42 GiB, reserved 12.51 GiB; after cleanup 8.12 MiB.
- Iteration 1: **success**, 171.2 s total (shape 39.0, paint 113.8, normal 15.7 s); mmgp=True; normal actual=high; peak torch allocated 6.43 GiB, reserved 12.58 GiB; after cleanup 8.12 MiB.

Memory returned to the same allocated baseline after both passes. Reserved
peaks exceed physical VRAM under this Windows driver; they are allocator
metrics, not a guarantee that default presets fit. No visual quality scores
were assigned to the two-step synthetic mesh (184740 faces, 75 components,
non-watertight). Use [BENCHMARK.md](BENCHMARK.md) for the real fixed input set.

The final cleanup code also passed two additional cached painter load/unload
cycles: torch default device restored to CPU, mmgp's global offloader released,
and **zero torch-allocated GPU bytes** after each. This separately verifies
release of DINO, super-resolution and render ownership, including partial
construction/traceback handling. Evidence: `.runtime/paint-cleanup.json` and
`.runtime/paint-cleanup.log`; these are lifecycle checks without inference.

Local evidence: `.runtime/gpu-handoff-restored-device/benchmark.json`,
`.runtime/gpu-restored.log`, `.runtime/tests-verified.log`,
`.runtime/environment-final2.log`, `.runtime/resolver.log` and helper help logs.
Earlier scratch runs preserve the observed DINO CPU stall and the second-pass
default-device failure that led to the fixes; they are not passing benchmarks.

## Remaining release checks and blockers

- **Native recompilation:** preflight confirmed installed CUDA Toolkit 12.6.85,
  while supported torch is CUDA 12.4. Existing native modules import and ran
  successfully. Install/select Toolkit 12.4 before rebuilding compatible wheels;
  no toolkit or vendor code was silently replaced.
- Clean portable build, relocated/clean Windows machine inference, and Inno
  Setup compilation/install/uninstall are not performed. No existing user
  distribution was cleaned to make room. These remain release gates; planning
  and import checks are not portability proof.
- Production quality/speed testing on a fixed real building/object set remains
  pending. TripoSG full inference, StableNormal and default-quality paint were
  not measured in this readiness smoke. GPU support remains NVIDIA CUDA;
  shape-only CPU fallback is slow, CPU painting and AMD/Intel GPU are unsupported.
- Blender `.max` conversion and the asset-specific FBX helper were help/import
  scoped here, not validated with a supplied asset. Final BML/authoritative
  metadata/DDS export remains external and no real BMS installation was touched.
- The root still has no Git repository. No commit, staging, remote creation or
  publication was performed. Nested vendor patches/licenses were preserved.

## Changed source files

Environment/setup: `requirements.txt`, `requirements-cuda124.txt`,
`requirements-windows-lock.txt`, `requirements-optional.txt`, `setup_windows.ps1`,
`activate_build.ps1`, `build_paint_extensions.bat`, `run_webui.bat`,
`scripts/check_environment.py`, `.gitignore`.

Lifecycle/benchmark: `scripts/gpu_lifecycle.py`, `scripts/engine.py`,
`scripts/engine_hunyuan.py`, `scripts/engine_paint.py`, `scripts/generate_3d.py`,
`scripts/web_ui.py`, `scripts/benchmark.py`.

Export/deploy: `scripts/export_contracts.py`, `scripts/lod_export.py`,
`scripts/deploy_bms.py`, `scripts/enhance_model.py`, `tools/instalod/stage.py`,
`tests/test_readiness.py`, and corrected comments in `config.yaml`.

Packaging: `build_portable.ps1`, `packaging/build_installer.ps1`,
`packaging/installer.iss`, `packaging/README.txt`.

Documentation: `README.md`, `docs/CODEX_PROJECT.md`, `docs/DEVELOPMENT.md`,
`docs/BENCHMARK.md`, `docs/BUILD_PORTABLE.md`, `docs/BMS_WORKFLOW.md`,
`docs/MODEL_ROADMAP.md`, this report, and
`.cursor/skills/modelunify-lods/SKILL.md`,
`.cursor/skills/modelunify-bms-enhance/SKILL.md`.
