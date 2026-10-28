# ModelUnify Mesh Workbench

The Precision CAD workbench is the new desktop launch path. It retains the
Inputs → Generate → Texture → Optimize → Export workflow and uses the actual
local engines. The original Gradio interface remains available during migration.

Generate also supports **TRELLIS.2 / Pixal3D through a separate local ComfyUI host**.
Single-image and Pixal fixed-orbit multiview inputs, diffusion stages, FOV and PBR
controls are model-specific. See [COMFYUI.md](COMFYUI.md) for explicit setup,
Windows/NVIDIA requirements, host management and retained workflow artifacts.

## Launch

Double-click `run_modelunify.bat`. Microsoft Edge (or Chrome when Edge is absent)
opens ModelUnify in a dedicated application window without tabs/address bar,
using a separate profile under `.runtime/workbench_preview/window-profile/`.
The rendering engine is still Chromium; this is not a standalone native toolkit.
Edge/Chrome must already be installed. No extra GUI dependency is installed.

The launcher immediately prints a startup banner, then loading progress with
elapsed time until the local server is ready. Cold library loading can take a
few minutes; a blank console is no longer expected. The ready URL is printed
before the window opens, and live startup output is saved to
`.runtime/workbench_preview/server.log`. Starting again reuses this installation's
running server.

- `run_modelunify.bat --browser`: ordinary default-browser window.
- `run_modelunify.bat --legacy`: original interface, port 7860.
- `run_modelunify.bat --port 7862`: alternate workbench port.
- `run_modelunify.bat --server --port 7862`: foreground server without opening a window.
- `.venv/Scripts/python.exe -m scripts.launch_workbench --check`: read-only readiness.
- `run_workbench_preview.bat --no-open`: server only, default port 7861.

Closing the application window leaves the local server and queued jobs running.
Reopening attaches to the existing workbench. The launcher checks application
identity and installation path before attaching. By default it selects an
available port from 7861 if another installation/application is already running.
An explicit `--port` is fixed and refuses a foreign server at that address.
The server binds only to localhost. Startup failures point to the server log.
Use `Ctrl+C` in a server-only session to stop it. Interrupted jobs are reported
after restart; queued jobs resume. CUDA kernels are never force-cancelled.

## Interface

The previous windowed Mesh Workbench was restored in v1.10.2 at the user's request.
The v1.10.0 redesign is no longer used. This is the same dedicated Edge/Chrome
application window launched by `run_modelunify.bat`, not the separate legacy UI.

One desktop viewport, with independent settings/inspector scrolling and visible
16px scrollbars. The previous graphite/navy styling, original ModelUnify logo,
locally served IBM Plex Sans/Montserrat type, turquoise actions and violet
material-inspection accents are restored.

The header shows live device/memory information and layout reset. The asset
toolbar contains the project name, mesh picker and Open/New actions. Channel,
bounds and environment controls are above the viewport. PBR, Texture, Mesh,
Project, UV and Jobs inspectors retain their previous order; project saving
remains in Project. Accept / checkpoint creates a named checkpoint.

Texture setup retains its original reference image, preset radio controls,
offload/remesh options and advanced paint controls. The bake-atlas label explains
that exported maps are half the atlas size. No inference defaults changed.

Drag the vertical grips beside the viewer to resize the settings and inspector
panels independently. Desktop widths range from about 260–560 px on the left
and 230–500 px on the right, constrained to retain a 360 px viewer. Smaller
windows share the available width automatically. Each panel keeps its internal
scrollbar; resizing does not reload the asset or reset its camera.

Tab to either divider and use Left/Right arrows (12 px), or Shift+arrow (40 px).
Home/End select that panel's minimum/maximum. Escape cancels an active drag.
Double-click a grip to reset that panel; **Reset layout** at the top restores
both defaults. Widths are saved locally in the browser/application profile for
the server's origin, separately from projects and model settings. If storage is
disabled, resizing still works for the current session.

There is one persistent 3D canvas. Source/result, LOD and material switches
preserve the camera; Fit resets it. Orbit, pan, zoom, wireframe, points, bounds
and environment intensity operate on the real loaded asset. Material inspection
offers only channels actually present, plus clay and a UV checker when supported.
Derived display GLBs live in the runtime cache and never modify the master.
The UV inspector draws actual UV triangle edges; its Analyze UV / PBR action
reports bounded sampled overlap, stretch and density findings with limits.
Channel views use display materials; the Texture inspector
shows the extracted pixels and dimensions directly.

## Project and operation workflow

1. Upload reference photographs or open/import a static, single-material GLB.
2. Select shared image preparation and inspect the resulting image/mask.
3. Generate with TripoSG (one input) or Hunyuan3D-2mv (1–4 named directions).
4. Inspect the result; accept a named checkpoint or discard the working preview.
5. Paint, reduce or enhance the working asset, inspect, then accept again.
6. Export a LOD set and inspect each actual level in the same canvas.

The Project inspector saves image pixels, preparation/masks, mesh copies,
settings, immutable versions, lineage and run provenance. It restores the images
and custom values rather than reapplying a preset. Changing texture settings
marks downstream stages stale when saved/queued, without deleting geometry.
Continue from a historical version creates a recorded branch point. Discard
removes the active preview pointer, retaining its immutable files/history.
Named presets contain settings only and can be applied to another asset.
Legacy settings-only snapshots remain on disk; the new project picker uses the
version-2 owned-asset format. Recreate an old snapshot by opening its mesh and
saving a new project; missing image pixels cannot be recovered from old snapshots.

Projects default to `projects/`; queue, presets, viewer cache and window profile
default to `.runtime/workbench_preview/`. Both locations are configurable in
`config.yaml`. Original/derived project artifact references are relative.
Back up the entire project folder, not only `project.json`. Queue history remains
in its server database; imported project history/provenance remains in its manifest.

## Actual controls

**Inputs:** keep existing alpha/input, BRIA RMBG-1.4, or rembg with selectable
u2net/u2netp/isnet-general-use/silueta sessions. Crop, square resize, padding,
alpha preservation, preview background, supported alpha-matting thresholds,
erosion, mask postprocessing and CPU/CUDA ONNX provider selection are explicit.
Unavailable ONNX providers fail visibly. Preparation is applied once to the
original view; Hunyuan's internal remover is explicitly bypassed. TripoSG receives
a white composite. Prepared alpha masters and masks remain in the project.

**Generate:** model identity, detected local weights and configured runtime,
steps, guidance, seed, face budget and planar projection. TripoSG additionally
exposes octree/dense depths and extraction bounds; Hunyuan exposes volume
resolution, decoder chunks, isovalue and extraction-box scale. Hidden directional
images survive switching to the single-image model. TripoSG folder batch creates
one owned project/job per image. Planar projection is distinct from PBR paint.

**Texture:** Hunyuan3D-2.1 Paint, separate reference, baking views, diffusion
resolution, render/bake-atlas sizes, exponent, merging, remeshing, additional PNG map copies,
mmgp low-VRAM request and post-paint normal baker. Job reports record actual
offload and normal fallback. The upstream exporter halves the bake-atlas size (2048 bake → 1024 exported maps),
and coverage selection can add views beyond the requested budget. The GUI labels
these settings accordingly; operation reports record actual view count, embedded
map dimensions and worker peak memory. Native OBJ/JPG companions are kept even
when additional PNG map copies are disabled.

**Optimize / Surface Lab:** existing UV-aware/geometry decimation with achieved
counts, retained maps and fallback reports; existing enhancement with resolution,
AO rays, normal baker, image-based delight, up axis, material, safe/optimized
mesh mode and separate/packed/both ARMW. Enhancement requires UVs, albedo and
metallic/roughness maps. Advanced topology constraints, UV repacking and MikkTSpace
high-to-low rebaking are not implemented and have no fake enabled controls.
Optimize now supports one to three safe passes, copy-only winding repair,
protected open boundaries, an explicit UV-fallback opt-in, an AABB bounds-change
limit, and a strict triangle budget. Strict misses/attribute failures leave the
accepted mesh untouched and publish no preview. Geometry-only optimization has
no separate island-removal cleanup. `optimization_report.json` records actual
settings, passes, counts, repairs and warnings; PBR pixels/factors and UV validity
are checked after GLB reload. Bounds checks do not establish silhouette quality
or guarantee thin-part retention. A separate deterministic bidirectional sampled
surface-error check defaults to 2% of source diagonal and also rejects excessive
deformation; sampled checks do not establish full silhouette/thin-part quality.
See [OPTIMIZATION_VALIDATION.md](OPTIMIZATION_VALIDATION.md).

**Export:** 1–7 editable budgets, shared PBR maps, reports and GLB/OBJ companions,
editable planning distances in feet and actual LOD switching. Distance preview
uses an explicit metres-per-mesh-unit assumption; normalized AI geometry must
be measured/scaled before physical interpretation. Parent.dat dimensions remain
templates requiring final measurement; the chosen distances are written to the
template. BML conversion and final DDS/BMS authoring remain external Blender/BMS
exporter steps. Export does not deploy into a real BMS installation.

## Inspection and accuracy tools (2026-10-21)

Inputs now offers **Check reference inputs**, alpha/framing metrics and a prepared
mask overlay. Empty foreground and invalid crops fail before inference. Opaque
photo backgrounds, clipped foreground and mismatched Pixal framing warn visibly.
Pixal fixed-orbit checks cannot verify camera calibration or object identity.

Generate offers **Compare generators**: queue selected backends in separate saved
projects, with seed 42, shared preparation and triangle target. Quick/quality
profiles are explicit model-specific shape settings; they do not certify maximum
quality. The repeatable tank/building/jet CLI is `scripts/benchmark_suite.py`;
see [BENCHMARK.md](BENCHMARK.md). Scores require manual reference review.

The same viewer switches between working result, raw decoded master, project
source and accepted version when available. Statistics, texture inspector and UV
inspection follow the displayed mesh; operations continue to use the working
result. Raw selection follows that version's ancestry, not the latest unrelated
generation. New native and Comfy jobs retain `master.glb`; older jobs may lack it.
Comfy cleanup adds bounded sample-distance/bounds reports and optional strict
rejection. These samples cannot guarantee preservation of every antenna/opening.

The UV tab's **Analyze UV / PBR** action calculates sampled interior overlap,
Jacobian anisotropy/stretch and texel density, with three heatmaps and map checks.
Sampling resolution and face/raster work budgets are reported. Shared triangle
edges are excluded; subpixel overlap can be missed. Mirrored/stacked UVs can be
intentional. Missing maps can instead be intentional constant material factors.
This does not automatically repair seams, pack UVs or generate missing maps.

Export includes **Apply measured scale**: supply one output-axis dimension in
metres, source up/forward and pivot. A queued copy-only transform checks material
pixels and GLB round-trip bounds, writes metres/Y-up/+Z-forward and retains the
source. **Check BMS readiness** reports physical bounds, LOD budget/distance
validation, winding, UVs/maps and external BML/DDS/Parent/DOF steps. Measurements
remain user supplied; readiness is for intermediates, not in-game certification.

Comfy jobs consume prompt-scoped WebSocket node/sampler events and poll history
for final completion. UI telemetry distinguishes sampled host Torch allocation
from main-worker memory. The node-based fraction is not a remaining-time estimate;
history polling continues if WebSocket events are unavailable. Host setup has a
read-only disk/driver/model plan and explicit optional installation; see COMFYUI.md.

## Jobs and runtime support

Jobs persist frozen settings and immutable input references in SQLite. One
worker runs at a time, in a separate Python process. Native failures produce
failed jobs and worker logs without terminating the UI. Queued cancellation is
immediate; active cancellation waits for a safe operation boundary. Partial files
remain private `.working` artifacts and are never accepted/published as results.
Progress, measured memory samples, warnings, source/output inspection, errors and
artifact paths are recorded. Global device free memory and worker PyTorch memory
are labelled separately. Rerun uses the frozen request, not current UI fields.

Windows + NVIDIA CUDA is the supported inference target. Shape has a configured,
slow CPU fallback; paint requires CUDA/native rasterizer and RealESRGAN weights.
AMD ROCm and Intel XPU are not wired. CPU rembg preparation is independent of
GPU vendor. Browsing model information does not download or initialize weights.
Actual inference or first-use removal/normal models may download missing weights.

## Development and validation

Typography uses locally served IBM Plex Sans for controls/descriptions,
Montserrat for the wordmark, workflow navigation and section headings, and IBM
Plex Mono for code/log details. Complete Regular/Bold faces are used: Gradio's
Plex SemiBold files contain partial character sets and can mix fallback fonts
within a label. Titles, workflow actions, project-name labels and reference-view
headers/upload prompts are centered; long paths and detailed settings remain
left aligned for scanning. Direction headers have a consistent 25px band and
upload content fits beneath it. No external font service is required.
The asset toolbar stretches Open/New buttons to the same height as the entry
cards. Toolbar cards/buttons use 12px corners and inner entry fields use 8px.

UI: `scripts/workbench_preview.py`. Gradio adapter: `scripts/workbench_service.py`.
Independent services: `scripts/workbench/{schema,projects,preparation,pipelines,
jobs,worker,viewer,runtime,normals}.py`. The new service path does not import
`web_ui.py`. UI and offline Babylon resources require pinned Gradio **6.17.3**;
its bundled viewer integration must be retested before a Gradio upgrade.
The viewer renders on demand: preview updates must call the initialization
details' public `markSceneMutated()` after changing scene settings. Otherwise
display and lighting changes remain invisible until the camera moves.

Run `.venv/Scripts/python.exe -m unittest tests.test_workbench tests.test_readiness`.
Run `node tests/workbench_browser.cjs` against the server with Playwright on
NODE_PATH; `--layout-only` checks 1366×768 and 1600×900. Tests validate owned image
round trips, stage invalidation, source preservation, actual UV/map-preserving
decimation, cancellation, failure handling, camera retention, project reopening
and real LOD export. GPU inference and clean portable builds are separate checks;
see `WORKBENCH_VALIDATION.md` for observed results and remaining release gates.
Run `node tests/workbench_viewer_browser.cjs` for stationary-camera redraw checks:
it uploads an existing GLB, compares actual rendered images for wireframe, solid,
points and lighting, preserves the camera and verifies rendering returns to idle.
`MODELUNIFY_TEST_URL`, `MODELUNIFY_TEST_MESH` and `MODELUNIFY_TEST_OUTPUT` select
the server, read-only source mesh and evidence folder. No inference runs.
