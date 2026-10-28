# Mesh Workbench delivery and next steps

The agreed asset-centered CAD workbench has been implemented in source. The
current feature contract is [WORKBENCH.md](WORKBENCH.md); observed checks and
release gates are [WORKBENCH_VALIDATION.md](WORKBENCH_VALIDATION.md).

## Delivered

- Inputs → Generate → Texture → Optimize → Export in one desktop window.
- One persistent source/result/LOD viewport; PBR, pixel-channel and UV inspection.
- TripoSG one-image controls and Hunyuan 1–4-direction controls.
- Explicit shared background provider/model preparation, masks and advanced parameters.
- UI-independent operations, owned asset projects, immutable versions and checkpoints.
- Surface Lab, actual UV-aware reduction, editable LOD budgets/distances and reports.
- Named presets, saved custom controls, persistent isolated jobs, cancellation and diagnostics.
- Dedicated application-window launcher; original interface retained with --legacy.
- First optimization reliability increment: bounded passes, winding repair,
  strict triangle budgets, boundary/UV/bounds safeguards and GLB attribute checks.
  See [OPTIMIZATION_VALIDATION.md](OPTIMIZATION_VALIDATION.md) for acceptance tests
  and remaining silhouette/thin-part/non-manifold limitations.

## Finish release validation

1. Preserve the passing repeated GPU shape→paint, TripoSG and Surface Lab checks
   when changing models or dependencies; current evidence is in the validation guide.
2. Evaluate Surface Lab and generation quality on fixed representative assets.
3. Test the fresh, relocated portable release candidate on a separate clean
   Windows/NVIDIA machine; clean-package GPU checks on this host have passed.
4. Validate installer lifecycle separately, then retire duplicated legacy orchestration.

## Subsequent improvements

- Improve GUI usability using feedback on real projects; automated keyboard/high-DPI
  checks already cover four desktop sizes.
- Add measured model benchmarks and only then prioritize new model integrations.
- Explore UV repacking, silhouette/thin-part constraints and high-to-low baking as
  new algorithms, with their own validation rather than placeholder controls.
- Finish Blender/BML and authoritative DDS/BMS metadata tooling as explicit external
  integration work; export currently supplies intermediate meshes and templates.

The original detailed plan and prior handoff were preserved as compressed local
archives in `.runtime/docs-archive/` during the requested repository cleanup.
