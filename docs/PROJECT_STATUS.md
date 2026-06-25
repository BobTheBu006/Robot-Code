# Project Status

Last meaningful update: 2026-06-22

## Mission

This project is a modular, open-source robotic platform for lab automation. It is intended as a direct alternative to closed, expensive automation systems, using cheap and available parts so underfunded research labs, universities, and small teams can build, repair, extend, and share hardware/software modules.

## Current Product Shape

The system is a local Raspberry Pi coordinated robot-control app:

- The Raspberry Pi runs the backend and frontend.
- ESP32 boards handle low-level motors, actuators, and sensors.
- The frontend gives the operator a Hardware Map and Workflow Editor.
- The backend stores workflows, discovers functions, syncs function hardware dependencies into the Hardware Map, and flashes ESP32 boards before workflow execution.

## Current Implemented Areas

- `backend/`: FastAPI app with routes for health, robot state, camera, hardware map, workflow storage, function discovery, and ESP32 builder/flash support.
- `frontend/`: React/Vite app with Hardware Map and Workflow Editor.
- `functions/esp 32 code/`: board workspaces with `board.json`, firmware entry files, and workflow-function blueprints.
- `backend/app/functions/`: backend-discovered advanced function folders with manifests and handlers.
- `hardware-map.json`: persisted physical map of boards, devices, pins, and hardware groups.
- `workflows/active-workflow.json`: persisted active workflow.

## Hardware Map Status

The Hardware Map currently models:

- Raspberry Pi coordinator block.
- Devices wired directly to Raspberry Pi GPIO or I2C using `board_id: raspberry-pi`.
- Hardware map connections can be disconnected from the canvas; disconnected devices stay visible as unconnected blocks until the operator reconnects them to the Raspberry Pi or a controller.
- ESP32 controller blocks with USB port selection.
- Devices connected to controllers.
- Device types:
  - stepper motor with direction, step, enable, and three micro-step signals
  - calibrated peristaltic pump steppers using mL per 200 full steps
  - servo with one signal pin and min/max rotation fields
  - position/limit switch sensor
  - AHT20 temperature/humidity sensor with SCL and SDA signals
- Default Raspberry Pi AHT20 I2C device using SCL GPIO 3 and SDA GPIO 2.
- X/Y axis motors and X/Y min/max limit switches may be mapped directly to Raspberry Pi GPIO. Current saved map uses X step/dir GPIO 17/27, Y step/dir GPIO 23/24, and XY limit switch inputs GPIO 5/6/12/13.
- Hardware groups that collapse selected controller/device assemblies into one block while keeping a visible Raspberry Pi connection.

The Hardware Map is the source of truth for USB ports, logical device IDs, pin assignments, and hardware groups.

## Workflow Editor Status

The Workflow Editor currently has:

- Basic blocks for trigger, logic, and hardware-map generated device actions.
- Calibrated peristaltic pump basic blocks generated from stepper devices with `calibration_ml_per_200_steps`.
- Advanced functions discovered from backend function manifests.
- Tool Change advanced function for six editable rack slots along the top-left work-area edge.
- Compound functions created from directly connected selected blocks.
- A separate compound-function editing canvas.
- Individual hide/unhide behavior for palette blocks.
- Right-click actions for creating, editing, and uncompounding compound functions.
- Pre-run ESP32 flashing for boards referenced by blocks in the workflow.
- Broken-reference placeholders for saved blocks whose function, hardware device, or module cannot currently be resolved.

Workflow outputs are control-flow paths only. Function result data is not a graph output.

## Function And Hardware Dependency Status

Function manifests can declare `hardware_devices`. Those devices are synced into the Hardware Map using stable IDs and optional `function_input_key` pin links.

Function manifests now carry `schema_version` at the backend model boundary. Legacy manifests without the field are treated as schema version 1. Unsupported future manifest schemas are rejected with a validation error instead of being loaded as if they were compatible.

Important rule: an advanced function and its generated basic hardware block should point to the same logical hardware device. For example, a syringe dispenser function should declare syringe-head stepper devices, and the Workflow Editor should generate matching basic move blocks from those devices.

The same physical hardware map can support multiple code routines. A 7-syringe pump assembly is hardware. Dispense, prime, clean, calibrate, and other behaviors are code/functions that may all target that same hardware.

## Firmware Status

Current behavior prepares a workflow firmware plan before flashing ESP32 boards used by a workflow.

Function manifests now expose `firmware_requirements`. Each requirement has a stable `routine_id`, controller role, optional source file, protocol, entry point, required hardware device IDs, and description. ESP32 workflow-function blueprints carry the same field under `manifest.firmware_requirements`, and generated backend manifests preserve it.

Before `Run all` flashes boards, the Workflow Editor collects firmware requirements from all blocks in the run, including inner blocks inside compound functions. It sends them to the backend ESP32 builder planner. The planner groups routines by controller, resolves each source file inside that controller workspace, deduplicates repeated routine requirements, and rejects missing or unsafe source paths before flashing starts.

Target architecture: firmware flashed to a controller should include every routine needed by all workflow blocks that target that controller. A workflow may call different routines on the same controller at different times. Firmware generation should be based on:

- Hardware Map controller/device/pin data
- all blocks used in the workflow
- each block's firmware requirements
- each advanced function's declared hardware dependencies

## Compatibility Status

Workflow files now normalize `schema_version` and legacy `version` values through the backend workflow storage service. Saved workflows are written with both `schema_version: 1` and `version: 1` for current frontend compatibility. Invalid or unsupported future workflow schemas are rejected.

There are lightweight backend `unittest` checks for:

- legacy function manifests gaining the current schema version
- unsupported function manifest schema versions being rejected
- legacy workflow payloads saving/loading with the current schema version
- unsupported workflow schema versions being rejected

The frontend now preserves unresolved saved workflow blocks as explicit missing-block placeholders. The placeholder keeps the original block ID, outputs, and edges visible, but disables normal execution and shows a suggested repair path.

## Deferred But Important

These are architecture directions, not implemented promises yet:

- API-call blocks as normal workflow blocks with success/error/timeout behavior.
- Camera modules connected over USB or another transport and controlled through workflow blocks.
- Simulation mode based on hardware map plus 3D/CAD models.
- Importing hardware maps from schematic or circuit design files.
- Community module packages that may live in Git repositories and include hardware, software, firmware, 3D models, docs, and tests.
- Exporting compound functions as reusable/shareable modules.

Track deferred feature work in `docs/FEATURE_ROADMAP.md` and lower-level architecture notes in `docs/TODO.md`.

## Status Update Rule

Update this file after meaningful changes. Meaningful means the next agent would make a worse design decision if they did not know about the change.

Examples that should update this file:

- new hardware type
- new workflow block type
- changed block-output behavior
- changed function manifest schema
- changed hardware map schema
- changed firmware build/flash behavior
- changed module packaging direction
- changed compatibility/migration policy

Examples that usually do not need a status update:

- minor CSS polish
- typo fixes
- local refactors with no behavior change
- tests that only cover an existing behavior more thoroughly
