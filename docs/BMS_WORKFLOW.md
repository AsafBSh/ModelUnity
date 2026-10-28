# Finish a ModelUnify asset for Falcon BMS

ModelUnify creates intermediate meshes, LODs, textures and optional static BMS
sidecars. Final BML/DDS conversion, material-slot checks, database registration
and in-game validation use external BMS/DCC tools.

## Prepare the source

Use the [operating guide](OPERATING_GUIDE.md) to generate or import a mesh. Preserve
the original and raw master. Check silhouette from several directions and protect
thin parts when optimizing. Measure a known dimension and apply physical scale.
AI generation does not establish accurate dimensions or camera calibration.

The static handoff supports opaque, single-sided assets with one material and
one skin per LOD. Glass, cutouts, animated turrets/aircraft, controls and multiple
skins/materials require additional external authoring.

## Export a package

In Export, select 1 to 7 decreasing LOD budgets and planning distances. Inspect
every actual LOD in the same viewer. Lower levels must reduce geometry; inspect
the export report for achieved budgets, preserved maps and any UV fallback.

Download export_package.zip to preserve the relative folder structure:

- GLB assets retain their materials and serve as the interchange reference.
- interchange/ contains OBJ geometry, genuine Wavefront MTLs and PBR companions.
- Reports record units, budgets and limitations; NEXT_STEPS_BMS.txt describes
  external work still required.

Enable Also author static BMS sidecars for bms_handoff/:

- Materials.mtl is a BMS JSON material library, distinct from Wavefront MTL.
- Model_n.mti names the material for each staged LOD.
- Parent.dat records one skin, zero DOFs/switches, LOD distances and actual
  staged geometry bounds in feet.
- geometry/ contains the staged OBJ/MTL assets; PNG maps use the DDS basenames
  referenced by the material library.

Review metres per input unit and the signed-axis mapping; the default is
`+Z,-X,-Y`. Staged geometry is already converted to BMS axes and feet. Avoid a
second conversion in the external exporter. Legacy CLI bms_template/ scaffolds
are different outputs; do not substitute them for the current package report.

## Produce BML and DDS

1. Use a compatible Blender or 3ds Max BMS exporter to create one BML per LOD.
   Follow the exporter's own installation and version requirements.
2. Convert the named PNGs to the referenced DDS files. Albedo is sRGB; packed
   ARMW and normal data are linear. ARMW is R AO, G roughness, B metallic and
   A wetness. Choose DDS encoding for the actual shader/toolchain.
3. Compare actual BML bounds with Parent.dat and verify orientation and scale.
4. Reconcile actual BML material-slot order with each MTI and Materials.mtl.
   For S skins and M slots the MTI needs S times M skin-major names, retaining
   repetitions. A v2 BML alone neither guarantees PBR quality nor requires BC7.

## Inspect and register

Open the complete folder in BML Workbench/BMS Editor. Inspect materials, lighting,
orientation, scale and every LOD. Then validate in a backed-up test BMS install.
Reserve the object/parent ID and register it with the target theater's database
tools. Other DAT/CT/feature records depend on the object type and theater; this
application does not guess or overwrite them.

The deploy helper is for finished assets and is never run by normal export. Check
its CLI help and dry-run output before any explicit deployment. A successful
intermediate export is not in-game certification.

## Optional InstaLOD Studio step

Use [Studio staging](../tools/instalod/README.md) for a manual inbox/outbox workflow.
Preserve the master, inspect returned LODs and continue with the BML/DDS process.
This integration does not include InstaLOD Pipeline or an InstaLODCmd wrapper.
Retain applicable upstream licenses and attribution.
