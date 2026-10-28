# Repeatable quality and speed comparisons

Use a fixed, permission-cleared input set: one isolated object, one simple
building with front/side views, and one difficult building with occlusion or
thin details. Freeze input files, view labels, preprocessing, seed, settings
and output face budgets. The harness records SHA-256 hashes, configuration,
Python/package versions, OS, GPU, CUDA runtime, stage times, peak torch
allocated/reserved memory, memory after cleanup, and actual geometry state.

```powershell
.\.venv\Scripts\python.exe scripts\benchmark.py --backend multiview `
  --front inputs\benchmark\building_front.png `
  --left inputs\benchmark\building_left.png --seed 42 --repeat 3 `
  --steps 50 --octree 380 --paint --normal low --offline `
  --render-size 1024 --texture-size 2048 --views 6 `
  --output outputs\benchmarks\baseline_001
```

Every invocation requires a **new** output directory. `--offline` requires
cached models and prohibits Hugging Face network downloads. Remove it only
when downloading the selected weights is intended. `benchmark.json` is saved
after each iteration, including failure traces. Iteration zero includes cold
process/model-load costs; each iteration deliberately unloads and reloads
models to test handoffs. The OS file cache becomes warmer on later runs.
`--backend triposg --front ... --octree-depth 9` tests the single-image path.

Inspect all outputs with identical camera positions and lighting. Fill in
the reserved 1–5 quality scores and notes for silhouette, facade alignment,
texture seams and LOD popping; these are **manual**, not automatic quality
measurements. Generate LODs with the same ladder and inspect `lod_report.json`
for achieved counts and UV fallbacks. Keep screenshots with the benchmark
folder when collecting a quality baseline. Review PBR channels independently.

Torch peaks do not include every native CUDA allocation or other processes;
record driver and optional `nvidia-smi` readings as supplemental evidence.
RSS is sampled after each run, not peak system RAM. Tiny two-step, octree-128,
512-texture smoke runs validate lifecycle/error handling only; they cannot
establish production quality, claimed upstream speedups, or default-preset
VRAM requirements. Re-run the fixed set before accepting future backends.

The current upstream paint view selector can select six views even when its
requested maximum is four. Keep the stage log with the JSON settings; do not
interpret a requested maximum as proof of actual view count. The existing
pipeline also controls texture resizing internally; inspect output map sizes.
# Unified four-generator benchmark (2026-10-21)

Use `scripts/benchmark_suite.py` for the current workbench pipeline. The older
`scripts/benchmark.py` below remains a two-backend legacy utility.

```powershell
.venv/Scripts/python.exe -m scripts.benchmark_suite --plan --offline
.venv/Scripts/python.exe -m scripts.benchmark_suite --offline --output .runtime/benchmarks/my-fresh-run
```

`benchmarks/objects.json` identifies existing Merkava tank, hangar and F-15
references. Single-image models use Front; Hunyuan uses supplied directions.
Reference photographs are local user inputs and are not shipped in portable
packages; supply your own suite paths or use the GUI comparison with uploads.
Pixal uses single-image mode in this baseline because those photos have no
certified fixed-orbit calibration. Quick defaults use 512 Comfy / lower native
extraction and 20k working triangles, seed 42 and rembg. `--profile quality`,
`--models`, `--cases`, `--faces`, `--seed`, `--repeat` and `--bg` are explicit.
Quality profile is a separate longer/higher-memory experiment, not automatically
validated by quick runs. All weights can be kept offline with `--offline`.

Runs enter the real serialized workbench queue, respect existing job order and
create independent saved projects. `benchmark.json` records original-image
hashes, frozen settings, input checks, failures, elapsed queue/execution time and
operation reports/artifacts. Comfy reports include sampled host memory and live
node/step evidence; local worker allocations alone do not measure Comfy usage.
Raw masters are retained by new jobs. Timeout/Ctrl+C cancels only that run.

Review each mesh from matching cameras against references for silhouette,
symmetry, thin parts and dimensions. Manual score slots remain unset until
reviewed. Triangle counts, bounds or successful GLB loading do not prove accuracy;
physical accuracy needs measured dimensions or a calibrated reference mesh.
The GUI's Generate comparison accordion queues the same settings against the
currently uploaded references without changing the active asset.

