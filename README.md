# Robot Control App

First-step monorepo skeleton for a Raspberry Pi 5 robot-control application.

This repository is intentionally minimal: it gives you a clean React frontend, a FastAPI backend, documentation, and placeholders for firmware work without implementing real robot logic yet.

## Project goals for this step

- Run the full stack locally on a Raspberry Pi 5
- Provide a simple dashboard UI
- Expose backend health and mock robot-state endpoints
- Keep the structure easy to extend into workflow editing, cameras, serial communication, WebSockets, and job execution later

## Repository structure

```text
.
|-- backend/
|-- docs/
|-- firmware/
`-- frontend/
```

## Quick start

### 1. Start the backend

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

Backend runs at `http://127.0.0.1:8000`.

### 2. Start the frontend

Open a second terminal:

On Raspberry Pi OS / Linux:

```bash
cd "/home/robot/robot control/Robot-Code"
./start-frontend.sh
```

On Windows 11:

```powershell
cd "C:\BOB\masters\Thesis\Robot Code"
start-frontend.bat
```

Frontend runs at `http://127.0.0.1:5173`.

### Optional: start both

On Raspberry Pi OS / Linux:

```bash
cd "/home/robot/robot control/Robot-Code"
./start-all.sh
```

On Windows 11:

```powershell
cd "C:\BOB\masters\Thesis\Robot Code"
start-all.bat
```

## Available endpoints

- `GET /health`
- `GET /api/robot/state`
- `POST /api/robot/state/mock-update`

## Architecture notes

- `frontend/` is a small Vite + React + TypeScript app that polls the backend and renders a dashboard.
- `backend/` is a FastAPI service with routers, models, and an in-memory robot-state store.
- `firmware/` is a placeholder for future ESP32 projects and shared protocol definitions.
- `docs/` contains lightweight architecture notes so the project can grow without losing clarity.

## Why this structure

- Easy to run locally without Docker
- Easy to understand for early development
- Keeps frontend, backend, and future firmware concerns separated
- Leaves natural extension points for:
  - workflow editor
  - camera monitoring
  - serial communication with ESP32 boards
  - WebSocket updates
  - background job execution

## Next step ideas

The most natural next increment is to add a small robot command model and a serial-communication abstraction layer on the backend, while keeping everything mocked until hardware integration starts.
