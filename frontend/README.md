# Frontend

Vite + React + TypeScript dashboard for the local robot-control app.

## Run locally

```powershell
cd "C:\BOB\masters\Thesis\Robot Code"
start-frontend.bat
```

Or run it directly:

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

## Available scripts

- `npm run dev`
- `npm run build`
- `npm run preview`

## Current features

- backend connection status
- robot state polling every second
- robot state card with loading, success, and error feedback
- camera placeholder panel
- workflow editor placeholder panel
