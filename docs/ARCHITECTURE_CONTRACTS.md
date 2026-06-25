# Architecture Contracts

These contracts are intended to stay stable from the public `v0.1 beta` release through the `v1.x` series. A hypothetical `v2` may fix deeper architecture problems, but it should still provide migrations for saved projects.

## Contract 1: Hardware Map Is Physical Truth

The Hardware Map owns physical wiring and grouping:

- USB port to controller
- Raspberry Pi GPIO/I2C direct device wiring
- controller to device
- device kind
- device logical ID
- device pins and signal names
- device calibration metadata such as pump mL per 200 motor steps
- controller/device groups

Functions, firmware, and workflow blocks must not treat private pin maps as the source of truth. They may provide defaults or requirements, but the Hardware Map resolves the actual physical setup.

Workflow function blocks must not expose controller selection, USB port selection, "Selected ESP32", or GPIO pin selection as normal per-block operator settings. Those values are derived from the function's logical hardware devices and the Hardware Map at execution/firmware-planning time.

Devices wired directly to the Pi use `board_id: raspberry-pi`. This is a virtual controller ID and must not create a duplicate ESP32/controller block.

Devices with an empty `board_id` are intentionally unconnected. The UI must keep them visible so they can be reconnected instead of silently deleting or reassigning them.

The current gantry model is CoreXY, not independent left/right or independent X/Y motors. The stable `x-axis-motor` and `y-axis-motor` IDs are compatibility names for CoreXY A and CoreXY B motors. The normal Cartesian gantry coordinate system is X/Y/Z in centimeters from the back-bottom-left origin, with a current nominal work envelope of 115 cm x 60 cm x 60 cm.

## Contract 2: Logical Device IDs Are Stable

Device IDs are the durable bridge between:

- hardware map entries
- generated basic blocks
- advanced function manifests
- firmware generation
- saved workflows

Do not rename IDs casually. If an ID changes, provide an alias or migration.

## Contract 3: Functions Declare Hardware Dependencies

Any function that uses hardware must declare it in `manifest.hardware_devices`.

Each declared device should include:

- stable `id`
- user-facing `name`
- `kind`
- optional `sensor_kind`
- optional `board_id`
- required signal rows in `pins`
- optional calibration metadata such as `calibration_ml_per_200_steps` for peristaltic pump steppers
- optional `function_input_key` links for fields that can be configured by function inputs
- optional `basic_block_id` for the generated primitive block

Advanced function code may still contain behavior, calibration, and command logic. It must not become the only place where hardware requirements are known.

## Contract 4: Hardware And Code Are Related But Not Married

A hardware assembly can support many functions.

Example: a 7-syringe pump is hardware. Dispense, prime, wash, calibrate, mix, and maintenance actions are different code routines that may all target the same hardware map.

When a workflow runs, the controller firmware should contain every routine required by all blocks targeting that controller.

## Contract 5: Workflow Outputs Are Control Flow

Graph outputs are flow-control paths.

Normal robot-action blocks should expose:

- `next`

Failures should use the block settings error path unless the block is explicitly a branching/logic block.

Motion blocks should prefer explicit numeric motion parameters such as RPM and acceleration over opaque speed presets. If a preset field is kept for backwards compatibility, new UI should present the numeric fields.

Allowed multi-output blocks include:

- if/else
- while/loop
- switch/case
- wait-until with timeout path
- API call with success/error/timeout paths if that is modeled as branching flow

Do not add handles for returned data such as status, measurements, or raw controller replies. Put those values in the result payload or workflow context.

## Contract 6: Compound Function Outputs

Compound functions are made from directly connected selected workflow blocks.

A compound block exposes the unconnected non-error flow outputs of the internal blocks. Internal error paths should stay internal unless the compound function explicitly exposes an error policy.

Compound functions must remain editable. Uncompounding should restore the internal block graph when possible.

## Contract 7: API Calls Are Workflow Blocks

External API calls should be normal workflow blocks.

The block contract should support:

- method
- URL or service ID
- headers
- request body
- timeout
- response mapping
- success path
- error or timeout path

Secrets must not be stored directly in workflow JSON. Store secret values in backend environment variables or a future secret store, and let workflows reference secret names.

## Contract 8: Firmware Is Per-Controller And Workflow-Aware

The firmware build/flash step should be driven by:

- the active workflow
- blocks used by that workflow
- hardware devices referenced by those blocks
- Hardware Map pin assignments
- `firmware_requirements` declared by modules/functions

The backend should build or assemble one firmware image per controller and flash each used controller before workflow execution. The image must include every routine needed by that controller during the workflow, not only the first block that uses it.

Only controllers present in the Hardware Map should be flashed. If the Hardware Map has no ESP32 controller boards for the workflow, the run must skip flashing and continue directly to execution. Stale manifest `builder_board_id` values are not enough to flash a board.

Each firmware requirement should carry a stable `routine_id`, controller targeting role, source file or fragment, protocol, optional entry point, and any required logical device IDs.

Current implementation note: `POST /api/esp32-builder/workflow-firmware/plan` is the backend boundary for collecting and validating per-controller requirements before flashing. Future code generation should extend this plan into actual assembled firmware images instead of introducing a separate path.

## Contract 9: E-Stop Is Highest Priority

The operator UI must keep an E-Stop control visible independent of page scroll or canvas state.

When E-Stop is pressed, the frontend must immediately abort in-flight workflow requests and the backend must immediately send a stop command to every active controller session it knows about. Controller firmware should treat `STOP` as a highest-priority command and stop motion before normal command completion handling.

During normal gantry motion, an unexpected physical limit-switch hit is treated as the same class of immediate stop fault. Calibration routines are the exception: they intentionally probe limit switches using controlled fast-touch, backoff, and slow-touch motion to define workspace boundaries.

## Contract 10: Missing References Stay Visible

If an old workflow references a missing function, module, device, controller, pin, or firmware routine:

- load the workflow anyway
- show a broken placeholder
- explain what is missing
- suggest a repair path

Do not silently delete blocks or edges from saved workflows.

## Contract 11: Modules Are Contract Packages

Future modules may live in this repository, a local folder, or a Git repository.

A module package should be able to declare:

- module ID and version
- compatible platform schema versions
- function manifests
- hardware templates
- firmware routines or firmware fragments
- backend handlers
- frontend UI extensions
- example workflows
- 3D/CAD models
- simulation hooks
- tests
- license

Do not split modules into separate repositories until the import/build/test workflow is clear enough to reduce maintenance work instead of increasing it.

## Contract 12: Simulation Is A First-Class Future Target

Simulation should eventually use the same contracts as real hardware:

- Hardware Map for device structure
- 3D/CAD models for geometry
- function manifests for behavior surface
- firmware or simulated controller routines for low-level behavior
- workflow JSON for process logic

Do not design simulation-only APIs that bypass the Hardware Map.

## Contract 13: Schema Versions Are Required For Persistent Data

Persistent project files must carry a schema version before `v0.1 beta`.

Applies to:

- hardware maps
- workflows
- function manifests
- module manifests
- firmware protocol descriptors
- future schematic imports
- future simulation model descriptors

When changing a persisted schema, add migration logic and tests.
