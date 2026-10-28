# Optimization reliability: implementation and verification

This is the first optimization improvement, not a complete topology/retopology
system. It uses the installed CPU pymeshlab decimator; no model weights or GPU
inference are needed. Existing NVIDIA inference/platform support is unchanged.

## Behavior

- UV-aware reduction reinitializes the collapse queue for at most three passes,
  keeping quality 0.3, UV error weight 1, normal preservation and planar quadrics.
  It stops when the target is met or a pass makes no progress. Zero-threshold
  decimation is excluded: a diagnostic stalled and was terminated.
- Workbench Optimize repairs inconsistent winding on a copy before and after
  reduction when enabled. This does not close holes, make a non-manifold mesh
  manifold, or prove outward orientation on open surfaces.
- **Require triangle budget** rejects an over-budget result. With it off,
  best-effort output retains an explicit target-miss warning.
- UV loss/nearest-neighbor fallback is rejected unless the user explicitly
  allows a degraded preview. Such previews remain labelled as fallbacks.
- Decoded PBR map pixels and material factors are checked before publication
  and after GLB serialization when fallback is not requested.
- **Maximum bounds change** limits AABB-corner displacement as a percentage
  of the source diagonal. It is not a silhouette-error, thin-part, UV stretch,
  or texture-quality measurement. Separate island-removal cleanup is not run.
- **Maximum sampled surface error** defaults to 2% of the source diagonal.
  Deterministic area-stratified triangle-centre and vertex samples are checked
  against the opposite mesh in both directions before/after GLB serialization.
  Distances are exact at those samples (rtree accelerated, or a chunked naive
  fallback); this is not full Hausdorff distance or proof of all thin features.
  An excessive result is rejected even if its count and outer bounds pass.
- Geometry-only reduction retains topology constraints. Vertex-colour transfer
  is not implemented; unsupported colour transfer is rejected explicitly.
- Reports record requested/achieved counts, pass counts, reoriented faces,
  indexed boundary/non-manifold edges, bounds change, UV method/fallback,
  sampled maximum/RMS surface deviation, warnings, algorithm ID
  (`bounded-quadric-v2`) and installed library versions. Originals remain intact.

## Automated checks

```powershell
.venv/Scripts/python.exe -m unittest tests.test_launcher tests.test_workbench tests.test_readiness tests.test_optimization
```

Focused cases cover malformed parameters; empty/nonfinite geometry; broken UVs;
seam-split panels using separate texture islands; exact albedo/MR/normal pixels
and material factors through GLB reload; winding repair before/after reduction;
a small disconnected closed detail; bounds rejection; explicit UV fallback;
surface deformation despite unchanged bounds; deterministic surface distances
with/without rtree; and strict-budget failure preserving the accepted asset
with no published preview.

The real browser/isolated-worker regression is:

```powershell
node tests/workbench_optimization_browser.cjs
```

It imports the inspected 40,000-triangle residential master through the real UI,
requests 2,000 with one pass and strict budget (must fail), changes to three
passes (count meets 2,000 but excessive surface deviation must reject it),
requests 8,000 (7,999 passes), accepts that result, and requests an impossible
one-triangle budget with protected boundaries (must retain the accepted mesh).
Set `MODELUNIFY_TEST_URL` for the portable server. Playwright must be available
on `NODE_PATH`; no inference runs. This fixed-asset browser test intentionally
expects the residential master rather than treating arbitrary assets as equivalent.

## Repeatable real-asset comparison

```powershell
.venv/Scripts/python.exe scripts/validate_optimization.py bms_export/residential_5/Model_0.glb --target 8000 --strict --output .runtime/optimization-reliability/residential_NEW
```

Every invocation requires a new output directory. It compares one pass without
repair against bounded passes with repair, saves actual operation reports and
GLBs, records elapsed time and source SHA-256, and verifies source preservation.
The one-pass baseline's warning is expected; `--strict` applies to the bounded
candidate. Exit 1 denotes a failed run, including a strict target miss.
Using target 2,000 with the default 2% surface limit intentionally fails on
this master. `--max-surface-error` permits an explicitly relaxed draft limit;
that choice is recorded and a deviation over the default limit is warned.

The inspected residential master has 40,000 faces, 25,973 vertices, valid UVs,
three PBR maps and consistent winding. It is an open static single mesh/material
with 562 indexed components. It reached 2,262 with one pass and 2,000 with two
passes under unchanged native constraints. The inspected TripoSG diagnostic
has 12,619 faces, valid UV/albedo, 553 indexed components and 1,223 non-manifold
edges. For target 5,000 it reached 9,827 in one pass and 9,577 in three, with
winding repaired; this remains an honest budget miss, not production approval.
The final surface guard also rejects that TripoSG reduction at about 6.685%
maximum sampled deviation. Repairing winding alone is insufficient to make
this non-manifold input safely reducible at the requested budget.

Visual review of the initial 2,000-face numeric-only result showed a damaged
facade. Measured maximum sampled surface deviation was **5.585%**, so the final
default guard rejects it. A 7,999-face result for target 8,000 measured about
**0.290%** and is the working validation candidate. Matching triangle counts,
outer bounds and texture pixels alone were insufficient; the rejected initial
diagnostic is retained as a counterexample rather than approved as quality.

Final evidence is under `.runtime/optimization-reliability/validated-residential-surface-001/`,
`rejected-residential-surface-001/` and `validated-triposg-surface-001/`.
Initial comparisons remain in `validated-residential-001/` and
`validated-triposg-001/`. Original SHA-256 hashes remain unchanged.

## Visual acceptance tests still required

1. Use identical camera, environment lighting and PBR channel for source and
   result in the single viewport. Orbit the front, sides, rear and roof.
2. Inspect roof lines, window frames, antennas and openings in solid and wireframe.
   Reject missing parts, new holes or unacceptable silhouette changes even if
   the triangle budget and bounds checks pass.
3. Inspect albedo/MR/normal channels and UV checker. Look for shifted facade
   details, island bleeding and seams; matching map pixels alone cannot prove
   that changed UV coordinates sample them correctly.
4. Repeat with a closed object, an open/thin structure and a difficult generated
   mesh. The synthetic small-detail regression does not guarantee arbitrary
   thin-part preservation.
5. Enable protected boundaries and verify the extra preservation/target tradeoff
   is reported. Try an impossible strict budget and verify no new checkpoint
   appears; the accepted model must remain visible.
6. Review actual LOD transitions at intended distances separately; the new
   Workbench Optimize surface guard is not a distance-aware LOD certification.
   UV repacking, high-to-low baking, complete silhouette-error testing and non-manifold reconstruction
   remain later work; BML/DDS deployment is outside this test.
