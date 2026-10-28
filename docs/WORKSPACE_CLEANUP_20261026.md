# Workspace storage maintenance — 2026-10-26

Source version: **1.11.1**. Root `run_modelunify.bat` still uses the retained
development source and environment. No application features, model settings or
inference defaults changed. No distributions were rebuilt or relabeled.

## Cleanup and retained files

- Retired the obsolete v1.0 portable and RC1 runtime archives, plus the RC2 setup
  executable and its checksum. The latest RC2 `.7z` and checksum are retained.
- Before deletion, verified the retained RC2 archive with a complete 7-Zip CRC
  test and SHA-256: `cd8a654d4c91e719a012adbdd45f0c146f8a3e3e55575571d482f75837e2cdfb`.
- Preserved all 40 differing non-runtime files from the two older releases in
  two checked source-history ZIPs. Their manifests identify unchanged files in
  the retained RC2 archive. Old Python runtimes are intentionally retired; these
  source-history deltas are not standalone runnable distributions.
- Compared the extracted RC2 with that archive: 33,589 files match. Preserved its
  58 unique files under `.runtime/retained-release-files/ModelUnify Workbench RC2/`
  before removing the duplicate extracted runtime.
- Removed source-backed Python bytecode and inactive private app-profile caches,
  including regenerable browser components. Browser preferences/local storage,
  project/queue databases, native modules and sourceless bytecode remain.
- Removed already-installed Python/Inno Setup bootstrap downloads. Kept the
  compiler tools, native paint wheel backups, source patches and licenses.
- Recompressed large inactive native libraries using transparent Windows LZX
  compression. Main and ComfyUI environments remain separate and usable in place;
  model weights were not removed or recompressed during this pass.

No files in unrelated projects, global user caches or the BMS installation were
cleaned. Original inputs, outputs, saved projects and BMS exports are retained.

## Recovery

The remaining distribution is `dist/ModelUnify-1.0-Workbench-RC2.7z`. It is still
version 1.0; the current source is 1.11.1. Extract that archive into a new folder
if the older portable runtime is needed. Apply the matching retained-release
overlay to restore its local differences. Source updates still need a new build
before they appear in a portable distribution.

Historical source deltas live under
`.runtime/cleanup-20261026/source-capsules/*-source-history.zip`.
Their `SOURCE_HISTORY.json` files describe the original non-runtime file tree,
the base archive SHA and the exact preserved differences. Earlier RC1 local
differences remain under `.runtime/retained-release-files/ModelUnify Workbench RC1/`.

## Measurements and checks

The before inventory measured **47.214 GiB** of stored project data and about
**31.7 GiB** free on C:. Deletion alone reclaimed **10.833 GiB**, plus separately
recorded library-compression savings of **0.714 GiB** across 126 libraries.
Total measured recovery is **11.547 GiB**; C: had about **43.3 GiB** free at the
final measurement. No compression errors were reported. Measurements use per-file stored sizes;
drive-wide free-space changes can also reflect unrelated activity.

All **1,092** protected input/output/project/BMS-export SHA-256 hashes match.
All **116** model files retain their original paths and sizes. Machine-readable
removal, compression, source-retention and validation records are in ignored
`.runtime/cleanup-20261026/`.

Post-cleanup validation passed: **122 regression tests**, launcher readiness,
GUI construction (**376 components / 70 events**), native painting/rasterizer/
mesh-inpaint imports, and the isolated ComfyUI runtime with CUDA available.
Source syntax checks passed. No inference or GUI server was left running by
these checks. Native libraries remain transparently readable in place.
