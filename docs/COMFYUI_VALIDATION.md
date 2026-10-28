# ComfyUI integration validation — 2026-10-21

Source integration tested on Windows with NVIDIA RTX 3500 Ada 12 GB, driver
596.72. ComfyUI 0.42.0, commit `7a28332047b6af638dc6c7f72ef3481a718769fd`,
Python 3.11.9, torch 2.14.1+cu130 in `.runtime/comfyui/python`.
The existing ModelUnify environment retains torch 2.5.1+cu124 / Gradio 6.17.3.

## Checks passed

- 79 Python regressions: 62 existing and 17 ComfyUI graph/transport/hosting cases.
  Covers parameter bindings, checkpoint schemas including V3 combos, saved settings,
  complete GLB transfer, empty `/free` responses, targeted cancellation, failure
  cleanup and protection of another host/job's resources.
- Main workbench and legacy UI construct; changed Python sources compile.
- Browser switching across all four generators, single-image versus Pixal
  multiview visibility, and the actual **Check model** button pass with no page errors.
- Single-window layout passes at 1280×720, 1366×768, 1536×864 and 1600×900,
  device scale 2, retaining one viewer, keyboard focus and 16px scrollbars.
- All three installed checkpoint variants pass live `/object_info` preflight.
- Owned host stop/start succeeds, including the Windows venv redirector's child
  process. Shared/external hosts are not stopped; idle owned models unload.

## Live inference

TRELLIS.2, Pixal3D single-image with automatic MoGe FOV, and Pixal3D fixed-orbit
four-view inference all completed at shape resolution 512. Single-image fixture:
the official `viking_wolf_rune_axe.png`; multiview fixture: the official
`character_turnaround_4view_sheet.png`, cropped using its template's four regions,
equally padded, with shared rembg preparation. Both originals are retained.

Raw decoded meshes have substantial geometry and may contain inconsistent winding
and disconnected indexed components. The first TRELLIS.2 raw PBR run produced a
valid GLB but reconstructed background geometry; it is **not an accepted quality
result**. Visual inspection caught this after format checks passed. Explicit rembg
foreground extraction produced a recognizable axe with PBR maps in the viewer.
Use isolated foregrounds on black/alpha; do not treat transport success as accuracy.

With solid remeshing at 512 and a 200,000-face working budget, the CLI produced
199,932 triangles, valid UVs, embedded base-colour/MR maps, consistent winding and
no indexed non-manifold edges. The raw master remained separately retained.
The UV-seamed GLB was not reported watertight; indexed components/edge counts
include chart seams. This does not establish printability or manifold solid quality.

The real browser Generate action also passed: image → frozen project request →
isolated worker → ComfyUI → validated preview → PBR viewer/maps. With explicit
rembg it produced 199,936 triangles and 1024-pixel PBR maps. The saved project is
`projects/comfy_browser_validation_b6db391445`; its job is
`c649bcbe0c2846bcbc3b2f715fc12ad4`. Evidence lives in its `jobs/` and `logs/` folders.
The submitted settings specify 512 diffusion, 512 solid remesh, 200,000 target,
12/20/12 structure/shape/texture steps, seed 42. Cleanup and normalized-scale
warnings remain visible; no BMS deployment occurred.

Runtime evidence (ignored generated files):

- `.runtime/comfyui/validation/trellis-512-r2/`: initial raw/background case.
- `.runtime/comfyui/validation/pixal-512/`: single-image shape/MoGe check.
- `.runtime/comfyui/validation/pixal-mv-512/`: four-view shape check.
- `.runtime/comfyui/validation/trellis-clean-pbr/`: explicit cleanup/PBR CLI check.
- `.runtime/comfyui/validation/ui/`: browser result JSON and screenshots.
- `.runtime/comfyui/hosts/`: host log and verified process identity.

## Repeat

```powershell
.venv/Scripts/python.exe -m unittest tests.test_comfyui tests.test_launcher tests.test_workbench tests.test_readiness tests.test_optimization
.venv/Scripts/python.exe -m scripts.comfyui_host status --model pixal-mv
node tests/workbench_comfyui_browser.cjs --host
node tests/workbench_browser.cjs --layout-only --high-dpi
```

`MODELUNIFY_TEST_URL` selects a running workbench. Browser automation needs
Playwright and Chrome. `workbench_comfyui_browser.cjs --infer` explicitly runs real
GPU inference and creates a new diagnostic project; supply `MODELUNIFY_TEST_REFERENCE`
or retain the official example at `.runtime/comfyui/validation/axe.png`.

## Remaining validation

Representative tank/building/jet reconstruction, silhouettes, symmetry, thin parts,
measured dimensions, Pixal PBR visual quality, 1024/1536 shape inference, 768 remesh,
QEF edges and larger atlases still require targeted quality/memory checks. The
current working-mesh defaults follow the official cleanup approach, but only
512 remesh / 200,000 faces were measured here. No universal VRAM minimum is claimed.
A clean-machine installer/portable build with this optional runtime remains separate.

Official fixtures and templates are from
[Comfy-Org workflow templates](https://github.com/Comfy-Org/workflow_templates).
Checkpoint revisions and byte sizes are retained in
`.runtime/comfyui/ComfyUI/models/modelunify_downloads.json`.
