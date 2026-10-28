# Previous windowed GUI restored — 2026-10-23

Source version **1.10.2** restores the windowed Mesh Workbench at the user's
request. The separate legacy Gradio UI was not substituted.

## Recovery

Compared the current UI against the pre-redesign RC2 copies before restoring.
Each recovered source file matched its SHA-256 in the retained RC2
`BUILD_PROVENANCE.json`. Differences were confined to the rejected GUI changes.

Restored root development files:

- `scripts/workbench_preview.py`: previous layout, styling, logo, typography,
  toolbar, controls, inspector order and original event wiring. Content matches
  the pre-redesign copy except the current version's `v` prefix in the header.
- `scripts/workbench/layout.py`, `scripts/workbench/viewer.py` and
  `scripts/workbench_service.py`: byte-identical to the verified previous copies.
- Browser-test labels/selectors return to the restored interface.

Removed the redesign-only appearance module, browser test, DESIGN.md and
Impeccable design guidance. The rejected state is backed up locally under
`.runtime/gui-revert/before/`; historical release notes remain accurate.

The application remains current version 1.10.2, with the v1.10.1 startup-progress
and unbuffered-logging fix. No engine, configuration, project, master asset,
weight, saved job or portable distribution was rolled back.

## Verification

- All **68** tests pass in `tests.test_launcher`, `tests.test_workbench`,
  `tests.test_readiness` and `tests.test_optimization`.
- UI construction returns the original **327 components / 63 events**.
- The actual `run_modelunify.bat` launch restarted the verified idle source
  server and opened the restored application window on localhost:7861.
- High-DPI browser layout passes at 1280×720, 1366×768, 1536×864 and 1600×900,
  across all workflow stages, with keyboard focus/model selection intact.
- Panel resizing, saved widths, keyboard controls, reset, drag cancellation and
  900 px clamping pass. Defaults are restored to 340 px left / 310 px right.
- Wireframe, solid, points and environment intensity change rendered images with
  the same stationary camera; rendering returns to idle.
- An actual browser capture confirms the original logo/header, asset toolbar,
  viewport material controls, PBR inspector and single canvas, with no browser
  errors. Screenshot: `.runtime/gui-revert/restored-windowed.png`.

No GPU inference, portable rebuild, publication or BMS deployment was performed.
