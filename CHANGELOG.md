# ModelUnify releases

Each entry records the version, date and main user-visible changes. Historical
entries describe their own delivery; validation of one version does not certify
later packages or machines.

## 1.12.1 — 2026-10-30

- Update the README, setup guides and illustrated Word guide for the Models manager.
- Add committed-source export packages with file hashes, a source commit manifest
  and a SHA-256 checksum; exclude weights, runtimes and private development data.
- Document the release procedure and require a dated change log for every update.
- Validation: 156 CPU tests, including source-export checks, passed alongside
  interactive model-manager checks for the
  implementation. ComfyUI and paint runtime probes passed on the reference GPU.
  Full AI inference and clean portable-runtime validation remain separate.

## 1.12.0 — 2026-10-30

- Add a Models workspace with persistent installation activity, resumable downloads,
  integrity verification, repair, updates and reviewed removal of owned weights.
- Manage shared model dependencies, storage locations and isolated ComfyUI runtime
  actions from the GUI; keep credentials in session memory.
- Check selected workflow prerequisites before queuing AI work; generation and
  preparation no longer start hidden checkpoint downloads.

## 1.11.4 — 2026-10-30

- Illustrate the README and operating guides with real Mesh Workbench screenshots.
- Show model-specific inputs, texture inspection, optimization and export menus.
- Add saved building, tank, hangar and jet examples with their actual limitations.

## 1.11.3 — 2026-10-28

- Keep the published repository focused on application source and current user guides.
- Exclude editor guidance, workflows, tests and historical development reports.
- Require pull requests to main without an automated CI status requirement.

## 1.11.2 — 2026-10-28

- Publish the application source and practical GUI/model operating guide.
- Keep model weights optional and document their installation.

## 1.11.0 — 2026-10-24

- Add manual masks, silhouette comparisons, protected optimization, UV rebaking
  and general interchange/static BMS handoff.
