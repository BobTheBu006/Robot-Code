# Frontend

Vite + React + TypeScript dashboard for the local robot-control app.

Requires Node.js 20+ with `npm` available on your `PATH`.

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
- first-pass workflow editor with block palette, canvas, JSON save/load, backend-discovered robot action nodes, per-block inspector editing, and block test actions
