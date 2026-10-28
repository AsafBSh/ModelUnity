# Falcon BMS workflow — `.glb` → `.bml` in-game asset

This is the full path from an AI-generated mesh to a model that loads in a
Falcon BMS mission. The AI tool gets you 70% of the way; the last 30% is
Blender + the official BMS plugin (no way around this — BMS uses a custom
`.bml` binary format).

> Skim the official BMS Blender Plugin manual once before doing this for real:
> https://github.com/BenchmarkSims/bms-blender-plugin/blob/main/docs/Manual/MANUAL.md

---

## 0. One-time setup

1. **Install Blender 4.x** (current LTS).
2. **Install the BMS Blender Plugin**:
   - Download the latest release from
     https://github.com/BenchmarkSims/bms-blender-plugin/releases
   - In Blender: *Edit → Preferences → Add-ons → Install from disk…* → pick the `.zip`.
   - Enable the addon. Point its `BMS Editor` path at your Falcon BMS install.
3. (Optional but recommended) Install a free PBR texturing tool:
   - **InstaMAT** (free; has a BMS preset)
   - **Substance Painter** (paid)

---

## 1. Generate the LOD set

Use a fresh asset name/output directory. Exports inspect the actual master,
preserve it, and refuse duplicate/no-op lower levels. Model_0 may retain the
master geometry; its GLB is reserialized. Use `--lod-count N` for fewer levels
or `--lod-faces 628,300,120` for a scaled ladder. Failed sets are not published.
Original photos stay at their input paths. Inspect `lod_report.json` and any
UV fallback warning before Blender import. Animated/skinned or multi-instance
masters need an explicitly baked static copy before this LOD path.

The UI also supports shape → Hunyuan3D-2.1 PBR paint → optional normals → LODs.
Paint is NVIDIA CUDA-only. Shared exports retain glTF MR (G=roughness,
B=metallic) and provide separate scalar maps for the Wavefront MTL.

Pick the right command for your inputs:

```powershell
.\activate.ps1

# Option A — single photo (TripoSG)
python scripts\generate_3d.py bms-lods inputs\satellite\hangar.png --name hangar_01

# Option B — 1–4 photos fused (Hunyuan3D-2mv). Recommended for buildings.
python scripts\generate_3d.py multiview-bms-lods --name hangar_01 `
       --front inputs\ground\hangar_front.jpg `
       --left  inputs\ground\hangar_left.jpg  `
       --back  inputs\satellite\hangar_top.jpg `
       --right inputs\ground\hangar_right.jpg
```

You now have `bms_export\hangar_01\` containing:

```
Model_0.glb .. Model_6.glb           # decimated geometry at falling face counts
lod_report.json                     # target/achieved faces, UV/fallback state
bms_template/                        # BMS-spec files (drop into Models\<XXXX>\
    Parent.dat                       #   after your BML export)
    materials.mtl                    # JSON scaffold, slots already named
    README.txt                       # PNG -> DDS conversion + extras
```

The Paint / textured flows also write `Model_*.obj` plus a Wavefront
`Materials.mtl` and placeholder `albedo.png` / `metallic_roughness.png`
into the same folder, for loading the OBJ into Blender / 3ds Max with the
placeholder textures already attached.

---

## 1b. Optional HQ LODs via InstaLOD Studio (Pioneer)

pymeshlab decimation in step 1 is the default. For cleaner lower LODs, run the
**master** mesh through InstaLOD Studio (free Pioneer license — desktop GUI
only, no CLI). See [`tools/instalod/README.md`](../tools/instalod/README.md)
and [`tools/instalod/profiles/RECIPES.md`](../tools/instalod/profiles/RECIPES.md).

```powershell
python tools\instalod\stage.py --name hangar_01
# or: python scripts\generate_3d.py instalod-stage --name hangar_01
```

In Studio: Optimize with **Automatic Quality Off** and Absolute Triangles
8000 / 3000 / 1000 / 400 / 150 / 60 (same as `bms_lods` in `config.yaml`).
Export `Model_1.glb` … `Model_6.glb` to `tools\instalod\outbox\hangar_01\`
and copy them over `bms_export\hangar_01\` — **keep** ModelUnify `Model_0.glb`.

This does **not** produce `.bml`. Continue with Blender below.

Pioneer requires attribution when you share or ship processed meshes
(https://docs.instalod.io/en/Products/InstaLOD_Studio/Licensing/Free_Pioneer_License_And_Attribution).
Do not add MCP/`InstaLODCmd` unless you license InstaLOD Pipeline.

---

## 2. Open each LOD in Blender, one collection per LOD

The BMS plugin maps **one Blender *collection* per LOD**. The Plugin will
export each collection into its own `.bml`.

Recommended workflow:

1. Open Blender → delete the default cube.
2. *File → Import → glTF 2.0 (.glb/.gltf)* → import `Model_0.glb`.
3. Rename the imported collection to **`LOD_0`**.
4. Repeat for `Model_1.glb` ... `Model_6.glb`, naming collections
   `LOD_1` ... `LOD_6`. Each goes in its own collection.
5. **Important:** make sure each LOD is in the right place — the BMS plugin's
   LOD subpanel pairs Blender collections to LOD numbers + viewing distances.

### LOD viewing distances (BMS will swap LODs at these distances)

| LOD | Suggested distance (ft) | Notes |
|---|---|---|
| 0 | 500   | Closest, full detail |
| 1 | 1500  | |
| 2 | 4000  | |
| 3 | 10000 | |
| 4 | 25000 | |
| 5 | 60000 | |
| 6 | 150000 | Impostor / silhouette |

(These match the `bms_template/Parent.dat` we wrote. Tune to taste.)

---

## 3. Texture the model (PBR)

This is where BMS really wants you to spend time, because the AI texture is
just a planar projection placeholder.

1. With **LOD_0** as the active collection, select your mesh.
2. *File → Export → FBX or OBJ* — temporarily — and bring it into InstaMAT
   or Substance Painter.
3. Bake your base maps (Normal, AO, Curvature) from the high-poly geometry.
4. Use the **BMS preset** to export back as:
   - `<asset>_Albedo.dds`
   - `<asset>_ARMW.dds` (AO / Roughness / Metallic / `W` mask)
   - `<asset>_Normal.dds`
5. Back in Blender: assign the new material to the LOD_0 mesh (the BMS
   plugin reads it directly).

> See the BMS forum's [InstaMAT walkthrough](https://forum.falcon-bms.com/topic/27621/instamat-free-pbr-platform)
> for a concrete recipe.

---

## 4. Export to `.bml` via the BMS plugin

In Blender:

1. *File → Export → F4-BMS (.bml)*
2. **Tick "Export materials"** — without `Materials.mtl` BMS won't load the model.
3. Output to `bms_export\hangar_01\` so everything ends up beside each other.

You should now have, in `bms_export\hangar_01\`:

```
Model_0.bml  Model_1.bml ... Model_6.bml
Materials.mtl
Parent.dat                     # produced by the plugin
hangar_01_Albedo.dds  hangar_01_ARMW.dds  hangar_01_Normal.dds
```

Verify `Parent.dat` references all 7 LOD files and their viewing distances.

---

## 5. Pick an unused Parent ID in the BMS Editor

1. Launch **BMS Editor** (from the Falcon BMS Launcher).
2. *Open DB for your theater* (e.g. Korea KTO).
3. Go to the **Models** tab.
4. Find an unused row (a `-1` in the parent column = free), or count up
   from the last used ID. **Note the ID** — that's your `--parent-id`.

---

## 6. Deploy into the theater

```powershell
python scripts\deploy_bms.py bms_export\hangar_01 --parent-id 12345
```

This copies:

- `Model_0.bml`...`Model_6.bml`, `Parent.dat`, `Materials.mtl`, `*.mti`
  → `<BMS>\Data\TerrData\Objects\Models\12345\`
- `*.dds` → `<BMS>\Data\TerrData\Objects\KoreaObj\`
  (or whatever folder you pass via `--obj-folder`)

(If you set `bms.bms_install` in `config.yaml` you can omit `--bms-install`.)

---

## 7. Verify

1. Re-open BMS Editor → Models tab → scroll to model **12345**.
2. The preview should show your asset with textures.
3. If you placed it correctly you can now reference parent ID `12345` from
   a feature, objective or unit definition for use in missions.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Editor shows an untextured grey blob | `Materials.mtl` missing, or `.dds` not in `KoreaObj`. |
| Model doesn't appear at all | `Parent.dat` references a `Model_0.bml` that wasn't copied. Check filename casing. |
| LODs pop in wrong | Viewing distances in `Parent.dat` are off. Tune them. |
| Lighting looks wrong / inverted | Re-export normals from your PBR tool with the BMS preset (Y-flip). |
| Object floats / sinks in game | Origin not at the base of the mesh. In Blender: select mesh, `Object → Set Origin → Origin to 3D Cursor` at world `(0,0,0)`, with mesh base on the floor. |
| Crash on load | Geometry has degenerate faces or non-manifold edges. In Blender: Edit mode → `M → By Distance`, then `Mesh → Clean Up → Make Manifold`. |

---

## Why this many manual steps?

Falcon BMS uses a closed, fairly old asset pipeline (`.bml` is BMS-specific
binary geometry, `Parent.dat` is custom metadata, and the texture format is
DDS with a BMS-specific channel packing). The AI step *replaces* the
"sit in 3ds Max for a week sculpting a building" step — which is the bulk
of the work — but doesn't replace BMS's required final-mile tooling.
