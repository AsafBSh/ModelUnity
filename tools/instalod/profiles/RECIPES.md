# InstaLOD Studio recipes (Pioneer)

Do **not** hand-author JSON until you have saved a working profile from
Studio (**File → Save Profile**). InstaLOD profiles are JSON and load via
**File → Open Profile…** or drag-and-drop
([docs](https://docs.instalod.io/Products/InstaLOD_Studio/InstaLOD_Profiles)).

Face counts below match `bms_lods` in `config.yaml`. If you change those
targets, update this file and re-save the profile.

Input is always the **master** mesh: `inbox/<asset>/Model_0.glb` (typically
~40k faces after Hunyuan 2.1 paint).

---

## Recipe A — BMS LOD Optimize (parallel)

**File → New Profile** → start with **Optimize**.

**Profile Settings**

- Leave operations **parallel** (default). Do **not** enable Previous Output
  As Input — each LOD is an independent reduce of the same master.
- **Automatic Quality: Off** so Absolute Triangles is honored.

Add one Optimize entry per LOD (rename so exports are obvious). For each
entry, set:

| Mesh operation name | Operation | Absolute Triangles |
|---------------------|-----------|--------------------|
| Model_1 | Optimize | 8000 |
| Model_2 | Optimize | 3000 |
| Model_3 | Optimize | 1000 |
| Model_4 | Optimize | 400 |
| Model_5 | Optimize | 150 |
| Model_6 | Optimize | 60 |

**Model_0:** do not Optimize — keep the staged master.

If LOD6 turns into a collapsed blob, replace the Model_6 Optimize step with
**Imposterize** and export that as `Model_6.glb`.

**File → Save Profile** → `tools/instalod/profiles/BMS_LOD_Optimize.json`

Export each result as GLB into `outbox/<asset>/` using those names.

---

## Recipe B — Remesh then Optimize (bad AI topology)

When marching-cubes / painter remesh is too messy for Optimize alone:

1. **File → New Profile** → **Remesh** (Reconstruct mode): new topology, auto
   UVs, bake appearance (normals / albedo as Studio offers).
2. Enable **Previous Output As Input**.
3. After Remesh, add Optimize entries for Model_1 … Model_5 with the same
   Absolute Triangles as Recipe A.
4. Model_6: Optimize at 60 tris or Imposterize.

Save as `tools/instalod/profiles/BMS_Remesh_Then_LOD.json`.

Use this for **presentation / game** GLBs as well; you can stop after Remesh
and export a single asset instead of the BMS ladder.

---

## Recipe C — Remesh settings for AI topology

Settings for the Remesh step in Recipe B, or for a standalone cleanup of a
blobby marching-cubes mesh. `Mesh Operation Settings` → `Surface Construction`:

| Setting | Value for ModelUnify meshes | Why |
|---|---|---|
| Resolution | `Normal` (`High` only if you get up close) | Low models *over* detail and bakes it into the normal map; anything above `High` is very slow |
| Ignore Backfaces | **On** | Painter output is rarely watertight |
| Automatic Occlusion Geometry | On for small holes | Closes gaps so no interior polygons get built; costs a lot of time |
| Welding Distance | Small non-zero | Welds pinholes for surface construction only, not for baking |
| Hardsurface Angle Threshold | Raise for buildings | Keeps wall/roof creases sharp |
| Clipping Planes | One at ground level | Cuts the junk skirt under photo-derived meshes |

Remesh generates UVs and bakes the old appearance automatically — do **not**
add a separate UV Unwrap after it.

---

## Recipe D — Rebuild UVs / collapse to one atlas

Choose one:

- **UV Unwrap** — new overlap-free parameterization. Use when UVs are stretched
  or overlapping and you do not want to change the geometry.
- **UV Pack** — keeps shell shapes, repacks them onto a single atlas. Use when
  UVs are correct but wasteful.
- **Material Merge** — several materials become one texture atlas, UV layout
  recalculated across all objects. Use before BMS export; fewer textures means
  fewer draw calls and a simpler `Materials.mtl`.

---

## Recipe E — Bake master detail onto a LOD

**File → New Profile… → Texture Bake.**

1. Import both meshes. The high-poly is the source, the LOD is the target.
2. `Bake Settings`: set `Target Suffix` and `Source Mesh RegEx Format` so the
   pair matches; confirm the mapping in the `Bake Outliner` before running.
3. `Texture Output` → enable the pages you want. For BMS:
   `NormalTangentSpace`, `AmbientOcclusion`, `Curvature`.
4. Turn on `Solidify Texture Pages` and set `Dilation In Pixels` to avoid
   mipmap bleed. `Super Sampling` improves quality at a steep memory cost.

This is what makes an 8k-triangle LOD still read as detailed.

---

## Recipe F — Delight a satellite-derived albedo

ModelUnify has no delight step. Do it here, inside a Remesh or Texture Bake —
`Texture Output` → `Delight Settings`:

| Setting | Start at |
|---|---|
| Shadow Kernel | default; raise for large soft shadows |
| Strength | low, then increase until sun direction stops reading |
| Highlight Removal | raise for specular roof glare |
| Shadow Removal | raise for hard cast shadows |
| Falloff | widen if removal leaves halos |

Over-delighting flattens the albedo. Stop as soon as the light direction is
ambiguous.

---

## Recipe G — Cull interior geometry

**Occlusion Cull** with automatic interior-face detection removes polygons
sealed inside a closed building. For a partly open structure (hangar doors,
open sheds), place cameras at the angles a BMS pilot actually sees instead of
using automatic detection, or you will lose visible interior surfaces.

---

## Recipe H — Repair dirty geometry

**Mesh Toolkit (MTK)** before any other operation when the mesh has loose
vertices, inconsistent winding, or flipped normals: weld vertices, conform
normals. Several MTK tools are also on the `Mesh` menu for one-off use on the
scene.

---

## After Studio

Copy `outbox/<asset>/Model_1.glb` … `Model_6.glb` over the pymeshlab LODs in
`bms_export/<asset>/`. Keep `Model_0.glb` from ModelUnify.

If you ran Remesh, Material Merge, or UV Unwrap, the topology or UVs changed —
regenerate the **whole** LOD ladder from the new master rather than mixing it
with the old levels.

Then Blender + [BMS Blender plugin](https://github.com/BenchmarkSims/bms-blender-plugin)
for `.bml` — InstaLOD does not write BMLv2.
