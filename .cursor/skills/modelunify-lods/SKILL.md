---
name: modelunify-lods
description: >-
  Build Falcon BMS / ModelUnify LOD chains of N levels (Model_0..Model_{N-1})
  using config.yaml bms_lods face targets, pymeshlab decimate, optional InstaLOD
  Studio Pioneer hop, and Gradio/CLI. Reports mesh status before decimating,
  refuses to write duplicate LODs, converts .max/.fbx sources, and falls back to
  a flat average-albedo material when UVs don't survive. Use when the user asks
  for LODs, LOD count N, remesh for BMS, Model_0–Model_6, decimation, impostor,
  or instalod-stage.
---

# ModelUnify LODs (count = N)

Product is **ModelUnify**. Repo folder may still be `3D AI Generator`.

When the user asks for **N** LODs, produce **N** files `Model_0` … `Model_{N-1}`.
Do not invent a 7th LOD unless they want the full BMS set.

## Step 1 — Report model status BEFORE any LOD work

**Mandatory.** Load the source and report these facts to the user *before*
decimating or writing anything:

| Field | Why it matters |
|---|---|
| Source path + format | Only OBJ/GLB/PLY/STL load natively — see **Converting source formats** below |
| **Triangle count** | Decides whether the ladder is achievable at all |
| Vertex count | — |
| UVs present? | No UVs → `make_textured_lod_set` fails; only planar `make_lod_set` works |
| Textures found | Embedded in GLB, sibling PNGs, or none |
| Connected components | Many loose parts decimate badly |
| Watertight / winding | Non-manifold can crash the BMS Editor |
| Bounds | Sanity-check scale and origin |
| Hierarchy / animation | FBX `F4 DOF*` nodes, skinning, per-part transforms are **flattened** by a static mesh export — say so explicitly |

Then print the **requested ladder vs reality**:

```
faces = 628
Model_0  40000  -> NO-OP (target >= 628)
Model_1   8000  -> NO-OP (target >= 628)
Model_2   3000  -> NO-OP (target >= 628)
```

### Stop conditions

Model_0 may retain the master geometry when its target is above the real count.
It is reserialized, not a byte-identical source copy. Every **lower** requested
or achieved level must reduce faces relative to the preceding level. Export
preflight rejects impossible ladders; staged output is published only after
actual reduction checks. Use fewer levels or explicit scaled face budgets.
Existing asset folders are refused; choose a fresh name/root.

Never present identical files as an LOD chain. Report a no-op as a no-op.

## Converting source formats

`trimesh` reads OBJ, GLB/glTF, PLY and STL. Anything else needs a hop first,
and the conversion itself can lose UVs or flatten a hierarchy — report that as
part of the status, not afterwards.

| Format | Route |
|---|---|
| `.obj` `.glb` `.gltf` `.ply` `.stl` | Native `trimesh.load` |
| **`.max`** | `python scripts/max_to_glb.py <file.max>` — headless Blender + the `io_scene_max` extension. Run `--inspect` first: it reports compression, referenced textures and which are missing, without launching Blender. |
| `.fbx` | Not supported by trimesh. `scripts/_fbx_to_textured_glb.py` uses `fbxloader` and asset-specific material logic; not a general ingest CLI. Convert a copy with Blender/Max and inspect losses first. |
| `.3ds` `.dae` | Convert via Blender headless, same pattern as `max_to_glb.py` |

`.max` specifics worth knowing:

- Needs Blender installed (`winget install BlenderFoundation.Blender`) plus the
  **Autodesk MAX** extension. Blender is required for `.bml` anyway.
- `io_scene_max` is **GPL-2.0**. Call Blender as a subprocess; never vendor the
  parser into `scripts/`, which would force ModelUnify to become GPL.
- Cannot read the compressed container from **3ds Max 2024+**. `--inspect`
  detects this.
- Modifier stacks, NURBS/patch surfaces and V-Ray/Corona proxies are **not**
  evaluated by any third-party reader. A scene whose geometry only exists after
  Max evaluates a modifier imports empty or without UVs — an `Unwrap UVW` in
  the stack is a red flag for UVs specifically. When that happens, the honest
  answer is "export FBX from 3ds Max", not a silent degraded result.

## Untextured LODs when UVs don't survive

`_decimate_keep_uv` is texture-aware and normally holds UVs down to very low
counts (verified intact at 24 faces). When it can't, `make_textured_lod_set`
no longer leaves the master's material attached to a mesh that has no UVs to
sample it with — that produced garbage texels or black.

Instead the LOD gets a flat, texture-less `PBRMaterial`, coloured by
`average_albedo_rgba()`: the mean opaque colour of the master albedo, with
transparent texels excluded so cut-out atlases don't average toward their empty
background. A distant LOD tinted with the model's own average reads as the same
object getting smaller, whereas neutral grey pops at the swap distance. With no
albedo available it falls back to mid-grey `(128, 128, 128)`.

Affected levels are named in stdout and must be named in the summary to the
user. Implementation notes:

- Set **either** a `baseColorFactor` material **or** vertex colours, never
  both — attaching a material to a `ColorVisuals` makes trimesh's glTF exporter
  treat the mesh as textured and drop both, so the colour vanishes on
  round-trip. This module uses the material, because Blender and the BMS
  exporter want a material slot.
- BMS still needs a material entry for these levels; they simply have no map.

## Resolve N

1. If they say a number (`3 LODs`, `N=4`, `only LOD0–LOD3`) → that is N.
2. Else default **N = 7** (BMS `Model_0`…`Model_6`).
3. Clamp to **1–7**. The Gradio UI already does `max(1, min(7, num_lods))` in `_build_lod_targets` (`scripts/web_ui.py`). BMS theaters almost always want **7**.

## Face targets (from `config.yaml` `bms_lods`)

Take the **prefix of length N** (same order as the UI):

| File | Default faces | Role |
|------|----------------|------|
| Model_0 | 40000 | Master. Matches Hunyuan 2.1 paint remesh (~40k). If target ≥ current faces, `engine.decimate` is a no-op. |
| Model_1 | 8000 | Mid |
| Model_2 | 3000 | |
| Model_3 | 1000 | |
| Model_4 | 400 | |
| Model_5 | 150 | Far |
| Model_6 | 60 | Impostor / silhouette |

Honor **explicit face counts** from the user over these defaults. If they change the ladder for the whole project, edit `config.yaml` `bms_lods` (and `tools/instalod/profiles/RECIPES.md` if they use Studio).

Suggested BMS swap distances (ft) for Parent.dat / Blender LOD panel — see `docs/BMS_WORKFLOW.md`: 500, 1500, 4000, 10000, 25000, 60000, 150000 for LOD0–6.

## How to generate

Prefer **existing code**, not a new decimator.

| Input | Command / path |
|-------|----------------|
| Single photo | `python scripts/generate_3d.py bms-lods <image> --name <asset>` (`--lod-count N` or `--lod-faces 628,300,120`) |
| 1–4 views | `python scripts/generate_3d.py multiview-bms-lods --name <asset> --front …` |
| Web UI | BMS checkbox + **number of LODs** + per-LOD face sliders |
| From an existing mesh | `scripts/lod_export.py`: `make_lod_set` (planar) or `make_textured_lod_set` (PBR GLB) |
| Decimate primitive | `scripts/engine.py` `decimate(mesh, target_faces)` — pymeshlab quadric collapse, topology preserved |

Use `--lod-count N` for a config prefix or `--lod-faces` for explicit budgets.
Do not generate extra levels and silently delete them afterwards.

## Where to save when the user did not say

State the chosen path in the status report so they can redirect before work
starts. Do not invent a location silently.

| Situation | Destination |
|---|---|
| User gave a path | Use it verbatim |
| Default | `paths.bms_export_dir` / `<asset>/` from `config.yaml` (default `bms_export/<asset>/`) |
| Asset name not given | Derive from the source filename, lowercased, spaces and punctuation → `_` (`win.fbx` → `win`). Confirm it if ambiguous. |
| Source is an archive | Extract to `inputs/<category>/<archive-stem>/`, then write LODs to `bms_export/<asset>/` |
| Target folder already has `Model_*` | **Do not overwrite.** Ask, or write to `bms_export/<asset>_v2/` |
| Scratch / non-BMS export | `paths.outputs_dir` (default `outputs/`) |

Never write results into `inputs/` — that tree is source material only.

## Quality hop (optional)

pymeshlab is the default. For cleaner lower LODs after a master exists:

1. `python tools/instalod/stage.py --name <asset>` (or `python scripts/generate_3d.py instalod-stage --name <asset>`).
2. User runs **InstaLOD Studio** (Pioneer GUI only — no CLI/MCP). Recipes: `tools/instalod/profiles/RECIPES.md`.
3. Copy `outbox/<asset>/Model_1.glb`… over `bms_export/<asset>/`. **Keep** ModelUnify `Model_0.glb`.
4. Pioneer needs attribution if they share/ship meshes.

InstaLOD does **not** write `.bml`.

## Do not

- Run the ladder before reporting mesh status.
- Write LOD files that are identical to the master and call them LODs.
- Flatten an animated / DOF hierarchy without warning that it was flattened.
- Leave a textured material on an LOD that lost its UVs.
- Vendor GPL parsers (`io_scene_max`) into `scripts/`.
- Hardcode 12 GB VRAM or assume AMD/Intel GPU paint.
- Skip Blender + [BMS Blender plugin](https://github.com/BenchmarkSims/bms-blender-plugin) for `.bml`.
- Treat `falcon-build` / avionics skills as this pipeline (those are FreeFalcon C++, not ModelUnify meshes).
- Wrap `InstaLODCmd` unless Pipeline is licensed.

## Related

- After LODs, `.bml` is a **manual** step outside this repo: Blender + the [BMS Blender plugin](https://github.com/BenchmarkSims/bms-blender-plugin), then `deploy_bms.py`. See `docs/BMS_WORKFLOW.md`. Hand the user the GLBs and the `bms_template/` scaffold; do not claim to produce `.bml`.
- Mesh / UV / texture cleanup on the master **before** the ladder (InstaLOD Studio): skill **modelunify-bms-enhance**. If that changes topology or UVs, rebuild every LOD.
- `AGENTS.md`, `docs/BMS_WORKFLOW.md`, `docs/MODEL_ROADMAP.md`.
