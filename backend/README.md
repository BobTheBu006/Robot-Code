# Backend

FastAPI backend for the local robot-control app.

Read `../docs/ARCHITECTURE_CONTRACTS.md` and `../docs/BACKWARDS_COMPATIBILITY.md` before changing function discovery, hardware map sync, workflow execution, firmware flashing behavior, or persistent data contracts.

## Run locally

On Raspberry Pi OS / Linux:

```bash
cd "/home/robot/robot control/Robot-Code"
./start-backend.sh
```

On Windows 11:

```powershell
cd "C:\BOB\masters\Thesis\Robot Code"
start-backend.bat
```

Or run it directly:

Raspberry Pi OS / Linux:

```bash
cd "/home/robot/robot control/Robot-Code/backend"
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m uvicorn app.main:app --reload
```

Windows 11:

```powershell
cd "C:\BOB\masters\Thesis\Robot Code\backend"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

## Run the tests

Install the development requirements, then run the standard-library test suite:

Raspberry Pi OS / Linux:

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m unittest discover -s tests -t .
```

Windows 11:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

## Endpoints

- `GET /health`
- `GET /api/robot/state`
- `POST /api/robot/state/mock-update`
- `GET /api/camera/status`
- `GET /api/camera/frame`
- `GET /api/camera/stream`
- `GET /api/functions`
- `POST /api/functions/{function_id}/test`
- `POST /api/esp32-builder/workflow-firmware/plan`
- `GET /api/tools/syringe/status`
- `POST /api/tools/syringe/dispense`

## Camera feed

The backend can expose a USB camera to the frontend as an MJPEG stream.

Camera environment variables:

- `CAMERA_DEVICE=0`
- `CAMERA_FRAME_WIDTH=1280`
- `CAMERA_FRAME_HEIGHT=720`
- `CAMERA_FPS=15`

If the camera feed reports that OpenCV is unavailable, reinstall backend dependencies:

```bash
cd "/home/robot/robot control/Robot-Code/backend"
./.venv/bin/python -m pip install -r requirements.txt
```

## Syringe ESP32 control

The backend can send a 7-head syringe dispense command to an ESP32 over serial.

Defaults:

- calibration file: `/home/robot/robot control/syringe control code/calibration.json`
- serial port: first match from `/dev/ttyUSB*` or `/dev/ttyACM*`
- baud rate: `115200`
- command format: `json`

Optional environment variables:

- `SYRINGE_CALIBRATION_FILE`
- `SYRINGE_SERIAL_PORT`
- `SYRINGE_BAUD_RATE`
- `SYRINGE_SERIAL_TIMEOUT_SECONDS`
- `SYRINGE_COMMAND_FORMAT`

Example request:

```bash
curl -X POST http://127.0.0.1:8000/api/tools/syringe/dispense \
  -H "Content-Type: application/json" \
  -d '{"A":150,"B":25,"C":0,"D":100,"E":0,"F":10,"G":75}'
```

## Function discovery

Robot execution blocks are discovered from subfolders in `backend/app/functions/`.

Each function folder must contain:

- `manifest.json`
- `handler.py`
- `requirements.txt`

Example structure:

```text
app/functions/
  dispense/
    manifest.json
    handler.py
    requirements.txt
```

The `GET /api/functions` endpoint scans those folders, validates their manifests, and returns the block metadata the workflow editor uses to build robot-action nodes.

`POST /api/functions/{function_id}/test` loads the function folder's `handler.py` and calls `execute(context, inputs)` in test mode so the workflow editor can preview block behavior without introducing a full execution engine yet.

Function manifest outputs are workflow control-flow paths, not data fields. Normal robot actions should expose a single `next` output with `"type": "flow"`; the Workflow Editor can add a separate `error` output from block settings. Branching blocks such as if/else or loops may expose multiple flow outputs. Handler return values such as status strings, measurements, or raw controller replies should remain in the result payload and should not be listed as graph outputs.

The Workflow Editor separates blocks into three groups:

- Basic blocks: triggers, logic blocks, and hardware-map generated servo/stepper/sensor actions.
- Advanced functions: backend-discovered robot functions such as gantry calibration and syringe dispensing.
- Compound functions: directly connected canvas blocks collapsed through the canvas context menu. Compound functions preserve their external flow outputs and can be expanded back into editable blocks.

Advanced function manifests may declare `hardware_devices`. Each declared motor, servo, or sensor is synchronized into the Hardware Map using stable device IDs and `function_input_key` pin links. The Workflow Editor then generates the matching basic hardware block from the Hardware Map, so a custom function and its basic move/read block point at the same physical USB controller and GPIO pins.

Advanced function manifests may also declare `firmware_requirements`. These identify the ESP32 routines, source files, protocols, and required logical devices that workflow-aware firmware planning collects per controller before flashing. The planner endpoint validates that referenced firmware sources stay inside the selected board workspace and exist before the workflow runner starts flashing boards.

## Mock update example

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/robot/state/mock-update `
  -ContentType "application/json" `
  -Body '{
    "machine_state": "running",
    "current_workflow": "tray_loading",
    "current_step": 4,
    "gantry": { "x": 210, "y": 85, "z": 32 },
    "sensor_values": [],
    "alarms": [
      {
        "code": "low_air",
        "message": "Compressed air pressure below threshold.",
        "severity": "warning",
        "active": true
      }
    ]
  }'
```

## Current design

- `app/api/routes/` contains route definitions
- `app/models/` contains Pydantic models for robot state and updates
- `app/services/` contains robot state, hardware map, function discovery, workflow storage, and ESP32 builder logic

This keeps routing, data contracts, and application logic separate from the start.

For future changes, keep persistent schema updates versioned and covered by migration tests. See `../docs/BACKWARDS_COMPATIBILITY.md`.
