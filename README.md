# Modular Robot Control Platform

This repository is the working prototype for a modular, open-source lab robot platform aimed at underfunded research labs, universities, and small teams that need repairable automation built from cheap, available parts.

The long-term target is an extensible alternative to closed lab automation systems. The Raspberry Pi coordinates the robot, the browser UI edits workflows and hardware maps, and ESP32 controllers run the low-level motor, actuator, and sensor code.

## Start Here

For future AI coding agents and maintainers:

- Read `docs/ARCHITECTURE_CONTRACTS.md` before changing schemas, workflow behavior, firmware generation, or module boundaries.
- Read `docs/BACKWARDS_COMPATIBILITY.md` before changing saved workflows, hardware maps, manifests, or firmware protocols.

## Current Capabilities

- FastAPI backend with health, robot state, camera, hardware map, function discovery, ESP32 builder, and workflow storage routes.
- Vite + React + TypeScript frontend.
- React Flow workflow editor with built-in flow controls, advanced function blocks, and compound function blocks.
- Hardware Map editor for Raspberry Pi, ESP32 controllers, motors, servos, sensors, and grouped hardware assemblies.
- Function manifests can declare hardware dependencies so the Hardware Map and workflow blocks can reference the same logical devices.
- Workflow runs flash the ESP32 boards used by the workflow before execution.

## Repository Structure

```text
.
|-- backend/
|-- docs/
|-- firmware/
|-- frontend/
|-- functions/
|-- hardware/
|-- hardware-map.json
`-- workflows/
```

## Quick Start

Prerequisites:

- Python 3.11+ for the backend
- Node.js 20+ with `npm` for the frontend
- Arduino CLI for ESP32 build/flash flows

### Start Everything

On Windows 11:

```powershell
cd "C:\BOB\masters\Thesis\Robot Code"
start-all.bat
```

On Raspberry Pi OS / Linux:

```bash
cd "/home/robot/robot control/Robot-Code"
./start-all.sh
```

Frontend UI:

```text
http://127.0.0.1:5173
```

Backend API:

```text
http://127.0.0.1:8000
```

### Start Backend Only

```powershell
cd "C:\BOB\masters\Thesis\Robot Code"
start-backend.bat
```

### Start Frontend Only

```powershell
cd "C:\BOB\masters\Thesis\Robot Code"
start-frontend.bat
```

## Development Model

The intended architecture is modular:

- Hardware Map is the source of truth for physical USB ports, controllers, devices, pins, and hardware groups.
- Function manifests declare the devices they require.
- Basic workflow blocks are generated from hardware devices.
- Advanced functions can use controller firmware and backend handlers, but they must still declare hardware dependencies.
- Compound functions can be built from connected workflow blocks and should become exportable/shareable modules later.
- Firmware flashed to each controller should eventually be generated from the Hardware Map plus every workflow block that needs that controller.

Do not add one-off pin lists or hidden hardware assumptions inside functions. If a function uses a motor, servo, sensor, camera, API service, or future device, declare it through the module/function contract so the UI, backend, firmware, and tests can reason about it.

## License

This repository is licensed under Apache License 2.0 unless a file or module says otherwise. See `LICENSE` and `docs/LICENSE_POLICY.md`.

Future hardware/CAD/electronics packages should carry an explicit open hardware license, with `CERN-OHL-S-2.0` as the preferred default when the goal is to keep hardware improvements open.
