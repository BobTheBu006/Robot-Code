# Agent Operating Guide

This file is the first stop for AI coding agents working in this repository.

## Mission

Build a modular, open-source robotic lab automation platform that can compete with closed systems such as Opentrons and Tecan-style instruments while staying cheap, repairable, and extensible for underfunded research labs and universities.

The system should let users describe physical hardware, connect it to workflow blocks, and reuse or share modules without breaking older workflows.

## Read These Before Editing

1. `docs/PROJECT_STATUS.md`
2. `docs/ARCHITECTURE_CONTRACTS.md`
3. `docs/BACKWARDS_COMPATIBILITY.md`
4. `docs/FEATURE_ROADMAP.md`
5. `docs/TODO.md`

If you are adding or changing a function, also read:

- `functions/esp 32 code/README.md`
- `backend/README.md`
- `docs/templates/function-manifest.template.json`

## What Counts As A Meaningful Change

Update `docs/PROJECT_STATUS.md` when a change affects any of these:

- robot capabilities visible to the operator
- workflow editor behavior
- hardware map behavior or schema
- function manifest schema
- firmware build, flash, or serial protocol behavior
- module/package boundaries
- compatibility promises or migrations
- setup, run, or test commands

Small CSS-only tweaks, copy edits, local refactors, and bug fixes that do not change behavior usually do not need a status update. If the next agent would be confused without knowing it, update the status file.

Update `docs/ARCHITECTURE_CONTRACTS.md` only when the stable contract changes. Update `docs/BACKWARDS_COMPATIBILITY.md` when saved data, migrations, or public version promises change. Put feature-sized deferred work in `docs/FEATURE_ROADMAP.md` and lower-level architecture notes in `docs/TODO.md` instead of scattering them through code comments.

## Development Rules

- Hardware Map is the source of truth for USB ports, controllers, devices, pins, and hardware groups.
- Functions must declare hardware dependencies instead of hiding device or pin assumptions in code.
- Normal robot-action blocks should expose one `next` flow output. Error paths are handled by block settings. Branching logic blocks may expose multiple flow outputs.
- Data returned by a function belongs in the result payload, not in graph outputs.
- Compound functions expose only the unconnected non-error flow outputs of their internal blocks.
- Saved workflows and hardware maps should continue loading. If something is missing, show a broken placeholder with a suggested fix instead of failing silently.
- Firmware for a workflow should be assembled per controller from every block that needs that controller, flashed once before the workflow run, and then reused by multiple blocks during that run.
- Do not split a module into another repository unless it can be built, tested, versioned, and imported independently with a documented contract.

## Common Verification

Frontend:

```powershell
cd "C:\BOB\masters\Thesis\Robot Code\frontend"
npm.cmd run build
```

Backend import smoke test:

```powershell
cd "C:\BOB\masters\Thesis\Robot Code\backend"
.\.venv\Scripts\python.exe -c "from app.main import app; print(app.title)"
```

Backend compatibility tests:

```powershell
cd "C:\BOB\masters\Thesis\Robot Code"
backend\.venv\Scripts\python.exe -m unittest discover -s backend\tests
```

Docs only:

```powershell
cd "C:\BOB\masters\Thesis\Robot Code"
git diff --check
```

After running the frontend build, restore `frontend/tsconfig.tsbuildinfo` if the build updates it and that change is unrelated to the requested work.

## Adding A New Robot Function

1. Define the function manifest.
2. Declare every required hardware device in `hardware_devices`.
3. Reference existing logical devices when possible instead of inventing duplicates.
4. Add or reuse basic blocks for motors, servos, sensors, or other primitive hardware operations.
5. Add backend handler code only for behavior that cannot be represented by basic/compound blocks.
6. Add firmware routine requirements when the function needs controller code.
7. Add a test or fixture that proves old saved data still loads.
8. Update `docs/PROJECT_STATUS.md` if the function changes platform capability.

## Future Module Direction

Community modules should eventually be importable from local folders or Git repositories. A module may contain:

- function manifests
- hardware templates
- firmware source or firmware fragments
- backend handlers
- frontend panels or inspectors
- example workflows
- 3D/CAD models
- simulation hooks
- documentation and tests

Until that importer exists, keep modules in this repository and preserve the same contract shape.
