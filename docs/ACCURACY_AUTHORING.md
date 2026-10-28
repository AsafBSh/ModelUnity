# Accuracy and authoring tools — v1.11.0

These additions fit the restored Mesh Workbench. They preserve source assets and
use the same single 3D viewport, owned projects and preview/checkpoint workflow.
Manual mask editing, reference comparisons, protected optimization, UV rebaking
and package preparation run on CPU independently of GPU vendor. Existing AI
generation and painting still target Windows/NVIDIA CUDA.

## Correct reference masks

In Inputs, select a direction and open **Manual mask correction**. Load the view
with the current background-removal provider. Paint white to restore foreground
or black to remove background; use Undo/Clear to remove strokes. Images up to
4096 pixels per side are supported for manual editing. Apply the edits,
then save the project or generate. Each correction is bound to an exact image
pixel fingerprint; generation preserves it even if automatic removal was selected.
The crop/padding/output-size preparation still runs once afterward. A different
image does not inherit another image's correction. Old owned image files remain.

## Compare a reference silhouette

Open the right-side **Reference** inspector. Upload an alpha-masked photograph or
copy the selected input view. Adjust yaw, pitch, scale and image offsets, then
compare. Red is reference-only foreground, cyan is mesh-only, green is overlap.
The report includes IoU and boundary distances in comparison pixels.

This is a user-aligned orthographic silhouette, not automatic camera calibration
or proof of 3D accuracy. Perspective, reference segmentation and clipping affect
the score. Texture transparency is ignored by the geometry rasterizer. Inspect
more than one direction and retain measured dimensions.

## Protect thin parts and edges

In Optimize, open **Protect parts during optimization**. Shift-click the working
Result in the viewport to pick a local mesh point, or enter X,Y,Z numerically.
Set a region half-size and convert the center into a box. Alternatively specify
zero-based triangle IDs, or an angle to protect triangles adjacent to sharp edges.
The box conservatively selects triangles whose bounds intersect it.

Inspect the selection: green highlights protected faces on a temporary copy;
changing a viewer control restores the normal material display. Configure the
triangle target and optimize. Selected triangles retain their positions, winding
and UVs; the remaining region is reduced with its boundaries protected. A budget
smaller than the protected set is refused. Whole-mesh bounds/surface guards remain.

Selections refer to the current working geometry; do not pick a different raw or
accepted comparison mesh. Recreate selections after topology changes. These
constraints apply only to this Optimize operation, not later paint/remesh/LOD jobs.
Split cut boundaries remain separate vertex records; inspect seam shading.
Shift-click triangle intersection is capped at two million displayed triangles;
use numerical region coordinates for larger meshes.

## Repair UVs and transfer high-detail textures

In the **UV** inspector, open **Repair UVs / rebake textures**. Use the current mesh
as both source and target for a new atlas, or supply an aligned high-detail GLB
with valid UVs/textures to project onto the current lower-detail mesh. Choose
256–2048 atlas pixels, padding and maximum projection distance, then queue a preview.
The high source is copied into the project so a recorded request can be rerun.

xatlas creates new charts and packs the atlas; CPU closest-surface sampling
transfers albedo, MR, AO, emission and tangent-normal information where available.
Padding is dilated from covered texels. The job fails if projection distance or
bounded raster-work limits are exceeded. Target bounds and triangle count survive
the GLB round-trip; input meshes are unchanged. Accept a checkpoint after review.

This reparameterizes UVs rather than fixing mesh holes or inventing missing image
detail. Nearby surfaces can receive the wrong projection. Tangent transfer uses
per-triangle derivatives/interpolated normals, not certified MikkTSpace; inspect
normal seams in the destination renderer. CPU limits are 200k target/1M source
triangles and 40M raster candidates. All limits fail visibly.

## General interchange and static BMS handoff

Export includes **interchange/** with an OBJ, a genuine Wavefront MTL and texture
companions per LOD, plus a BMS next-steps text guide. Input coordinates stay in
their original units; the report records metres per input unit. Import support
for Wavefront PBR extensions varies, so the GLB remains the material reference.
Download `export_package.zip` to keep the complete relative folder structure.
Its CRC is verified before the preview is published. Individual GLBs and the
package report remain available beside the ZIP in the download list.

Enable **Also author static BMS sidecars** for an additional **bms_handoff/**:

- `Materials.mtl`: BMS JSON, separate from the Wavefront MTLs.
- `Model_n.mti`: one material name per LOD, matching its staged single material.
- `Parent.dat`: one skin, zero DOFs/switches, selected LOD distances and bounds
  calculated from the actual staged BMS-coordinate geometry in feet.
- `geometry/Model_n.obj` plus Wavefront sidecars for DCC authoring in those units.
- Albedo, packed ARMW and normal PNGs with the exact DDS basenames referenced by
  the BMS material library. Wetness is explicitly authored; missing normals are
  explicitly reported neutral maps, not invented detail.

The signed-axis mapping states how source axes become BMS X,Y,Z. Its default
`+Z,-X,-Y` must be reviewed for the particular model. General geometry is unaffected.
Do not perform a second axis/feet conversion when exporting the staged geometry.
Compare the external exporter's BML bounds against Parent.dat before use.

This narrow handoff supports opaque, single-sided static PBR assets. Glass,
cutouts, emissive effects, animated aircraft/turrets and multi-skin/multi-material
authoring require explicit external work. Existing legacy `bms_template/` files
are earlier scaffolds; use the new package report and `bms_handoff/` together.

### Finish the BMS object

1. Author/export one BML per LOD with a compatible Blender/3ds Max BMS exporter.
2. Convert PNGs to the referenced DDS names: albedo sRGB; ARMW/normal linear.
   ARMW is R=AO, G=roughness, B=metallic, A=wetness. Choose DDS encoding for the
   shader/toolchain; v2 alone does not impose BC7.
3. Verify BML material-slot order and shader vertex layout/tangents. Adjust MTI
   and material names to match the actual exporter output. For S skins/M slots,
   an MTI requires S×M skin-major names, including repetitions.
4. Inspect the complete folder in BML Workbench/BMS Editor, across LODs, skins,
   orientations and lighting; then validate in a test BMS installation.
5. Reserve a parent/object ID and register it using the target theater's database
   tools. Other DAT/CT/feature records depend on object type and theater; this
   application does not guess or overwrite them. Retain backups before deployment.

No generated handoff is marked BMS-ready until those external checks are done.

## Workflow evidence

Reviewed the existing **BML Blender/Max export and DCC debugging** and **BML
v1-to-v2 converter validation** chats, together with BML Workbench's local
`docs/BML_V1_V2_MODELLER_MAP.md`, `src/bmltool/convert_v1_mesh.py` and
`src/bmltool/materials.py` under `C:/AI Projects/BMS_Art/bml-toolkit`.
Those sources establish MTI skin-major ordering, named JSON material definitions,
shader-specific map slots, Parent.dat scope and the need for runtime verification.
No source or deployment files in the BML Workbench/BMS installations were modified.
