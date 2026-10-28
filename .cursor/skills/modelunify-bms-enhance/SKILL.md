---
name: modelunify-bms-enhance
description: >-
  Post-process an already-generated ModelUnify main mesh and textures for
  general quality and Falcon BMS PBR: repair/optimize geometry, preserve or
  rebuild UVs, enhance and bake texture maps, and pack AO/roughness/metallic/
  wetness into ARMW. Gathers missing criteria before processing and can stage
  an optional manual InstaLOD Studio pass. Not for generating models or BML.
---

# Enhance an existing main model for BMS

**Scope: post-process only.** Input is a finished mesh — normally
`bms_export/<asset>/Model_0.glb` from ModelUnify. This skill does **not**
generate models. Photo prep, shape generation (TripoSG / Hunyuan multiview) and
PBR paint (Hunyuan 2.1) belong to `scripts/generate_3d.py` and the Gradio UI,
not here. If the user needs a *new* model, send them there first.

## Required intake

Inspect the asset first. Infer answers from the mesh, textures, request and
`config.yaml`; do not ask for information already available. If a choice
materially changes output and was not supplied, ask the user:

1. **Input master** — exact `Model_0` path.
2. **Target** — BMS only, general 3D only, or both.
3. **Mesh work** — repair only, optimize to a face target, or reconstruct/remesh.
4. **UV work** — preserve, repack, or create a new unwrap.
5. **Texture resolution** — 1024, 2048 (default), or 4096.
6. **Texture enhancement** — delight strength; normal quality; bake AO;
   preserve or regenerate roughness/metallic; generate wetness.
7. **ARMW output** — ask this every time unless the user already chose:
   - **Separate maps only** — `ao.png`, `roughness.png`, `metallic.png`,
     `wetness.png`. No packed `armw.png`.
   - **Packed only** — one `armw.png` (R=AO, G=Roughness, B=Metallic,
     A=Wetness). No separate source maps.
   - **Packed + separate sources** — both the packed ARMW and the four
     editable source maps.

   BMS in-game still needs a packed four-channel ARMW DDS. Separate-only is
   for editing or 3ds Max / general PBR; pack later before BMS export.
8. **Interchange output** — local enhancement writes GLB. OBJ requires an external conversion step.
9. **InstaLOD** — local automated enhancement only, or an optional manual
   InstaLOD Studio pass for higher-quality reconstruction/baking.

If the user supplies only a model path, recommend: both targets; repair;
preserve valid UVs; 2048 textures; light delight; AO on; low normal baker;
preserve MR; automatic wetness; packed + separate ARMW; GLB; no manual
InstaLOD pass.

## Local automated processor

After intake, execute `scripts/enhance_model.py` for the local path. Example:

```powershell
python scripts/enhance_model.py bms_export/car_10/Model_0.obj `
  --resolution 2048 --normal high --delight-strength 0.18 `
  --up-axis y --material-name modelunify_car_10 `
  --armw separate
```

`--armw` is `separate` | `packed` | `both`. Pass the user's choice. Do not
write `armw.png` when they asked for separate maps only.

## Output contract

Write to `<asset>/enhanced/` without overwriting the supplied master:

- `Model_0.glb` — enhanced main model with embedded standard PBR textures.
- OBJ/MTL enhancement output is not implemented; use external conversion if needed.
- `albedo.png`, `normal.png`, `metallic_roughness.png`.
- Texture extras according to `--armw`:
  - `separate` → `ao.png`, `roughness.png`, `metallic.png`, `wetness.png`
  - `packed` → `armw.png` only
  - `both` → packed ARMW plus the four source maps
- DDS export/texconv integration is not implemented. Convert externally for BMS: Albedo BC7 sRGB, ARMW BC7 Linear, Normal BC5 Linear.
- `enhance_report.txt` — requested options, operations actually performed,
  before/after mesh statistics, outputs, warnings and skipped steps.

Do not report an unavailable or skipped operation as enhancement.

## OBJ MTL versus BMS Materials.mtl

These are different files:

- `Model_0.mtl` is a Wavefront material sidecar. **3ds Max needs it only when
  importing OBJ** and automatically reconnecting the referenced textures. GLB,
  FBX and native Max scenes do not require this file.
- BMS `Materials.mtl` is mandatory JSON generated/configured through the BMS
  Blender/3ds Max exporter. It points BMS materials at DDS textures. A
  Wavefront `.mtl` cannot replace it.

Do not claim this skill can create a final authoritative BMS `Materials.mtl`
without the BMS exporter.

## Optional InstaLOD Studio pass

InstaLOD Studio is a **desktop GUI**. Pioneer has no CLI, REST, or MCP, so this
part cannot be automated: stage files, provide exact settings, and the user
clicks Start.

```
bms_export/<asset>/Model_0.glb
  → python tools/instalod/stage.py --name <asset>
  → tools/instalod/inbox/<asset>/Model_0.glb
  → InstaLOD Studio  (recipes below)
  → tools/instalod/outbox/<asset>/
  → copy back over bms_export/<asset>/
```

## Pick the operation from the symptom

| Symptom on the ModelUnify mesh | InstaLOD operation | Notes |
|---|---|---|
| Blobby / marching-cubes topology, self-intersections | **Remesh** (Reconstruct) | Rebuilds from scratch, repairs geometry, auto-UVs, bakes old appearance onto new mesh |
| Stretched or overlapping UVs, texture smearing | **UV Unwrap** | Overlap-free parameterization; or let Remesh do it |
| UVs fine but wasteful layout | **UV Pack** | Repacks existing shells onto one atlas, no reshaping |
| Several materials / texture sets on one building | **Material Merge** | Combines into a single atlas and recalculates UVs — BMS wants few textures |
| Baked-in sun and shadows from satellite photos | **Delight** (Texture Output panel) | Shadow Kernel, Strength, Highlight Removal, Shadow Removal, Falloff |
| Flat-looking LODs, no surface relief | **Texture Bake** profile | Bake 40k master → low LOD: NormalTangentSpace, AmbientOcclusion, Curvature |
| Interior walls/floors the player never sees | **Occlusion Cull** | Auto interior-face detection, or place cameras |
| Loose verts, flipped normals, small holes | **Mesh Toolkit (MTK)** | Weld, conform normals, convex hull, and more |
| Uneven triangle density | **Isotropic Remesh** | Uniform edge length, can preserve attributes |
| Lowest LOD collapses to a blob | **Imposterize** | Billboard stand-in instead of a reduce |
| Just need fewer triangles, keep everything else | **Optimize** | Preserves UVs, textures, normals, vertex colors → that is the `modelunify-lods` ladder |

Full recipes with Studio settings: `tools/instalod/profiles/RECIPES.md`.

## Bakeable texture pages

Texture Output panel, up to 32k, with Super Sampling, Dilation and Solidify:

NormalTangentSpace, NormalObjectSpace, AmbientOcclusion, Curvature, Thickness,
BentNormals, Displacement, Position, VertexColor, MeshID, Opacity, Transfer.

For BMS, the ones worth baking are **NormalTangentSpace** (recovers detail lost
during decimation), **AmbientOcclusion** (free contact shadows) and
**Curvature** (drives edge wear if the user retextures).

## Delighting — read this before satellite-sourced buildings

Local enhancement has a lightweight image-based delight filter; learned Delight-v2 is roadmap only in
`docs/MODEL_ROADMAP.md`. InstaLOD Studio's baker **does** delight, so this is
an optional way to remove baked-in lighting during a manual texture bake. It
runs on texture pages during a bake or remesh, not as a standalone filter.

## What InstaLOD will not do

- **Not a painter.** It bakes, transfers, atlases and delights existing texture
  content. It never invents new detail. Generative texturing stays with
  Hunyuan 2.1 paint.
- **No `.bml`.** Blender + the [BMS Blender plugin](https://github.com/BenchmarkSims/bms-blender-plugin), see `docs/BMS_WORKFLOW.md`.
- **No automation under Pioneer.** Do not wrap `InstaLODCmd` or write an MCP
  server unless the user licenses InstaLOD Pipeline.

## License

Pioneer is free for individuals or businesses under **$100,000** annual revenue
or total funding, commercial use included. Attribution is required whenever
processed content is shared or published — for a BMS mod, a readme link back to
InstaLOD. Freelance work only qualifies if the *client* would also be eligible.

## Handoff

After Studio: copy `outbox/<asset>/` results over `bms_export/<asset>/`, then
run the LOD ladder with skill **modelunify-lods**, then Blender for `.bml`.
If Remesh changed the topology, regenerate every LOD — the old ones no longer
match.
