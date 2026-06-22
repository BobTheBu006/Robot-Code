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
- ESP32 controller blocks with USB port selection.
- Devices connected to controllers.
- Device types:
  - stepper motor with direction, step, enable, and three micro-step signals
  - servo with one signal pin and min/max rotation fields
  - position/limit switch sensor
  - AHT20 temperature/humidity sensor with SCL and SDA signals
- Hardware groups that collapse selected controller/device assemblies into one block while keeping a visible Raspberry Pi connection.

The Hardware Map is the source of truth for USB ports, logical device IDs, pin assignments, and hardware groups.

## Workflow Editor Status

The Workflow Editor currently has:

- Basic blocks for trigger, logic, and hardware-map generated device actions.
- Advanced functions discovered from backend function manifests.
- Compound functions created from directly connected selected blocks.
- A separate compound-function editing canvas.
- Individual hide/unhide behavior for palette blocks.
- Right-click actions for creating, editing, and uncompounding compound functions.
- Pre-run ESP32 flashing for boards referenced by blocks in the workflow.

Workflow outputs are control-flow paths only. Function result data is not a graph output.

## Function And Hardware Dependency Status

Function manifests can declare `hardware_devices`. Those devices are synced into the Hardware Map using stable IDs and optional `function_input_key` pin links.

Important rule: an advanced function and its generated basic hardware block should point to the same logical hardware device. For example, a syringe dispenser function should declare syringe-head stepper devices, and the Workflow Editor should generate matching basic move blocks from those devices.

The same physical hardware map can support multiple code routines. A 7-syringe pump assembly is hardware. Dispense, prime, clean, calibrate, and other behaviors are code/functions that may all target that same hardware.

## Firmware Status

Current behavior flashes ESP32 boards used by a workflow before running it.

Target architecture: firmware flashed to a controller should include every routine needed by all workflow blocks that target that controller. A workflow may call different routines on the same controller at different times. Firmware generation should be based on:

- Hardware Map controller/device/pin data
- all blocks used in the workflow
- each block's firmware requirements
- each advanced function's declared hardware dependencies

## Deferred But Important

These are architecture directions, not implemented promises yet:

- API-call blocks as normal workflow blocks with success/error/timeout behavior.
- Camera modules connected over USB or another transport and controlled through workflow blocks.
- Simulation mode based on hardware map plus 3D/CAD models.
- Importing hardware maps from schematic or circuit design files.
- Community module packages that may live in Git repositories and include hardware, software, firmware, 3D models, docs, and tests.
- Exporting compound functions as reusable/shareable modules.

Track deferred work in `docs/TODO.md`.

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
