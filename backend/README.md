# Backend

FastAPI backend for the local robot-control app.

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

## Endpoints

- `GET /health`
- `GET /api/robot/state`
- `POST /api/robot/state/mock-update`
- `GET /api/camera/status`
- `GET /api/camera/frame`
- `GET /api/camera/stream`
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
    "sensor_values": [
      { "name": "vacuum_pressure", "value": -51.2, "unit": "kPa" },
      { "name": "motor_driver_temp", "value": 41.6, "unit": "C" }
    ],
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
- `app/services/` contains the in-memory robot state store and update logic

This keeps routing, data contracts, and application logic separate from the start.
