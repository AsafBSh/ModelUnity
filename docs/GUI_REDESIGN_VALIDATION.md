# Mesh Workbench design implementation — 2026-10-23

**Historical report: this redesign was rejected by the user and reverted in
v1.10.2.** It is not the current interface or a design direction to reapply.
See `GUI_REVERT_VALIDATION.md` for the restored windowed workbench.

## Launcher follow-up — v1.10.1

The reported blank-console launch was traced to silent cold startup: the server
started at 21:19:10 and the app-window process appeared at 21:20:52. The live GUI
returned HTTP 200 and rendered the workbench/canvas with no browser errors.
The normal application launch also succeeded during diagnosis.

The batch launcher now prints immediately. The Python launcher reports progress
and elapsed seconds, the ready URL and existing-server reuse. Server output is
unbuffered and each new start is marked in the log. All **11 launcher tests**
and syntax checks pass, including new cold-wait, failure, timeout, reuse,
unbuffered-command and JSON-only readiness regressions. This improves startup
visibility; it does not claim to shorten cold library loading. Portable packages
were not rebuilt.

Source version: **1.10.0**. The user approved the generated charcoal/teal
workbench concept and requested implementation in the existing application.

## Delivered

- One presentation module, `scripts/workbench/appearance.py`, replaces the
  overlapping stylesheet layers in `scripts/workbench_preview.py`.
- Compact project header and workflow strip with working New/Save actions.
- Stage-specific settings headings, a larger persistent Babylon viewport,
  displayed-asset/role heading and compact checkpoint/status controls.
- Material/Mesh/UV-first inspection; the Material inspector owns channel
  selection, embedded maps, environment intensity and bounds. Other inspectors
  remain available through Gradio's overflow menu.
- Texture quality and actual exported map resolution appear first. Preserve
  all processing defaults, remesh/offload options, advanced controls, normal
  baking, requirements and warnings.
- Single-line footer with actual queue counts and a working Jobs shortcut.
- Existing pointer/keyboard panel sizing and profile persistence remain intact.

The concept's model and numbers were illustrative. The implementation displays
real meshes/maps/metrics and retains the actual one-image paint-reference path.
The exporter still downsamples bake atlases by two; resolution choices say so.
The existing viewer's real orbit/pan/zoom/fit controls remain; no decorative
orientation cube or grid button was added that pretends to control the scene.

## Validation

All checks below passed against the source workbench on localhost:7861.

- `python -m unittest tests.test_launcher tests.test_workbench
  tests.test_readiness tests.test_optimization`: **62 tests passed**. Expected
  failure-path fixtures print exceptions; the suite result is OK.
- `python -m scripts.workbench_preview --check`: construction succeeds with
  the expanded UI/event graph; no inference is performed.
- `python -m scripts.launch_workbench --check`: source launcher, interpreter,
  Edge application-window engine and live server detected.
- Syntax compilation of the four changed GUI modules passes.
- `node tests/workbench_browser.cjs --layout-only --high-dpi`: all five workflow
  stages fit 1280×720, 1366×768, 1536×864 and 1600×900 at device scale factor 2;
  keyboard model selection, visible focus and 16 px scrollbars pass.
- `node tests/workbench_layout_browser.cjs`: pointer/keyboard sizing,
  persistence, reset, Escape cancellation, 900 px clamping, single canvas,
  unchanged asset and camera pass. Reset defaults: left 310 px/right 285 px.
- `node tests/workbench_viewer_browser.cjs`: real rendered images change for
  wireframe, solid, points and environment intensity with a stationary camera;
  the same viewer returns to idle after each change.
- `node tests/workbench_design_browser.cjs`: desktop/laptop/900 px layout,
  compact footer, stage headings, inspector controls, Jobs shortcut, displayed
  asset heading, retained images/camera and New asset empty state pass.
- `node tests/workbench_browser.cjs`: real CPU optimization produces **7,999
  triangles**, two LODs export, a preview is accepted as a checkpoint, project
  pixels/custom settings save and restore, and the camera survives channel
  switches. No browser errors.
- `node tests/workbench_comfyui_browser.cjs`: all four shape-model selections,
  Pixal multiview and backend-specific fields pass without inference.
- Impeccable's mechanical detector returns `[]` for the changed GUI modules.
- Independent visual review requested a material-gallery correction. The final
  gallery uses natural full rows, readable captions below images and only the
  outer inspector scrollbar; compact-width browser assertions pass. The reviewer
  scored that fix resolved with disposition **ship** and no visible regressions
  introduced by the correction.

The implemented visual system is recorded in root `DESIGN.md` and
`.impeccable/design.json` for future interface changes.

Browser captures/reports are under `.runtime/gui-redesign/`, including
`design/texture-1600.png` and `design/texture-1280.png`. These are actual app
captures, not generated concept images. The supplied residential GLB is only
viewed or copied into owned test projects; its master remains intact.

## Scope and limits

Windows/Chromium is the validation platform. The GUI redesign adds no GPU
dependency and does not change existing NVIDIA CUDA/CPU/AMD/Intel support.
GPU inference, portable rebuilding, clean-machine installation and BMS
deployment were not run. Existing distributions retain their historical versions.
