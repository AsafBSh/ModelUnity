# ModelUnify — Model & Method Roadmap

Tracked upgrade and integration options for ModelUnify. Use this file to prioritize future work and to give AI coding assistants context on what is planned vs shipped.

**Last reviewed:** 2026-10-21

## Next product priorities after adjustable panels

The workbench now has independent persistent side-panel sizing. The six priorities
below now have source implementations: input checks/overlays, unified four-model
benchmark CLI and GUI queue, raw/working/accepted comparison, bounded UV/PBR
diagnostics, copy-only measured scaling/BMS readiness, and prompt-scoped host
progress plus optional runtime setup. See WORKBENCH.md for behavior and limits.
The original acceptance checklist below remains useful for validation; future-tense
items describe that checklist, not missing UI controls. High-resolution quality,
calibrated accuracy and clean-machine installer validation remain separate gates.

1. **Input readiness before inference.** Make mask inspection and foreground
   coverage easier to review; explain when an unchanged photo background may
   become geometry. Add Pixal multiview framing/FOV checks and alignment guides
   for its fixed orbit. Preserve explicit provider selection and originals.
   Verify with opaque backgrounds, already-transparent inputs, thin antennas,
   inconsistent view dimensions and correctly matched four-view fixtures.
2. **One benchmark path for all four generators.** `scripts/benchmark.py` currently
   accepts only TripoSG and Hunyuan multiview. Add the Comfy backends and a fixed
   tank/building/jet reference set, frozen inputs, seeds, preprocessing, working
   budgets and actual host memory/timing. Include the untested higher shape/atlas
   settings listed in `COMFYUI_VALIDATION.md`. Compare silhouettes, symmetry and
   thin parts from identical cameras; do not substitute triangle counts for accuracy.
3. **Raw-master comparison and cleanup guards.** Comfy retains `master.glb`, but
   the GUI's current Source preview is the project's source, not a dedicated
   selector for the decoded master. Add raw / working / accepted selection in the
   same viewer with the same camera and clear mesh statistics. Extend surface /
   bounds checks to Comfy cleanup, warning when remeshing closes openings or
   alters small parts. Verify gun barrels, intakes, antennae and separate components;
   retaining an original must remain byte-identical and failed candidates unpublished.
4. **UV/PBR diagnostics.** The UV inspector currently draws edges and counts
   out-of-range vertices; it explicitly does not calculate overlap or stretch.
   Add overlap/stretch/texel-density visualization and clearer missing-map/seam
   findings. Test intentional mirrored overlap separately from accidental overlap,
   distorted UVs, proper GLB channel packing and missing maps. Keep new normal/AO
   generation explicit and report the algorithm actually used.
5. **Measured scale and BMS readiness.** The existing metres-per-unit and LOD
   distances are planning metadata, and final measurement/BML/DDS remain external.
   Add a known-dimension scaling tool, axis/pivot preview and a readiness report
   for LOD budgets, bounds, UVs/maps and required external BMS conversion. Verify
   metre/centimetre fixtures and exported bounds, preserving supplied masters.
   Never claim the intermediate GLB set is already a deployed BML asset.
6. **Host progress and optional-runtime delivery.** Comfy currently polls history
   with a fixed processing progress value. Surface real node/sampler progress and
   host memory/offload state, then package optional Comfy installation/model selection
   with disk/driver checks. Verify cancelled/failed prompts, offline/missing weights,
   external-host ownership and a clean Windows installation. Keep Comfy's torch
   environment separate and avoid bundling all weights by default.

UI diagnostics and CPU validation are independent of GPU vendor; generation and
native Comfy quality checks target Windows/NVIDIA CUDA. AMD/Intel inference remains
unvalidated. A new portable release is separate from these source changes.

## ComfyUI integration — 2026-10-21

TRELLIS.2 and Pixal3D now have a native-core ComfyUI adapter in the source
workbench and CLI: `scripts/engine_comfyui.py`, `scripts/comfyui_workflows.py`
and `scripts/comfyui_host.py`. See [COMFYUI.md](COMFYUI.md) for installation,
model-specific inputs and validation. Default checkpoints use Comfy-Org INT8
diffusion weights; outputs retain raw masters and optional UV/PBR GLBs.
Pixal multiview requires a matched fixed 90° orbit, not arbitrary photo poses.

Windows/NVIDIA is the integration target. Original upstream research stacks
remain Linux-first; this adapter uses ComfyUI's Windows-capable core instead.
AMD/Intel GPU support remains unvalidated. Historical ratings and VRAM estimates
below do not apply as measured requirements for this new runtime. Existing
portable bundles predate this source integration; representative tank/building/jet
quality evaluation and a new clean portable release remain separate gates.

## Readiness recheck — 2026-10-19

The ratings, size/VRAM estimates and integration durations below are historical
planning estimates, not measured guarantees. No speculative backend was added.
Benchmark the fixed set in [BENCHMARK.md](BENCHMARK.md) before reprioritizing.

- **FlashVDM/Turbo:** upstream still documents multiview Turbo plus
  `--enable_flashvdm`, distinct from guidance-distilled Fast. Retain as the
  first speed experiment; changing only the subfolder is not a validated
  integration. The [primary repository](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)
  and [FlashVDM project](https://github.com/Tencent-Hunyuan/FlashVDM) describe
  distilled models and acceleration. Their timing claims do not establish
  Windows RTX 3500 Ada latency, topology/UV quality, or end-to-end paint speed.
- **Preprocessing:** upstream lists a separate Hunyuan3D-Delight-v2-0 model.
  Evaluate it against the current crop/pad/rembg and enhancement's lightweight
  image filter; learned delight is not currently wired. Measure facade-color
  stability and shadow removal on satellite/ground pairs before adopting it.
- **RMBG 2.0:** the [primary model card](https://huggingface.co/briaai/RMBG-2.0)
  uses gated access and non-commercial terms with separate commercial licensing.
  It is not a transparent replacement for RMBG-1.4/rembg; resolve access,
  licensing and Windows dependency/memory costs before benchmarking.
- Keep text-to-3D and broader UI/model/algorithm/BMS redesign in the separate
  planning discussion. TRELLIS.2 remains Linux-first; any future integration
  needs visible Windows/platform warnings, CUDA requirements and independent
  validation. ModelUnify does not gain AMD or Intel GPU support from this review.

---

## Product context (for prioritization)

| Dimension | Detail |
|-----------|--------|
| **Primary use** | Falcon BMS custom objects/buildings (LOD export → `.bml`) |
| **Secondary uses** | 3D presentation, 3D printing, gaming asset prototyping |
| **Native OS** | Windows (portable installer) |
| **Reference GPU** | NVIDIA RTX 3500 Ada 12 GB (dev machine) |
| **Target GPUs** | NVIDIA CUDA cards from ~6 GB to 32 GB (RTX 3060 → RTX 5080 class) |
| **Non-NVIDIA** | AMD/Intel GPU inference not supported today; CPU fallback only (slow) |

When a row below is **Linux-first** or **CUDA-only**, surface that in UI/docs before shipping.

---

## Shipped in v1.0

| Model / method | Role | Engine | VRAM (typical) | OS | GPU |
|----------------|------|--------|----------------|----|-----|
| TripoSG 1.5B | Single image → mesh | `engine.py` | 6–8 GB | Win | NVIDIA CUDA |
| Hunyuan3D-2mv | 1–4 views → mesh | `engine_hunyuan.py` | 10–12 GB | Win | NVIDIA CUDA |
| Hunyuan3D-2.1 Paint | Mesh → PBR textures | `engine_paint.py` | 12 GB (low_vram + mmgp) | Win | NVIDIA CUDA |
| RMBG-1.4 / rembg | Background removal | `preprocess.py` | 1–2 GB | Win | NVIDIA preferred |
| Marigold / StableNormal | Normal from albedo | `lod_export.py` | 4–6 GB | Win | NVIDIA CUDA |
| Planar texture projection | Quick placeholder UV | `texture.py` | CPU | Win/Linux | Any |
| InstaLOD Pioneer workspace | Optional Studio remesh/LOD hop (manual GUI) | `tools/instalod/` | 0 | Win | Any (CPU in Studio) |

---

## Recommended upgrades & new methods

**Rating scale:** ★★★★★ (95%) = do first · ★☆☆☆☆ (30%) = defer / out of scope

| # | Upgrade / model | Type | Rating | Why | Model size | Est. integration | VRAM | OS | GPU | Status |
|---|-----------------|------|--------|-----|------------|------------------|------|----|-----|--------|
| 1 | **FlashVDM + Hunyuan Turbo** (`hunyuan3d-dit-v2-mv-turbo`, 5 steps) | Upgrade | ★★★★★ 95% | Already in `vendor/Hunyuan3D-2`; upstream speed claims need local quality/runtime comparison; candidate for batch runs | +1.1 GB | 0.5–1 day | 8–10 GB | Win | NVIDIA | **Planned** |
| 2 | **Hunyuan3D-Delight-v2-0** | Upgrade | ★★★★★ 90% | Removes lighting/shadow from input photos before shape + paint; critical for satellite/building shots | ~1.3 GB | 1–2 days | 2–4 GB | Win | NVIDIA | **Planned** |
| 3 | **Text-to-3D** (wire `hy3dgen/text2image.py`) | Upgrade | ★★★★☆ 85% | Vendor code exists, not wired; prompt-only generation when no photos available | 0 (existing cache) | 3–5 days | 10 GB | Win | NVIDIA | **Planned** |
| 4 | **BRIA RMBG 2.0** | Upgrade | ★★★★☆ 82% | Better edges vs RMBG-1.4 on complex silhouettes (trees, antennas on buildings) | ~500 MB | 1 day | 1–2 GB | Win | NVIDIA | **Planned** |
| 5 | **Hunyuan3D-Shape-2.1** | Upgrade | ★★★★☆ 80% | Stronger geometry than 2.0; aligns with 2.1 paint already in use | ~2–3 GB | 3–5 days | 10–12 GB | Win | NVIDIA | **Planned** |
| 6 | **Stable Fast 3D (SF3D)** | New backend | ★★★★☆ 78% | Sub-second draft meshes, ~6–7 GB, UV + delit albedo; ideal "Quick Preview" before full pipeline | ~2.5 GB | 4–7 days | 6–7 GB | Win (exp.) | NVIDIA | **Backlog** |
| 7 | **MeshAnything V2** | Post-process | ★★★★☆ 75% | Dense mesh → clean artist topology (≤1600 faces); useful for BMS LOD5/LOD6 | ~1.5 GB | 5–8 days | 8 GB | Win | NVIDIA | **Backlog** |
| 8 | **TRELLIS.2-4B** | New backend | ★★★★☆ 72% | SOTA open image-to-3D + native PBR; MIT license. **Linux-first upstream; 24 GB official, low-VRAM 512³ may fit 12 GB** | ~8–12 GB | 2–3 weeks | 8–24 GB | **Linux-first** | NVIDIA | **Backlog** — needs platform warning |
| 9 | **Hunyuan3D-mini-Turbo** (0.6B) | New backend | ★★★★☆ 70% | Ultra-light draft mode on 8 GB cards; FlashVDM compatible | ~0.6 GB | 2–3 days | 4–6 GB | Win | NVIDIA | **Backlog** |
| 10 | **Hi3DGen / Stable3DGen** | New backend | ★★★☆☆ 68% | Normal-bridging; best fine architectural detail (roof lines, frames); TRELLIS lineage | ~5–8 GB | 2–3 weeks | 10–16 GB | Win/Linux | NVIDIA | **Backlog** |
| 11 | **InstantMesh** | New backend | ★★★☆☆ 65% | Fast sparse-view LRM; good when 2–3 views available, not full 4-view set | ~3–4 GB | 1–2 weeks | 8–10 GB | Win | NVIDIA | **Backlog** |
| 12 | **Tripo API 3.0** | Cloud API | ★★★☆☆ 62% | Speed + native PBR + text-to-3D without local VRAM; optional cloud tier | 0 local | 3–5 days | N/A | Any | N/A | **Backlog** |
| 13 | **Hunyuan3D 3.5 API** | Cloud API | ★★★☆☆ 60% | Text/image/MV, 8K PBR, &lt;60 s rapid; API-only (not open weights) | 0 local | 3–5 days | N/A | Any | N/A | **Backlog** |
| 14 | **DiffSplat** | New method | ★★★☆☆ 55% | Text/image → Gaussian splats in 1–2 s; preview/visualization only, not BMS mesh export | ~1–2 GB | 2–3 weeks | 6–8 GB | Win/Linux | NVIDIA | **Defer** |
| 15 | **diso flash decoder** (TripoSG) | Upgrade | ★★★☆☆ 52% | Faster marching-cubes decode; commented out in `requirements.txt` (Windows CUDA build pain) | ~50 MB | 3–7 days | — | Win | NVIDIA | **Defer** |
| 16 | **Rodin Gen-2 API** | Cloud API | ★★☆☆☆ 45% | Film-grade hero assets; overkill for BMS building LODs | 0 local | 3–5 days | N/A | Any | N/A | **Defer** |
| 17 | **Seed3D 2.0** | Cloud API | ★★☆☆☆ 40% | Apr 2026 SOTA in blind tests; closed API only — monitor for availability | N/A | TBD | N/A | Any | N/A | **Watch** |
| 18 | **Meshy 4 API** | Cloud API | ★★☆☆☆ 38% | Strong text-to-3D + quad topology; redundant if local text-to-3D + MeshAnything ship | 0 local | 3–5 days | N/A | Any | N/A | **Defer** |
| 19 | **Luma Genie + splat capture** | Ecosystem | ★★☆☆☆ 35% | Phone scanning workflow; not aligned with satellite-photo BMS pipeline | N/A | — | N/A | Any | N/A | **Out of scope** |
| 20 | **HunyuanWorld-1.0** | New method | ★★☆☆☆ 30% | Full 3D world generation; wrong scale for single BMS objects | ~10+ GB | 1–2 months | 16+ GB | Linux | NVIDIA | **Out of scope** |
| 21 | **InstaLOD Pipeline CLI / MCP** | Post-process | ★★☆☆☆ 40% | Automate `tools/instalod` from Cursor/Web UI. Pioneer is Studio-only; CLI needs paid Pipeline. Do not wrap MCP until that SKU exists. | 0 | 2–4 days after license | N/A | Win | Any | **Defer** |

---

## Implementation tiers

### Tier 1 — Do first (high ROI, low risk, fits Windows + 8–12 GB NVIDIA)

1. FlashVDM + Turbo subfolder
2. Hunyuan3D-Delight preprocessing
3. BRIA RMBG 2.0
4. Text-to-3D wiring (vendor code exists)

### Tier 2 — Next (new capability, moderate effort)

5. SF3D quick-preview backend
6. Hunyuan3D-Shape-2.1 alignment
7. MeshAnything V2 LOD topology pass
8. Hunyuan3D-mini-Turbo draft mode

### Tier 3 — Strategic (bigger bets; validate Linux/VRAM first)

9. TRELLIS.2-4B — **requires explicit Linux-first / VRAM user warning**
10. Hi3DGen for architectural detail
11. Optional cloud API tier (Tripo 3.0 / Hunyuan 3.5)

### Tier 4 — Defer or niche

- DiffSplat (preview only)
- diso on Windows (build pain vs gain)
- Closed hero-asset APIs (Rodin, Seed3D)
- InstaLOD Pipeline CLI / MCP (Pioneer Studio sidecar already in `tools/instalod`)

---

## VRAM reference by pipeline (NVIDIA)

| Pipeline | Typical VRAM | Notes |
|----------|--------------|-------|
| TripoSG single | 6–8 GB | Fits 8 GB cards |
| Hunyuan MV shape | 10–12 GB | Turbo/FlashVDM reduces peak |
| Hunyuan Paint (mmgp) | 12 GB+ | `low_vram_mode: true` in config |
| SF3D draft | 6–7 GB | Good for 8 GB laptops |
| TRELLIS.2 @ 512³ | 8–10 GB (low-VRAM) | Untested on RTX 3500 Ada |
| TRELLIS.2 @ 1024³+ | 14–24 GB | Needs sequential model unload |

---

## Platform & GPU compatibility matrix (for user-facing docs)

Use this when adding features or writing installer checks.

| Capability | Windows | Linux | NVIDIA | AMD | Intel GPU | CPU only |
|------------|---------|-------|--------|-----|-----------|----------|
| TripoSG shape | ✅ | ⚠️ untested | ✅ | ❌ | ❌ | 🐌 slow |
| Hunyuan MV shape | ✅ | ⚠️ untested | ✅ | ❌ | ❌ | 🐌 slow |
| Hunyuan 2.1 paint | ✅ | ❌ ext | ✅ CUDA ext | ❌ | ❌ | ❌ |
| Gradio Web UI | ✅ | ⚠️ | — | — | — | ✅ |
| Portable installer | ✅ | ❌ | — | — | — | — |
| TRELLIS.2 (planned) | ⚠️ risky | ✅ upstream | ✅ 8–24 GB | ❌ | ❌ | ❌ |

**Legend:** ✅ supported · ⚠️ partial/untested · ❌ not supported · 🐌 impractically slow

---

## Proposed config registry (v2 architecture)

Future `config.yaml` extension to support multiple GPUs and use cases without hardcoding:

```yaml
model_registry:
  draft:     { engine: sf3d,        min_vram_gb: 6,  os: [windows] }
  single:    { engine: triposg,    min_vram_gb: 8,  os: [windows] }
  single_hq: { engine: trellis2,   min_vram_gb: 12, os: [linux, windows], warn_linux_first: true }
  multiview: { engine: hunyuan_mv, min_vram_gb: 10, turbo: true, os: [windows] }
  paint:     { engine: hunyuan_paint, min_vram_gb: 12, low_vram: true, os: [windows], gpu: nvidia_cuda_only }
  text3d:    { engine: hunyuan_t2i, min_vram_gb: 10, os: [windows] }
```

---

## Changelog

| Date | Change |
|------|--------|
| 2026-08-22 | InstaLOD Pioneer sidecar (`tools/instalod`); Pipeline CLI/MCP deferred |
| 2026-07-16 | Initial roadmap created from market survey + codebase audit |
