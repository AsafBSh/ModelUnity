# Four-generator workbench smoke benchmark — 2026-10-21

All **12/12** quick-profile jobs completed: TripoSG, Hunyuan3D-2mv, TRELLIS.2
and Pixal3D on local Merkava tank, hangar and F-15 references. Seed 42, rembg,
20k working triangle target; Comfy used 512 shape/remesh and shape-only output.
Hunyuan uses supplied directions; the F-15 has one supplied image. Pixal uses
single-image mode because the photographs have no certified fixed-orbit camera
calibration. This supplements the earlier separate Pixal multiview smoke test.

Evidence: `.runtime/benchmarks/20261021-workbench/benchmark.json`, saved projects
and **36** front/side/three-quarter screenshots. Display copies were centered and
uniformly normalized with a common clay material and camera, preserving masters.
Original inputs and the supplied residential master remain unchanged.

## Observed findings

- Successful loading is not sufficient accuracy. The quick TripoSG jet and
  hangar have conspicuous extraction artifacts; higher extraction settings are a
  separate experiment, not assumed to fix them.
- The hangar's rembg preparation removed many supports and retained mainly the
  roof. Inspecting `front_prepared.png` against the original confirms information
  loss **before** generation. Those outputs cannot rank reconstruction accuracy
  on the complete building. Review/replace its mask before repeating quality runs.
- All tank outputs are recognizable, with visibly different turret/thin-part
  reconstruction. Comfy draft cleanup changes geometry: sampled max distance
  relative to the raw-master diagonal was about **11.45%** for TRELLIS tank and
  **2.75%** for Pixal tank. Every Comfy baseline cleanup exceeded the selected
  2% surface threshold. Warning mode published them for inspection; strict mode
  would reject them while retaining raw masters.
- F-15 Comfy drafts have recognizable fuselage/wings/tails; symmetry, intakes,
  pylons and thin edges still require reference inspection. No result is approved
  as a final BMS asset or metrically accurate reconstruction.

These are qualitative visual observations, not invented 1–5 scores. Manual
numeric score fields remain unset. No calibrated mesh or dimensions were supplied.
Queue/execution wall times span roughly 52–366 seconds under concurrent packaging
and cold imports; they are not controlled speed rankings. Sampled Comfy Torch
allocations are neither exact allocator peaks nor GPU minimum requirements.

## Next accuracy experiment

Approve prepared masks first, then run the quality profile on the same owned
inputs. Compare raw and cleaned meshes from matching views, increase working face
targets where justified, and test QEF/remesh settings explicitly against antennas,
barrels, openings and intakes. Supply one measured dimension and, ideally, a
calibrated reference mesh before scoring dimensional accuracy. Higher settings,
PBR atlas quality and clean-machine installation remain distinct validation work.
