# Model weight removal on 28 October 2026

The maintainer authorized removing downloaded models and publishing source-only
code. Removed 116 model/cache files, totaling 49.59 GiB logical. C: free space
increased from 16.33 to 63.98 GiB during the measured pass, recovering about
47.65 GiB of physical space. Other machine activity can change free space later.

Removed TripoSG, RMBG-1.4, Hunyuan3D-2mv (both checkpoint formats), Hunyuan Paint,
DINOv2 giant, Marigold, U2Net, RealESRGAN and all seven Comfy generator/support
checkpoints. Relevant shared user-cache folders were included. Unrelated models
were retained. Model restoration is documented in [MODEL_WEIGHTS.md](MODEL_WEIGHTS.md).

Retained application/vendor source, Python environments, compiled native paint
modules, wheel backups, licenses, inputs, outputs, projects and BMS exports. The
historical RC2 portable archive, source-history deltas and unique overlays remain;
the deltas still depend on that archive. It has not been relabeled or rebuilt.

Validation after removal:

- Full offline CPU regression suite: 122 tests passed.
- Launcher check passed; weight-free GUI constructed 376 components/70 events.
- Headless Chrome high-DPI checks passed at 1280x720, 1366x768, 1536x864 and
  1600x900: one 3D viewport, no outer page scroll, visible 16 px scrollbar,
  keyboard model selection/focus and no browser errors.
- These checks do not validate AI inference after checkpoint removal. Learned
  workflows must restore their models; existing mesh workflows remain available.
- All 1,092 protected input/project/output/BMS-export files retained their SHA256
  hashes. No protected file changed or disappeared.

Local ignored evidence and removal manifests are under `.runtime/release-20261028`.
Protected-asset SHA256 verification and final Git publication checks are recorded
there separately. Native build output and model data are excluded from Git.
