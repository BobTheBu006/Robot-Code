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
