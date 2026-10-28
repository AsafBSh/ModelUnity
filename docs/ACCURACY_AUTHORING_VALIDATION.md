# v1.11.0 validation — 2026-10-24

All checks used synthetic two-panel textured geometry and an alpha-masked image
under `.runtime/accuracy-tools/`, with an isolated project store and SQLite queue.
Supplied masters, real projects, weights, the BML Workbench checkout and BMS
installation files were not processed or modified. No AI inference or portable
distribution rebuild was run.

- Full Python regression suite: **122 passed**. This includes manual stroke/RGB
  preservation, image fingerprint and PNG round-trips, known silhouette agreement,
  real protected decimation and post-GLB coordinate checks, real xatlas rebaking,
  guarded high-source projection, owned queued inputs, Wavefront/BMS material
  separation, MTI names, Parent.dat dimensions, map channels and ZIP CRC checks.
- Actual GUI construction/live configuration: **376 components, 70 callbacks**.
- Browser acceptance: painted and applied alpha strokes; compared a masked
  reference; inspected protected triangles and Shift-clicked a real mesh point;
  queued and completed Optimize, Rebake and Export using the actual services and
  subprocess workers. **No browser errors; one 3D viewport; no page scrolling.**
- The saved corrected reference is RGBA and its exact pixel digest is present in
  the saved preparation settings. PNG output is explicit to avoid lossy WebP
  breaking the manual-mask binding. Different directions/reference revisions are
  checked before applying strokes.
- Exported the actual `interchange/`, `bms_handoff/`, package report and checked
  ZIP. Static BMS output contains JSON `Materials.mtl`, matching `Model_0.mti`,
  `Parent.dat`, native-axis/feet OBJ geometry and ALB/ARMW/NOR source PNGs.
  The package correctly reports `bms_ready=false` and lists external BML/DDS,
  registration and runtime checks.
- High-DPI layout passed all workflow stages at 1280×720, 1366×768, 1536×864 and
  1600×900. Keyboard model selection/focus and 16 px panel scrollbars remain.
- Stationary-camera rendered-image checks passed wireframe, solid, points and
  environment intensity changes, followed by return to idle.
- Windows-reserved sockets are excluded by real bind probes. Three launcher
  regressions cover reserved ports, owned-server reuse in the fallback range and
  Windows sockets that cannot be rebound after a failed connection attempt.
- Actual idle source server restarted successfully. The dedicated application
  window opened on localhost:7861 and its live configuration confirmed v1.11.0.

Browser evidence and logs: `.runtime/accuracy-tools/browser.log`,
`mask-editor.png`, `reference-overlay.png`, `protected-selection.png`,
`rebaked-preview.png`, `export-handoff.png`, `layout.log`, and `viewer.log`.
Regression evidence: `.runtime/accuracy-regressions-release.log`.

This validates implemented CPU behavior and interface wiring, not calibrated
reconstruction accuracy or BMS renderer parity. Native tangent normals are not
certified MikkTSpace; projection can cross nearby surfaces. Protection applies
to the selected Optimize operation and is not inherited by later remeshing/LODs.
The BMS handoff is limited to static opaque single-sided assets, one skin and
one material slot per LOD. Only Parent.dat is authored; other global database
records require object/theater information and external authoring.
