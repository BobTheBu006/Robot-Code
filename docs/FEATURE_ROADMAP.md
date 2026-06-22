# Feature Roadmap

This file tracks the larger feature ideas that came from architecture planning. Keep `docs/PROJECT_STATUS.md` for what is true now; keep this file for what should be implemented next.

## Implementation Queue

1. Broken reference placeholders
   - Status: implemented for frontend saved workflow blocks
   - Load old workflows even when referenced functions, hardware devices, controllers, or modules are missing.
   - Keep the original block visible with preserved edges and outputs.
   - Show the missing reference and suggested fix.
   - Remaining: add backend-side validation summaries and direct repair actions for missing hardware map references.

2. Firmware requirement contract
   - Add a real `firmware_requirements` field to function manifests and frontend types.
   - Let each block declare the routines it needs on an ESP32.

3. Workflow-aware firmware assembly
   - Before running a workflow, collect every block used in the run.
   - Group requirements by controller.
   - Build/flash one controller image containing all required routines for that workflow.

4. Explicit advanced-to-basic hardware links
   - Make advanced functions machine-reference the generated basic blocks they depend on.
   - Keep the Hardware Map as the source of truth for pins and devices.

5. Golden compatibility fixtures
   - Add example saved workflows, hardware maps, function manifests, and future module manifests.
   - Test that old fixtures still load and migrate.

6. Exportable compound functions
   - Save a compound function as a reusable module/function package.
   - Preserve external non-error outputs.
   - Keep the compound editable after import.

7. API-call workflow block
   - Normal workflow block that calls an external service and waits for a response.
   - Support success/error/timeout paths.
   - Store secrets by name in the workflow; keep secret values in backend environment or a future secret store.

8. Local module registry
   - Add an internal `modules/` structure before Git/community imports.
   - Define how modules declare hardware, functions, firmware, frontend extensions, examples, tests, docs, CAD, and licenses.

9. Community Git module import
   - Pull a module from a Git repo.
   - Check schema compatibility, license metadata, tests, and build requirements before use.

10. Hardware map fragment import/export
    - Export reusable hardware assemblies.
    - Import hardware map fragments into a project.
    - Keep schematic import as later work.

11. Schematic import
    - Investigate KiCad first.
    - Consider Fusion Electronics only if there is a stable export path.
    - Convert external designs into the internal Hardware Map JSON.

12. Camera module workflow blocks
    - USB camera support through workflow blocks.
    - Initial possible blocks: capture frame, stream preview, wait for visual condition, send image to service.

13. Simulation and collision prevention
    - Use Hardware Map plus CAD/3D models.
    - Support later collision prediction and dry-run workflow tests.

14. Security/trust model for community modules
    - Decide how to handle untrusted backend/frontend/firmware code.
    - Add warnings or sandboxing before remote community imports.

## Rule For Future Agents

When implementing one item, update its status here and move any newly discovered subfeatures into this file instead of burying them in code comments.
