# AGENTS.md — AI assistant guide for ModelUnify

This file is for Cursor, Copilot, Claude Code, and other AI coding tools working in this repository.

## Codex session startup

- Read this file, then `docs/CODEX_PROJECT.md` for the component map, validation baseline, known gaps, and prioritized next steps. Check the current code before treating that dated baseline as current state.
- Read `config.yaml` before changing pipeline settings. Use `scripts/_version.py` as the version source.
- Version every delivered change set: update `scripts/_version.py` and add a dated `CHANGELOG.md` entry. Use patch increments for fixes, minor increments for features, and major increments for breaking changes, unless the user specifies a version. Keep historical build labels accurate; versioning does not authorize commits or distribution rebuilds.
- Work on the root `scripts/`, `tools/`, and `packaging/` sources. `dist/` contains generated copies and a bundled runtime, not the development source of truth.
- For LOD tasks, read `.cursor/skills/modelunify-lods/SKILL.md`. For enhancement tasks, read `.cursor/skills/modelunify-bms-enhance/SKILL.md`. These are existing project workflows; their documented capabilities still need checking against the implementation.
- Inspect an existing mesh before processing: triangles, vertices, UVs, materials, components, bounds, winding, and hierarchy. State conversion losses and proposed output paths. Keep supplied masters intact and report duplicate/no-op LODs and UV fallback honestly.
- Project-owned tests now live in `tests/`; see `docs/CODEX_PROJECT.md` for the current baseline. Start with relevant tests, syntax checks and CLI help/info; validate changed export behavior with temporary synthetic assets and GLB round-trips. GPU inference and clean portable-build checks are separate validation steps.
- Use `.venv/Scripts/python.exe` explicitly when it works. The initialization review found its base Python unavailable; do not assume activation repairs it. The bundled interpreter can support limited diagnostics, but its installed packages differ from `requirements.txt`.
- Do not import `_bake_prototype.py` for discovery: it runs asset-specific processing and deletes prior scratch outputs at module import.
- Keep downloaded weights, environments, caches, inputs, generated meshes, native build artifacts, and `dist/` outside source control. Inspect nested vendor Git repositories before any initial staging; never stage the entire workspace blindly.
- Only commit when explicitly asked. Publishing, installing dependencies, rebuilding distributions, running inference, and deploying to BMS are separate work from reading or initializing project guidance.

## What ModelUnify is

**ModelUnify** is an integrated local 3D AI creation tool. It wraps multiple image-to-3D and mesh-texturing backends behind one CLI and Gradio web UI.

| Aspect | Detail |
|--------|--------|
| Version | `scripts/_version.py` → `MODELUNIFY_VERSION` (currently `1.11.2`) |
| Entry points | `scripts/generate_3d.py` (CLI), `scripts/web_ui.py` (UI), `run_webui.bat` |
| Config | `config.yaml` — per-machine model paths, VRAM modes, LOD presets |
| Vendored upstream | `vendor/TripoSG/`, `vendor/Hunyuan3D-2/`, `vendor/Hunyuan3D-2.1/` |
| Optional post-process | `tools/instalod/` — InstaLOD **Studio** (Pioneer) inbox/outbox + recipes. Stage GLBs with `python tools/instalod/stage.py`. **Not** an engine, MCP, or CLI into InstaLOD. Do not wrap `InstaLODCmd` unless Pipeline is licensed. |

## Primary use cases (in priority order)

1. **Falcon BMS** — Generate building/object meshes from satellite and/or ground photos; export LOD sets (`Model_0`…`Model_6`) and deploy via `deploy_bms.py`. See `docs/BMS_WORKFLOW.md`.
2. **3D presentation** — Quick textured meshes (GLB/OBJ) for demos, slides, or viewers.
3. **3D printing** — Single-view or multi-view meshes; users may need mesh repair/decimation before slicing.
4. **Gaming** — Prototype assets; PBR paint path produces albedo/metallic/roughness maps usable in engines after cleanup.

Do not describe ModelUnify as “BMS-only.” BMS is the **main** workflow, not the only one.

## Hardware and platform assumptions

### Reference development machine

The maintainer develops on **NVIDIA RTX 3500 Ada (12 GB VRAM)**. This is a **validation target**, not a minimum or maximum for all users.

### Target GPU range

Design for a spectrum of NVIDIA cards, for example:

| Class | Example GPUs | Typical VRAM | Implications |
|-------|--------------|--------------|--------------|
| Entry laptop | RTX 3060, RTX 4060 | 6–8 GB | Shape-only or SF3D draft; paint needs `low_vram_mode` + mmgp |
| Mid workstation | RTX 3090, RTX 4070 Ti | 12–16 GB | Full MV + paint with low-VRAM tricks |
| High-end | RTX 4090, RTX 5080 | 16–32 GB | Full quality, less swapping, optional TRELLIS.2 |

Always expose VRAM-sensitive options in `config.yaml`. Prefer runtime detection over hardcoded limits.

### GPU vendor support (critical)

| Vendor | Status | What works | What does not |
|--------|--------|------------|---------------|
| **NVIDIA + CUDA** | **Supported** | TripoSG, Hunyuan3D-2mv, Hunyuan3D-2.1 paint, rembg GPU | — |
| **AMD + ROCm** | **Not supported** | Nothing tested; CPU-only theoretical | `custom_rasterizer` (CUDA), most paint pipeline |
| **Intel CPU** | **Fallback** | Shape backends via `device: cpu` in config | Impractically slow for diffusion; PBR paint requires CUDA |
| **Intel GPU (XPU)** | **Not wired** | — | No IPEX/XPU integration |

When proposing features, state which GPU vendors they support. If CUDA-only, say so in UI tooltips and docs.

### Operating system

| OS | Status |
|----|--------|
| **Windows** | **Native.** Portable build (`packaging/`, `docs/BUILD_PORTABLE.md`), MSVC for CUDA extensions, primary user base. |
| **Linux** | **Secondary.** Some upstream models (e.g. **TRELLIS.2-4B**) are Linux-tested first. If integrating Linux-first deps, add a visible **platform warning** in README, UI, and `docs/MODEL_ROADMAP.md`. |

**Rule for AI assistants:** If a dependency or model is Linux-only or Linux-prioritized, **tell the maintainer explicitly** and propose user-facing messaging (installer check, Gradio banner, docs section) — do not assume silent cross-platform support.

## Current backends (v1.9)

| Backend | Engine file | Input | Output |
|---------|-------------|-------|--------|
| TripoSG 1.5B | `scripts/engine.py` | Single image | Mesh (+ planar texture) |
| Hunyuan3D-2mv | `scripts/engine_hunyuan.py` | 1–4 views | Mesh (+ planar texture) |
| Hunyuan3D-2.1 Paint | `scripts/engine_paint.py` | Mesh + reference image | PBR textured mesh |
| TRELLIS.2 via native ComfyUI core | `scripts/engine_comfyui.py` | Single image | Raw master + optional UV/PBR GLB |
| Pixal3D via native ComfyUI core | `scripts/engine_comfyui.py` | Single image or 1–4 matched fixed-orbit views | Raw master + optional UV/PBR GLB |

ComfyUI uses a separate ignored runtime under `.runtime/comfyui` and explicit
`scripts/comfyui_host.py` setup/download commands. Never install ComfyUI dependencies
into the existing ModelUnify environment. See `docs/COMFYUI.md`: Windows/NVIDIA
integration differs from the Linux-first original research stacks. Existing
portable bundles do not contain this new runtime. Shape controls are wired in
Mesh Workbench; the legacy UI links to that workflow. Default diffusion weights
are Comfy-Org INT8 repacks; Pixal multiview assumes a fixed 90° orbit and shared FOV.

Auxiliary: RMBG-1.4 / rembg (BG removal), Marigold / StableNormal (normal maps), `lod_export.py` (BMS LOD decimation), `enhance_model.py` (mesh/texture post-process + ARMW packing), `max_to_glb.py` (3ds Max `.max` ingest via headless Blender).

**Source format ingest:** the core mesh paths use trimesh for OBJ/GLB/glTF/PLY/STL. `.max` goes through `scripts/max_to_glb.py` (needs Blender + the GPL-2.0 `io_scene_max` extension — call Blender as a subprocess, never vendor the parser). The existing `scripts/_fbx_to_textured_glb.py` helper imports `fbxloader`, not `pyufbx`, and includes an asset-specific windsock material helper; it is not a general CLI ingest path. Both conversions can drop UVs or flatten hierarchies; always report that before running a pipeline on the result.

**Not integrated (but present upstream):** text-to-3D (`vendor/Hunyuan3D-2/hy3dgen/text2image.py`), FlashVDM/Turbo, NeRF, Gaussian splatting.

## How to add a new model

There is no plugin registry. Standard pattern:

1. Add `vendor/<upstream>/` or document HF weights path.
2. Create `scripts/engine_<name>.py` with `*_from_config()` factory.
3. Add `model.<name>:` section in `config.yaml`.
4. Wire CLI subcommand in `scripts/generate_3d.py`.
5. Add Gradio tab/controls in `scripts/web_ui.py`.
6. Document VRAM, OS, and GPU vendor requirements.
7. Add row to `docs/MODEL_ROADMAP.md`.

## Coding conventions

- Match existing engine wrapper style; lazy-load heavy models.
- Unload shape engines before paint when VRAM is tight (`HunyuanMVEngine.unload()`).
- Windows paths: support both `\` and `/`; portable build must not assume dev venv layout.
- Do not commit secrets, `.env`, or downloaded weights.
- Only create git commits when the user explicitly asks.

## Key documentation

| File | Purpose |
|------|---------|
| `docs/MODEL_ROADMAP.md` | Tracked upgrade options and recommendation ratings |
| `docs/BMS_WORKFLOW.md` | Falcon BMS export pipeline (optional InstaLOD Studio hop) |
| `docs/BUILD_PORTABLE.md` | Portable Windows packaging |
| `config.yaml` | Runtime model and LOD settings |
| `README.md` | User-facing quick start |

## Future roadmap

See **`docs/MODEL_ROADMAP.md`** for prioritized upgrades (FlashVDM/Turbo, text-to-3D, TRELLIS.2, SF3D, etc.) with recommendation scores, sizes, and integration estimates.
