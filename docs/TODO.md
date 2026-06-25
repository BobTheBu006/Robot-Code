# Architecture TODO

This file is for deferred ideas that should not be lost. Keep it practical: add enough context for the next agent to continue the design or implementation.

## Near-Term Architecture Work

- Extend schema version coverage to module manifests, firmware protocol descriptors, and future schematic/simulation imports.
- Add migration helpers for hardware maps, workflows, and function manifests.
- Add golden fixture tests for current hardware map and active workflow.
- Extend broken-placeholder behavior to backend validation responses and hardware-map controller/device repair actions.
- Extend the workflow firmware planner into real per-controller firmware assembly/generation.
- Add real controller execution for generated basic hardware blocks, including calibrated peristaltic pump steppers.
- Define how advanced functions reference generated basic blocks in a machine-readable way.
- Make compound functions exportable and importable as reusable modules.

## Module System

- Decide whether modules stay inside this monorepo or can be pulled from separate Git repositories.
- Define module install/update/remove commands.
- Define a trust model for community module code.
- Define module package structure for:
  - hardware templates
  - function manifests
  - backend handlers
  - frontend UI extensions
  - firmware routines
  - example workflows
  - tests
  - 3D/CAD models
  - documentation
- Create a local module registry folder before building any remote/community platform.

## Workflow Blocks

- Design API-call workflow block:
  - request configuration
  - timeout behavior
  - success/error paths
  - response mapping
  - secret-name references
- Design camera workflow blocks later:
  - capture frame
  - stream preview
  - wait for visual condition
  - send image to service
  - map detection response into workflow context
- Decide whether typed data edges are needed or whether workflow context/result mapping is enough.

## Hardware Map

- Add more device kinds only through explicit contracts.
- Add import/export for hardware map fragments.
- Investigate schematic imports later:
  - KiCad first if practical
  - Fusion Electronics export only if a stable import path exists
  - generic JSON as the internal exchange format
- Preserve Hardware Map as the source of truth for pin layout unless a future migration intentionally changes this.

## Firmware

- Replace planner-plus-flash behavior with full workflow-aware firmware assembly.
- Track firmware routines required by each function/block in generated controller images.
- Build one firmware image per controller per workflow run.
- Add dry-run firmware generation tests.
- Add compatibility checks between function firmware requirements and board capabilities.

## Simulation And 3D

- Treat simulation as future work.
- Use Hardware Map plus 3D/CAD models as the simulation source.
- Support collision prediction and prevention when mechanical models exist.
- Avoid simulation-only contracts that bypass real hardware definitions.

## Licensing And Community

- Keep repository software under Apache-2.0 unless changed intentionally.
- Use explicit licenses for future CAD/electronics/hardware packages.
- Prefer CERN-OHL-S-2.0 for open hardware packages where improvements should remain open.
- Add contributor guidance before accepting external community modules.
