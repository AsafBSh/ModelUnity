# Workbench validation — 2026-10-20

Reference: Windows, Python 3.11, Gradio 6.17.3, NVIDIA RTX 3500 Ada Laptop
(12 GiB). Product version remains `scripts/_version.py` → 1.0.

## Passed

- **47 launcher/service/readiness regression tests**, including owned-image/alpha and
  mesh round trips, clearing views, relative artifact paths, rejecting escaped
  paths, texture-only settings/reference invalidation, preview/accept/discard, failure handling,
  safe cancellation, persistence, packed-channel extraction, actual UV-aware
  decimation/map retention, bypassing hidden Hunyuan removal, and preserving
  default dtype on initialization failure. Existing export/deployment/lifecycle
  regressions pass. New coverage verifies installation ownership, automatic port
  selection, foreground launch and queued/completed jobs after relocation,
  including legacy absolute-path migration, unmet generation budgets, inconsistent
  winding and completed-job warning visibility. Log: `.runtime/workbench-release-tests.log`.
- **Real Chrome/Playwright workflow** against the current server: one/four input
  switching, presets, custom steps, camera preservation across material and
  wireframe switching, project save/reopen, accepted checkpoint, UV inspection,
  actual optimization and two-level shared-PBR export. **Zero browser errors.**
  The 40,000-triangle residential master reached **7,999** for an 8,000 target.
  Target misses/fallbacks are reported, not silently relabelled as achieved.
- **Compact layout:** 1280×720, 1366×768, 1536×864 and 1600×900, all five stages,
  one canvas, no document scrolling, internal panel boundaries, 16px visible
  scrollbars. Device scale factor 2, keyboard model selection and visible focus
  also passed. Evidence: `.runtime/workbench-dpi.log`.
- **Dedicated window launched and verified:** Edge `--app=` with private profile,
  MainWindowTitle `ModelUnify · Mesh Workbench`; localhost port 7861. This is a
  Chromium application window, not a new native rendering toolkit.
- **Relocated source and bundled interpreter checks:** copied scripts/assets/
  configuration into a temporary path containing spaces, used the existing
  portable Python (without copying/modifying dist), and constructed the workbench
  and checked the launcher successfully. Log: `.runtime/workbench-relocation.json`.
  This verifies source/bootstrap/resource discovery, not a clean distribution.
- A new-service Hunyuan run completed shape generation: **15 steps, octree 256,
  5,000 output faces**, with original alpha preparation. This is a synthetic
  lifecycle diagnostic, not a production visual-quality benchmark. Evidence:
  `.runtime/workbench_gpu/1792480877083136600/validation.json`.
- Actual isolated-worker/native failure handling was exercised during GPU
  diagnosis. Jobs recorded failure/log paths and the UI stayed available. A
  Windows progress-file replacement race was reproduced and fixed with bounded
  atomic-replacement retries. Failed/private outputs were not published.

Screenshot: `.runtime/workbench_preview/screenshots/cad-workbench-final.png`.
Tests: `tests/test_launcher.py`, `tests/test_workbench.py`, `tests/test_readiness.py`,
`tests/workbench_browser.cjs` (`--layout-only` for compact checks).

## Preview redraw correction — 2026-10-20

Reproduced a stationary-camera wireframe change that updated the scene setting
but rendered no new frame. Preview updates now call the Babylon viewer's public
`markSceneMutated()` hook after applying settings. Rendering remains on demand.

`tests/workbench_viewer_browser.cjs` passed against the source server (7861) and
the unpacked portable candidate (7862): actual image changes for wireframe,
solid, points, dark environment and bright environment; unchanged camera and
scene; rendering returns to idle; zero browser errors. Python/Node syntax checks
passed. No inference or mesh processing ran and the residential master SHA-256
remained unchanged. Evidence: `.runtime/viewer-redraw-source/` screenshots and
`.runtime/viewer-redraw-portable/report.json` plus screenshots.

Both idle servers were restarted with the corrected source. Existing windows
need reloading to receive the new frontend code. The unpacked RC records this
post-archive update in its provenance; the original RC1 `.7z` and checksum were
preserved and do **not** contain this correction.

## Typography and alignment refresh — 2026-10-20

Centered panel titles, workflow text, asset-field captions, direction headers
and upload prompts; unified IBM Plex Sans/Montserrat/Plex Mono typography,
line spacing, button baselines and numeric figures. Chrome's actual-glyph font
inspection exposed mixed fallback letters in the bundled Plex SemiBold faces;
complete Regular/Bold faces now render the inspected English labels entirely
with local custom fonts. Source syntax checks and the existing high-DPI layout
checks passed at 1280×720, 1366×768, 1536×864 and 1600×900: one canvas, no page
scroll, 16px panel scrollbars, keyboard model selection and visible focus.
No inference, mesh processing or dependency installation was needed.

Source evidence: `.runtime/typography-final.json`, `.runtime/typography-final.png`
and `.runtime/typography-final-layout/compact-workbench.png`.
The unpacked portable candidate passed the same glyph-font inspection and four
high-DPI layout checks. Evidence: `.runtime/typography-portable.json`,
`.runtime/typography-portable.png` and `.runtime/typography-portable-layout/`.
Both idle servers were restarted; existing windows need reloading. The original
RC1 archive remains unchanged.

## Final GPU and Surface Lab evidence

- Two complete Hunyuan shape→paint cycles passed through isolated workers,
  followed by TripoSG generation and a real PBR paint of its result. All used
  cached weights/offline mode on the 12 GiB reference GPU. Shape diagnostics used
  15 steps, MV octree 256 or TripoSG depth 8/dense depth 7, seed 42, 5,000 target
  faces. These tests establish functionality/lifecycle, not production quality.
- Paint used resolution 512, render 512, bake atlas 1024, normal off and requested
  view budget 4. Measured: **6 actual coverage views**, **512×512 exported albedo
  and metallic/roughness maps**, **mmgp active**, approximately **6.46 GiB peak
  worker PyTorch allocation**. The upstream exporter halves the bake atlas.
  UI labels now explain both behaviors, and reports include measured values.
- Additional PNG map copies are actually written when requested; the scalar
  roughness/metallic files use glTF G/B correctly. The final TripoSG paint
  produced a 4,981-face textured result with embedded maps and PNG companions.
- Surface Lab ran through the real worker at 1024 resolution with mesh normals,
  8 AO rays, delight 0.18, Y up, safe geometry and both ARMW representations.
  Output packing was checked (RGBA dimensions and exact roughness/metallic G/B
  values), and the supplied diagnostic source SHA-256 was unchanged.
- Windows native failures were addressed with isolated workers, UTF-8 output,
  bounded atomic JSON retries, lower-memory Hunyuan checkpoint assignment and
  direct resource release. A scoped DINO NumPy checkpoint reader avoids the
  Torch Windows mapping failure while retaining the checkpoint tensor values.
  Regression tests cover value preservation and loader restoration after failure.

Evidence (local, ignored generated data):

- `.runtime/workbench_gpu/queue_1792482163445219900/`: first complete MV cycle;
  successful paint job `2735f1a25c3b4ea99b305e2fdab09ebb` follows the recorded shape.
- `.runtime/workbench_gpu/final-repeated-mv/validation.json`: repeated MV cycle.
- `.runtime/workbench_gpu/final-triposg/validation.json`: TripoSG generation;
  additional paint job `5d3b6c4af6b34cc9a314fa70a8315c0f` has the final measured
  view count, atlas behavior and PNG-map validation.
- `.runtime/workbench_surface_validation/validation.json`: real Surface Lab run.
- `scripts/validate_workbench.py`: reusable fresh-output diagnostic CLI. Use
  `--front PHOTO --output NEW_FOLDER --repeat 2 --paint --backend multiview --offline`.

## Requested repository cleanup

The repository storage audit identified environments, weights and generated
outputs as the largest groups. **No source, original input, model weights,
finished asset or distribution contents were deleted.** Transparent NTFS
compression was applied to existing outputs, the inactive portable Python
runtime and static Torch build libraries. Only regenerable bytecode with an
existing source file was removed; sourceless modules and runtime-imported package
source/test modules were retained. Some bytecode naturally regenerated during tests.

Measured net reclaim across the affected trees: approximately **3,336,012,225
bytes (3.34 GB / 3.11 GiB)**, accounting for regenerated caches at measurement.
Detailed before/after data: `.runtime/storage-cleanup-report.json`. Gross bytecode
cleanup: 22,963 files / 458,310,860 bytes. Old handoff/plan text was preserved in
`.runtime/docs-archive/` as gzip archives before consolidating the current guides.

C: fell below 500 MB during the original checks; even a small fixture write
reported `No space left on device`. Space became available and cleanup improved
headroom. Paint can consume substantial temporary disk/commit space while mmgp
is active; the UI now reports free disk and actual worker memory separately.
Post-compaction bundled-runtime relocation/bootstrap checks are recorded in
`.runtime/workbench-relocation.json`.

## Fresh portable release candidate

Final archive: `dist/ModelUnify-1.0-Workbench-RC1.7z`, **1,918,970,407 bytes**.
Archive content checks found **zero user/QA data entries**, and the full 7-Zip
integrity test passed (33,473 files). SHA-256 companion: the same path plus
`.sha256`; digest
`0113d37e78e182f513e0695faf6cb64ae8ab08dc87d8d9fc9dbd74e7a439fcb2`.

`dist/ModelUnify Workbench RC1/` was built with a **fresh embeddable Python and
clean pip dependency installation**, then moved to a different path containing
spaces. Its paint extension is the explicitly reused validated Windows
CPython 3.11 / torch 2.5.1+cu124 binary, packaged with hashes and its upstream
license; it was not recompiled with the installed CUDA 12.6 toolkit.

- Both interfaces construct after relocation. `pip check` passes; the offline
  check imports the actual lazy `hunyuanpaintpbr` model class, native rasterizer,
  native mesh-inpaint module, RealESRGAN and mmgp without loading weights.
- A clean PATH launcher test removed development Python and inherited cache
  overrides. The real `run.bat` opened an Edge application window on **7862**,
  independently of the source server on 7861. Reported HF/Torch/Hunyuan/rembg/
  matplotlib/Numba/temp caches stay under the candidate.
- Full browser import/camera/PBR/UV/project/checkpoint/optimization/LOD workflow
  and all four high-DPI layouts passed with no browser errors. Actual reduction
  was 40,000 → **7,999** for an 8,000 target. The second LOD achieved **2,440**
  for a 2,000 target; that miss is reported, not relabelled as success.
- Four supplied **hangar renders**, Front/Left/Back/Right, completed shared BRIA
  preparation and actual Hunyuan generation: 25 steps, octree 256, **4,986 faces**,
  about 182 seconds including preparation/loading. PBR painting completed in
  about 127 seconds with **4,974 faces**, 512×512 albedo/MR maps, six measured
  coverage views, mmgp and approximately **6.45 GiB** peak worker allocation.
- TripoSG used **front only**, 25 steps and the same BRIA provider. It completed
  in about 51 seconds. It achieved **12,619** faces for a requested 5,000 and had
  inconsistent winding. A repeat using the final source confirms both findings
  appear in the completed-job warning message and saved history. These are
  functional diagnostics, not production-quality approval of these meshes.
- Actual painting exposed a missing **pytorch-lightning** runtime requirement
  hidden by a shallow import check. Requirements now include it and the
  fast-simplification dependency used by remeshing/fallback reduction. The
  strengthened check and the real paint retry passed; the original failure is
  retained in the diagnostic history.
- Copied CLI help and an actual InstaLOD Studio staging copy passed. The original
  residential master retained SHA-256
  `483c54b674b8ee1911a60f84c32f230d4ad35f3c64a2a1990bd6cf25ee748a99`.

Evidence: `.runtime/portable-rc1/`, especially `assembly.json`, `clean-check.log`,
`portable-browser.log`, `portable-dpi.log`, `gpu-summary.json`,
`multiview-gpu/validation.json`, `triposg-gpu/validation.json` and
`triposg-warning-retest.log`. The candidate records source hashes and package
versions. Its cached inference weights were reused explicitly from the existing
machine; they are not bundled in the release archive except the explicit
RealESRGAN checkpoint required by the paint build.

`packaging/archive_candidate.ps1` packages only application/runtime components,
excluding projects, inputs, outputs, queue/profile data, caches and Studio QA
inbox/outbox files. It checks the archive contents, CRC integrity and SHA-256.

## Remaining release work

Current optimization increment: **62 regressions** pass, including 15 new
optimizer cases. Real-asset diagnostics improved the residential target-2,000
run from 2,262 (one pass) to 2,000 (two passes), retaining its UVs and three PBR
maps through GLB reload. However, visual review found facade damage: its sampled
surface deviation is 5.585%, so the final 2% default guard rejects it. The working
7,999-face candidate for target 8,000 measures about 0.290%. TripoSG target-5,000 improved from 9,827 to 9,577 with
consistent winding; it remains non-manifold and over budget. Both master hashes
were preserved. The final surface guard rejects that TripoSG reduction too
(about 6.685% sampled deviation), so it is not published as a safe optimization.
See [OPTIMIZATION_VALIDATION.md](OPTIMIZATION_VALIDATION.md) for
source/portable GUI checks and explicit visual acceptance steps. Original RC1
archive/checksum are unchanged; the unpacked candidate contains post-archive updates.

Final host check during this CPU-only increment: `nvidia-smi` reported
`GPU is lost. Reboot the system to recover this GPU` and found no available
device. Source and portable environments still report PyTorch 2.5.1+cu124 /
CUDA 12.4 with no CUDA_VISIBLE_DEVICES override, but CUDA availability is false.
CPU optimization/GUI checks passed; this increment did not rerun AI inference.
Recover the host GPU before any new shape/paint GPU validation.

1. Assess generation and Surface Lab quality/performance on fixed representative
   real photographs and meshes at production settings, including AI normal bakers.
2. Run the release candidate on a **separate clean Windows/NVIDIA machine**.
   Clean dependencies, relocation and actual inference on the development host
   have passed; that does not establish clean-OS/driver portability. Original
   distributions and user data remain intact.
3. Validate installer compilation/install/uninstall separately and finish
   keyboard/high-DPI usability testing with real users.

Final BML conversion, authoritative BMS metadata/DDS authoring and deployment
remain external workflows; no real BMS installation was modified.
