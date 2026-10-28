# Workbench inspection and delivery validation — 2026-10-21

Source: version 1.0, Windows / NVIDIA RTX 3500 Ada 12 GB. Evidence lives in ignored
`.runtime/`; source tests and instructions are retained in the repository.

## Completed functional checks

- Existing 79 regressions plus 18 new CPU/integration tests passed together
  (**97 tests**). Installer preflight/signature and ambiguous-version ancestry
  cases are included in `tests/test_workbench_inspection.py`.
- Synthetic alpha fixtures cover empty foreground, preserved originals, opaque
  background warnings, bbox/overlay geometry, model-specific inputs and mismatched
  fixed-orbit dimensions/crop. Camera calibration is explicitly not certified.
- A two-triangle square has zero sampled shared-edge overlap, unit anisotropy
  and 32 pixels per mesh unit with a 32px atlas. Stacked faces, distorted/invalid
  UVs and raster work truncation are detected. Mirrored intent remains manual.
- Measured box transforms preserve original vertices and map pixels through GLB
  round-trip. A real CPU queue job scales a textured plane to 7m along X while
  preserving its source hash. Invalid/no-op LOD planning is reported.
- A strict Comfy cleanup fixture rejects a shrunken working mesh while retaining
  raw master and comparison evidence. Version ancestry selects the matching raw
  generation despite a newer unrelated generation in the same project.
- Prompt-scoped progress rejects foreign prompts and nonfinite sampler values.
  Actual GPU runs emit native sampler/remesh/decimation node/step events and
  sampled host memory; exact peak allocation and remaining time are not claimed.
- Browser `workbench_inspection_browser.cjs` passed input checks, diagnostic
  results, raw/result switching, camera preservation, queued scaling and readiness
  with one canvas, no page scroll and no browser exceptions. The test found and
  fixed Babylon target-coordinate rebuilding during model replacement. Slow
  inspector callbacks were also separated from viewport updates so their old
  display settings cannot overwrite later wireframe/lighting edits; the existing
  stationary-render image regression passes again.
- Browser `workbench_layout_browser.cjs` passed actual drag/keyboard resizing,
  persistence, reset, Escape, window resize and camera/canvas preservation.
- Embedded CPython can resolve registered full Python without Python/Git on PATH.
  A real pinned-source ZIP download/extraction passed. Installer signature failure
  is separately tested. Tiny isolated installers compiled from the real task/run
  declarations verify optional setup is off by default, Pixal multiview selection
  and no downloads in silent mode. Fresh-machine PSF bootstrap still needs clean
  Windows verification.

```powershell
.venv/Scripts/python.exe -m unittest tests.test_comfyui tests.test_launcher tests.test_workbench tests.test_readiness tests.test_optimization tests.test_workbench_inspection
```

Browser tests use Playwright/Chrome against an isolated validation server. Do not
share the user's active queue/project store with destructive test fixtures.
`MODELUNIFY_TEST_URL` selects the server; the inspection test expects a synthetic
"Inspection fixture" project containing `jobs/fixture/{asset,master}.glb`.

## Reproduction in the application

1. Inputs: check an opaque photo with remover off, then inspect prepared alpha
   and overlay with rembg. Try an empty-alpha image: Generate must reject it.
2. Generate: choose TripoSG (Front only), Hunyuan (1–4 views), TRELLIS (Front),
   then Pixal fixed-orbit mode. Confirm framing/FOV guidance and input checks.
3. Compare generators: queue selected models, then open each saved comparison
   project. Input hashes/settings are frozen; review actual shape from matching
   cameras. Do not infer accuracy from triangle counts alone.
4. Switch raw/result/accepted in the same viewport. Verify labels, statistics,
   texture/UV inspector and stationary camera; operations still use working mesh.
5. UV: analyze a normal atlas and stacked/warped UV fixture; inspect overlap,
   stretch/density maps and sampling limits. Missing maps must be explicit.
6. Export: measure a known dimension, choose source orientation/pivot and apply
   scale. Confirm bounds in metres and original unchanged. Try a no-op LOD ladder:
   readiness must flag it. BML/DDS/game validation remains external.
7. Comfy: check setup plan, then run generation; verify actual node/step text and
   host allocation. Cancel only that prompt. Missing weights must fail readiness;
   Generate must never install runtime packages/checkpoints.

## Benchmark and release gates

The quick suite completed **12/12** real GPU jobs and 36 matching-camera renders.
See [BENCHMARK_WORKBENCH_20261021.md](BENCHMARK_WORKBENCH_20261021.md) for input
loss and cleanup findings. Source photographs/calibrated dimensions are not bundled.

The tank/hangar/F-15 suite uses existing photographs without calibrated reference
meshes or real dimensions. Quick-profile success is workflow evidence. Manual
quality scores, maximum-quality resolutions/atlases, production symmetry/thin-part
accuracy and real-world measurement need separate review. See BENCHMARK.md.

A clean portable candidate and installer are built separately from source tests.
Compiler success, copied-source checks, relocation and clean-machine installation
are distinct gates. Never label a shape-only candidate as including paint native
extensions. Keep old distributions and user projects unchanged.
