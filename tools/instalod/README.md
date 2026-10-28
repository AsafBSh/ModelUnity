# InstaLOD Pioneer workspace

Optional **post-process** hop after ModelUnify generates a mesh. This folder
does **not** contain InstaLOD itself (licensed app, not vendored source).

**License path:** free [InstaLOD Pioneer](https://docs.instalod.io/en/Products/InstaLOD_Studio/Licensing/Free_Pioneer_License_And_Attribution)
gives **InstaLOD Studio** (desktop GUI). Pioneer has **no** CLI, REST API, or
MCP. Cursor / ModelUnify can only **stage GLBs** here; you run Optimize /
Remesh in Studio by hand.

Do not wrap `InstaLODCmd` or an MCP server unless you later buy **InstaLOD
Pipeline**. The Blender add-on is **not** included with Pioneer.

## One-time setup

1. Sign up for Pioneer: https://instalod.com/licensing/?pioneer=true
   (annual revenue or funding under $100,000; attribution required when you
   share or ship content).
2. Install **InstaLOD Studio** for Windows from
   [License Management](https://cloud2.instalod.io/) → Your Files.
3. Build the BMS Optimize profile once in Studio using
   [profiles/RECIPES.md](profiles/RECIPES.md), then **File → Save Profile**
   into `tools/instalod/profiles/` (commit the JSON after it works).

## Per-asset flow

```
ModelUnify (Model_0.glb)
    → python tools/instalod/stage.py --name hangar_01
    → tools/instalod/inbox/hangar_01/Model_0.glb
    → InstaLOD Studio (Open Profile, Start, export)
    → tools/instalod/outbox/hangar_01/Model_1.glb … Model_6.glb
    → copy over bms_export/hangar_01/ (keep Model_0)
    → Blender + BMS plugin → .bml
```

### Stage a master mesh

From the repo root (venv activated):

```powershell
# After bms-lods / multiview-bms-lods / paint
python tools\instalod\stage.py --name hangar_01

# Or a specific GLB
python tools\instalod\stage.py --glb outputs\hangar_01.glb --name hangar_01

# Same helper via the main CLI
python scripts\generate_3d.py instalod-stage --name hangar_01
```

### In Studio

1. Drag `inbox\<name>\Model_0.glb` into the viewport (or File → Import).
2. **File → Open Profile…** and pick `profiles\BMS_LOD_Optimize.json` once you
   have saved it. Until then, follow [profiles/RECIPES.md](profiles/RECIPES.md).
3. Click **Start**.
4. Export each LOD as GLB into `outbox\<name>\` named `Model_1.glb` …
   `Model_6.glb`. Leave `Model_0` as the ModelUnify master.

Copy the outbox LODs over `bms_export\<name>\Model_1.glb` … `Model_6.glb`.
Continue with [docs/BMS_WORKFLOW.md](../../docs/BMS_WORKFLOW.md) (Blender BMLv2).

## Presentation / game (not BMS)

Same inbox, but use a **Remesh** profile (UVs + baked normals) instead of the
BMS triangle ladder. Export a single GLB to `outbox\<name>\` for viewers or
engines. See RECIPES.md.

## Attribution (Pioneer)

When you share, publish, or distribute meshes processed with Pioneer, credit
InstaLOD (splash logo for a game/app; readme link for BMS mods). Details:
https://docs.instalod.io/en/Products/InstaLOD_Studio/Licensing/Free_Pioneer_License_And_Attribution

## Layout

| Path | Purpose |
|------|---------|
| `inbox/<asset>/` | Staged master GLB (gitignored) |
| `outbox/<asset>/` | Studio exports (gitignored) |
| `profiles/` | Studio JSON profiles (commit after first save) |
| `stage.py` | Copy helper only — does not run InstaLOD |
