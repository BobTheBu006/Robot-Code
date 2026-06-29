# Architecture Overview

## Purpose

The platform is a local-first robot-control system for modular lab automation. It should make physical hardware, controller firmware, backend functions, and visual workflows fit together through explicit contracts instead of hidden wiring assumptions.

## Runtime Shape

```text
Operator browser
  |
  v
React frontend
  |
  v
FastAPI backend on Raspberry Pi
  |
  +-- saved workflows
  +-- hardware map
  +-- function discovery and handlers
  +-- ESP32 firmware build/flash orchestration
  |
  v
ESP32 controllers
  |
  v
motors, servos, sensors, tools, future modules
```

## Main Components

### Frontend

The frontend is a Vite + React + TypeScript app.

Responsibilities:

- render operator dashboard panels
- edit the Hardware Map
- edit workflows with block diagrams
- expose block settings and function inputs
- call backend APIs for function discovery, workflow storage, hardware map storage, and ESP32 flash/run actions

### Backend

The backend is a FastAPI app.

Responsibilities:

- validate API contracts with Pydantic models
- discover backend function folders
- sync declared function hardware into the Hardware Map
- persist workflows and hardware map JSON
- build and flash ESP32 workspaces
- run or test backend function handlers

### Hardware Map

The Hardware Map owns the physical model:

- Raspberry Pi
- controllers
- USB ports
- devices
- pins
- groups

Functions and firmware should reference logical devices from the Hardware Map instead of carrying private pin maps.

### Workflow Editor

The Workflow Editor owns process logic:

- Basic blocks represent built-in control logic and direct hardware operations.
- Advanced functions represent backend/firmware-backed robot actions.
- Compound functions represent selected connected blocks collapsed into a reusable block.

Workflow edges represent control flow. Data should be passed through parameters, context, or result payloads, not through extra graph handles unless a future typed-data-edge contract is explicitly designed.

### Firmware

ESP32 firmware is the low-level execution layer.

Target design:

- collect all workflow blocks used in a run
- group block firmware requirements by controller
- generate or assemble one firmware image per controller
- include all routines needed by that workflow for that controller
- flash each required controller once before the workflow starts
- execute routines by command during the workflow

## Data Ownership

| Data | Source of truth |
| --- | --- |
| USB port to controller mapping | Hardware Map |
| controller to device mapping | Hardware Map |
| device pin mapping | Hardware Map |
| advanced function metadata | function manifest |
| function hardware needs | function manifest, synced into Hardware Map |
| workflow process | workflow JSON |
| controller firmware source | board workspace and future module firmware requirements |
| user secrets | backend environment or secret store, not workflow JSON |

## Extension Direction

New capability should enter through one of these boundaries:

- new hardware device type
- new advanced function manifest and handler
- new firmware routine
- new compound function
- future module package

Avoid adding new hidden side channels. If a feature needs hardware, declare hardware. If it needs firmware, declare firmware requirements. If it needs saved state, version the schema.
