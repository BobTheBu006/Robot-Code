# Frontend

Vite + React + TypeScript dashboard for the local robot-control app.

Requires Node.js 20+ with `npm` available on your `PATH`.

Read `../AGENTS.md`, `../docs/PROJECT_STATUS.md`, and `../docs/ARCHITECTURE_CONTRACTS.md` before changing workflow, hardware map, or block behavior.

## Run locally

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

Or run it directly:

Raspberry Pi OS / Linux:

```bash
cd "/home/robot/robot control/Robot-Code/frontend"
cp .env.example .env
npm install
npm run dev
```

Windows 11:

```powershell
cd "C:\BOB\masters\Thesis\Robot Code\frontend"
copy .env.example .env
npm.cmd install
npm.cmd run dev
```

## Environment

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Once the backend camera route is enabled, the dashboard camera panel will pull its live stream from `/api/camera/stream`.

## Available scripts

- `npm run dev`
- `npm run build`
- `npm run preview`

## Current features

- backend connection status
- robot state polling every second
- robot state card with loading, success, and error feedback
- camera status and feed placeholder/live stream support
- Hardware Map editor for Raspberry Pi, ESP32 controllers, devices, pins, and hardware groups
- Workflow Editor with basic, advanced, and compound function blocks
- hardware-map generated basic blocks for steppers, servos, and sensors
- per-block inspector editing and function test actions
- palette block hide/unhide behavior
- pre-run ESP32 flashing for boards used by the workflow
