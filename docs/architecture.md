# Architecture Overview

## Purpose

This repository is the starting point for a local robot-control application running on a Raspberry Pi 5.

The Pi is the high-level coordinator. Later, it will:

- send commands to multiple ESP32 boards
- receive sensor and status updates
- expose operator controls through a local web UI

## Current split

### `frontend/`

React + TypeScript dashboard for:

- connection status
- robot state monitoring
- future workflow editing
- future camera views

### `backend/`

FastAPI service for:

- health checks
- mock robot-state APIs
- future serial communication
- future WebSockets
- future workflow/job orchestration

### `firmware/`

Placeholder for future ESP32 firmware projects, shared protocols, and board-specific notes.

## Design decisions

- Keep API models explicit with Pydantic so frontend/backend contracts stay clear.
- Keep backend routes thin and move robot state creation into a service module.
- Keep frontend components small and reusable without introducing a UI framework yet.
- Avoid Docker, auth, databases, and hardware code until the basic workflow is stable.

## Planned growth path

1. Serial communication abstraction for ESP32 boards
2. Command queue / job execution engine
3. Workflow editor data model
4. WebSocket live updates
5. Camera streaming integration
6. Persistent storage if needed
