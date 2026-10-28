# Workspace cleanup — 2026-10-23

Historical record. Later cleanup: [2026-10-26 storage maintenance](WORKSPACE_CLEANUP_20261026.md).
Some distributions retained below were subsequently retired; consult that report
for the current archive and recovery locations.

Source version: **v1.9.1**. This is storage maintenance; no portable release was
rebuilt, no model was uninstalled and no GPU inference was run.

Measured large-file compression and duplicate removal reclaimed **at least
17.416 GiB**, plus the cache/staging cleanup and an earlier small-file compression
pass. This excludes unrelated changes to drive-wide free space.

## What was cleaned

- Removed 38,306 regenerable Python bytecode files only where matching source
  exists, plus Ruff cache and three disposable build bootstrap directories.
  Sourceless bytecode, package test modules, native extensions and licenses stay.
- Compressed 1,602 large retained files using transparent Windows XPRESS8K
  compression, reclaiming **7.547 GiB** in that measured pass. Files retain their
  names and can be opened normally; no manual extraction is required.
- Compared portable releases with their archives using complete archive integrity
  tests and per-file CRC32/size comparisons. Unmatched or modified files are
  preserved separately before pruning redundant extracted copies.
- Removed the extracted RC1 folder (**5.509 GiB** of verified duplicates) and
  legacy v1.0 portable folder (**4.360 GiB** on disk). Retained RC1's **2,402**
  unmatched/modified files in `.runtime/retained-release-files/ModelUnify Workbench RC1/`.
  The legacy folder matched its archive completely and needed no overlay.
- Kept the latest extracted **ModelUnify Workbench RC2**, all release archives,
  the installer, source code, model weights, environments and project state.
- Updated the version/changelog, ignored Ruff cache and condensed outdated
  validation chronology in the current Codex handoff.

## Recovery and retained state

Launch the current source using root `run_modelunify.bat`. Existing v1.0 release
archives and installer keep their original labels and contents. To restore an
older extracted build, extract its archive into a fresh directory and apply its
matching `.runtime/retained-release-files/<original folder>/` overlay if present.
An overlay contains only local differences and is not a standalone application.

Inputs, output meshes, BMS exports and saved projects retain their paths and
contents. Job history, settings, browser profiles, validation evidence and
downloaded models remain. Windows transparently decompresses compacted files on
read; compaction may add some CPU work during loading.

No global user caches, unrelated projects or operating-system files were cleaned.
Drive-wide free-space changes may include activity outside this workspace, so the
measured per-file savings are the relevant cleanup figures.

## Validation

- **97 regression tests passed** during the maintenance validation.
- Workbench construction passed: **327 components, 63 events**.
- Launcher readiness passed and found the dedicated Edge application engine.
- Environment validation passed with CUDA available on the RTX 3500 Ada,
  native rasterizer, mesh inpaint, Paint, RealESRGAN and mmgp imports available.
- All **1,042** input/output/project/BMS-export SHA-256 checksums match.
- All **116** model files retain their paths and sizes; **60** Python source
  files passed syntax parsing. Weight inventories are not full model SHA checks.
- All three portable archives passed integrity tests. Full CRC32/size comparisons
  covered 33,460 matching RC1 files, all 42,400 legacy portable files and 33,589
  RC2 files. RC2's 58 extra local files stay in its retained extracted folder.
- Isolated ComfyUI core imports passed with CUDA available. Memory mapping and
  small tensor reads passed for TripoSG, TRELLIS.2 and both Pixal3D checkpoints.

Machine-readable evidence lives in ignored `.runtime/cleanup-20261023-*` files:
the baseline inventory, removal manifest, compression measurements, archive
comparisons, protected asset hashes, pruning manifest and validation logs.
