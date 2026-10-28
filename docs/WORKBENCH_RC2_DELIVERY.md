# Mesh Workbench RC2 delivery — 2026-10-21

The six priorities are implemented in the root sources: input/mask readiness,
reproducible generator comparison, raw/working/accepted inspection, UV/PBR
diagnostics, measured scaling/intermediate BMS readiness, and native Comfy
progress plus explicit optional runtime setup. See WORKBENCH.md for the controls.

## Build and launch

- Fresh candidate: `dist/ModelUnify Workbench RC2/`. Run its `run.bat` to use a
  separate application window/installation identity. Existing distributions and
  the running source application were preserved.
- Portable archive: `dist/ModelUnify-1.0-Workbench-RC2.7z`, **1,920,198,360 bytes**.
  CRC/integrity passed; the archive scan found zero user/QA-data entries.
  SHA-256: `cd8a654d4c91e719a012adbdd45f0c146f8a3e3e55575571d482f75837e2cdfb`.
- Classic installer: `dist/ModelUnify-1.0-Workbench-RC2-Setup.exe`,
  **2,885,487,774 bytes**. Inno Setup 6.7.3 compilation passed with fast LZMA2
  compression; `.sha256` companion files are provided for both packages.
  Installer SHA-256: `62353c2616ba9ad4a66cd2a7b0105fc3baf09ae0c4f687c932e86ab9ee3acab7`.

The candidate uses clean pinned Python dependencies, plus the validated reused
Windows CPython 3.11 / torch 2.5.1+cu124 paint binaries and RealESRGAN checkpoint.
Native extensions were not recompiled. Paint prerequisites, native imports and
CUDA availability pass; this is not fresh paint inference on a clean machine.
`BUILD_PROVENANCE.json` records 77 source hashes and native binary hashes.

Comfy runtime/weights are not bundled. `Setup ComfyUI.bat` explicitly installs
selected models into a separate environment after disk/driver checks. An existing
compatible localhost Comfy host can also be used. Reference photographs and
existing user projects are not bundled; retain/back up their original directories.
The bundled benchmark JSON is a template requiring local input paths.

To use root source changes with existing projects, restart the source server.
Closing its application window alone leaves that server running. The validation
servers were closed; the user's application and Comfy host were left untouched.

## Evidence and limits

- **97 tests passed**, including real synthetic GLB/queue scaling, source hashes,
  UV geometry, strict cleanup rejection, version ancestry and installer failures.
- Source and clean-candidate browser checks pass: one canvas, no page scrolling,
  1280×720 through 1600×900 at 2× DPI, keyboard/model-aware inputs, and immediate
  stationary-camera display/lighting updates. Source inspection tests also pass
  raw comparison, UV diagnostics and queued scale/readiness.
- **12/12** real quick-profile generator jobs completed, with 36 matching-camera
  renders. All nine original reference-image hashes and the supplied residential
  master hash remain unchanged. See BENCHMARK_WORKBENCH_20261021.md for findings.
- Isolated installer fixtures verify compilation, optional setup off by default,
  Pixal multiview task selection, no downloads in silent mode, and exclusion of
  project/runtime/cache/input markers. They do not certify a fresh Windows install.

Remaining gates: clean-machine installation/uninstallation, the no-Python PSF
bootstrap path on that machine, and quality-profile/atlas/accuracy evaluation.
The hangar baseline loses supports during background removal; repair/approve masks
before using it to rank models. Geometry cleanup exceeded the default sampled
2% surface limit in the quick Comfy cases; warning mode retains results for review,
while strict mode rejects them. Scores and real-world accuracy are not certified.
UV diagnostics are on-demand: analyze again after choosing a different asset.
