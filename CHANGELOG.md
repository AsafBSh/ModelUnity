# ModelUnify changelog

Use `scripts/_version.py` as the version source. Every delivered change set gets
a version bump and a dated entry here. Fixes increment the patch version;
features increment the minor version; breaking changes increment the major
version. Explicit user version requests take precedence.

## [1.11.2] — 2026-10-28

- Removed downloaded AI weights while retaining runtimes, native modules and user
  assets; verified offline application/CPU behavior and documented restoration.
- Added the template-based practical GUI/model operating guide, vendor provenance
  and a contribution workflow for source-only GitHub publication.
- Added dependency-free source/asset checks. Historical v1.0 distributions retain
  their labels and were not rebuilt.

## [1.11.1] — 2026-10-26

- Storage maintenance: retire obsolete v1.0/RC1 distribution binaries and the
  duplicate RC2 installer/extracted runtime after validating the retained RC2
  archive and preserving historical source differences and unique local files.
- Remove source-backed bytecode, inactive app-profile caches and already-installed
  bootstrap downloads. Preserve browser preferences/local storage, real projects,
  source assets, weights, native extensions and separate model environments.
- Apply denser transparent compression to large inactive libraries. See
  `docs/WORKSPACE_CLEANUP_20261026.md` for measured savings, recovery and checks.
  No inference, distribution rebuild, commit or BMS deployment was performed.

## [1.11.0] — 2026-10-24

- Add editable foreground/background alpha strokes bound to exact image pixels;
  corrected views survive saved projects and bypass a hidden second remover.
- Add an orthographic reference-overlay inspector with user alignment, silhouette
  IoU and boundary-distance metrics, with explicit calibration limitations.
- Add protected regions, triangle IDs and sharp-edge selection for optimization,
  with exact protected triangle checks and copy-only selection overlays.
- Add queued xatlas UV reparameterization and CPU high/source-to-low PBR rebaking,
  bounded projection distance and a retained high-source input. Tangent normal
  transfer is not certified MikkTSpace.
- Add general OBJ/MTL/PBR interchange and optional static BMS handoff: distinct
  BMS JSON Materials.mtl, ordered per-LOD MTI, Parent.dat matching staged XYZ/feet
  geometry, editable wetness and a next-steps guide. BML/DDS generation, global
  database registration, animated/effect authoring and runtime acceptance remain
  external. Existing portable distributions are unchanged.
- Package the new interchange/handoff as a CRC-verified ZIP. Preserve RGBA inputs
  losslessly as PNG. Probe Windows socket binding and use a fallback port range
  when Windows reserves otherwise-unoccupied default application ports.

## [1.10.2] — 2026-10-23

- Revert the v1.10.0 GUI redesign at the user's request. Restore the previous
  windowed Mesh Workbench: logo/header, asset toolbar, settings, viewport controls,
  inspector order, typography, colors and panel defaults.
- Recover the interface from provenance-verified pre-redesign copies; keep the
  current application version and v1.10.1 startup/progress fix. No pipeline,
  project, model-weight or portable-distribution rollback.
- Remove the rejected design module, design-specific browser test and persistent
  design guidance so they cannot steer future edits back to the rejected UI.

## [1.10.1] — 2026-10-23

- Fix the blank-console startup experience: print an immediate batch banner,
  report server discovery/loading progress and elapsed time, and show the ready
  URL before opening the application window.
- Start the workbench with unbuffered output and mark each startup in server.log
  so current diagnostic messages are available while startup is in progress.
- Preserve existing-server reuse, installation identity checks and the JSON-only
  Python `--check` output. Existing portable distributions were not rebuilt.

## [1.10.0] — 2026-10-23

- Apply the approved charcoal-and-teal Mesh Workbench design with a compact
  project header, workflow navigation, larger persistent viewport and focused
  settings/inspector panels. Consolidate the overlapping style layers.
- Move environment/bounds controls into the Material inspector; add the displayed
  asset heading, top-level project saving and a live queue summary/Jobs shortcut.
- Simplify Texture setup with the real quality/atlas controls and collapsible
  advanced settings, normal baking and pipeline requirements. Preserve processing
  defaults, checkpoint behavior and GPU requirements.
- Source update only; existing portable distributions keep their original versions.

## [1.9.1] — 2026-10-23

- Workspace maintenance: remove regenerable bytecode, linter cache and disposable
  build bootstrap staging; retain sourceless bytecode and all dependencies.
- Verify archived releases before pruning redundant extracted copies; retain
  unmatched files and existing release archives with their original labels.
- Transparently compress retained local files using Windows filesystem compression.
  Source assets, model weights, saved projects and job history remain available.
- Ignore future Ruff cache files. See `docs/WORKSPACE_CLEANUP.md` for measured
  results, retained state and validation. No distributions were rebuilt.

## [1.9] — 2026-10-21

This release names the current source baseline v1.9 at the maintainer's request.
No intermediate 1.1–1.8 releases are implied.

### Included in this baseline

- CAD Mesh Workbench with one persistent inspection viewport, resizable side
  panels, model-aware inputs and advanced settings, and its own application window.
- TripoSG, Hunyuan3D-2mv and Paint workflows, plus isolated ComfyUI hosting for
  TRELLIS.2 and Pixal3D.
- Input/mask readiness and framing checks, reproducible four-generator benchmarks,
  retained raw masters and result/checkpoint comparisons.
- Bounded optimization guards; UV/PBR overlap, stretch and density inspection;
  measured scale, orientation, pivot and intermediate BMS readiness checks.
- Prompt-scoped ComfyUI progress/memory reporting and optional isolated setup.
- Persistent release numbering and changelog guidance for subsequent changes.

### Validation and limits

- Prior baseline validation: 97 Python tests, browser layout/interaction checks,
  and 12/12 quick GPU shape benchmarks. Details and quality caveats are recorded
  in `docs/WORKBENCH_INSPECTION_VALIDATION.md` and
  `docs/BENCHMARK_WORKBENCH_20261021.md`.
- This version change is validated separately with launcher tests and a live GUI
  startup check; it does not repeat GPU inference or rebuild portable packages.
- Existing v1.0 distribution artifacts remain v1.0. Final BML/DDS conversion
  remains external, and benchmark completion does not certify model accuracy.

## [1.0] — Earlier baseline

Existing source and portable/RC artifacts used version 1.0 before this changelog
was introduced. Original artifact names and delivery reports remain historical
records; an exact initial release date is not asserted here.
