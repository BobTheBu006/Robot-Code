# Backend Architecture v2

Target structure for the control backend. This document is the agreed plan; it
supersedes nothing in `ARCHITECTURE_CONTRACTS.md` — it is how those contracts
actually get implemented.

## Decisions

| Decision | Choice |
| --- | --- |
| Blast radius | Keep the hardware drivers, replace the orchestration above them |
| Firmware | Identity + fingerprint handshake and preflight now; code generation next |
| Parallel branches | Genuinely concurrent, gated by logical resource locks |
| Verification | Simulation-first; no hardware available during development |

### Why the drivers stay

`raspberry_gantry.py`, `gantry_controller.py`, `hybrid_z_axis.py` and
`syringe_controller.py` are roughly 180 KB of hardware-tuned code: CoreXY step
timing, trapezoidal acceleration, limit probing with fast-touch/backoff/slow-touch,
partial-travel adoption after an aborted move. That behaviour was tuned against
the physical machine and cannot be re-derived without it.

Everything above them — scheduling, safety arbitration, controller identity,
function discovery, packaging — is what actually misbehaves, and all of it is
testable without hardware. So v2 rebuilds the orchestration layer and wraps the
drivers behind explicit ports.

## Root causes being fixed

These are the specific defects v2 exists to remove. Each is referenced by the
phase that closes it.

| # | Defect | Where | Phase |
| --- | --- | --- | --- |
| 1 | No backend execution engine; the runner is in the browser | `WorkflowEditorCard.tsx` | 3 |
| 2 | `ok=True` hardcoded, so handler failure reads as success | `function_discovery.py` `test_function` | 3 |
| 3 | Run order is a DFS over edge-array order | `collectRunAllOrder` | 3 |
| 4 | Joins fire on the first arriving branch | `collectRunAllOrder` | 3 |
| 5 | `if`/`while`/`for` run every successor; loops never loop | `collectRunAllOrder` | 3 |
| 6 | `error` edges traversed during healthy runs | `collectRunAllOrder` | 3 |
| 7 | Only 5 hardcoded block ids receive upstream JSON | `blockUsesUpstreamInput` | 3 |
| 8 | `result.ok` never checked; a failed block does not stop the run | `runOrderedWorkflowNodes` | 3 |
| 9 | `failureMode` / `retryCount` are edited but never consumed | workflow settings | 3 |
| 10 | Disabled hardware yields `ok:true`, run continues | `getDisabledHardwareReason` | 4 |
| 11 | Five independent E-Stop latches; `/rearm` clears two | `emergency_stop.py` | 1a |
| 12 | Every block run silently un-latches E-Stop | `startNewActivity` | 1a, 5 |
| 13 | Toolhead state is written only on success, then forced to `None` | `toolhead.py`, `emergency_stop.py` | 1b |
| 14 | `cancel` targets a freshly re-imported module, not the running one | `_load_handler_module` | 3 |
| 15 | Two controller-ID namespaces; unmatched boards silently skip flashing | `esp32_builder.py` | 2 |
| 16 | Firmware plan is computed then discarded; static `main.ino` flashed | `flash_firmware` | 2 (partial), later (full) |
| 17 | `GET /api/functions` rewrites the hardware map mid-run | `function_discovery.discover` | 3 |
| 18 | POSIX-only `/tmp` and `killpg` | `esp32_builder.py` | 2 |
| 19 | Workflows embed frozen block definitions (820 KB files) | workflow JSON | 5 |
| 20 | `hardware-map.json` has no `schema_version` | `hardware_map.py` | 2 |

## Target layout

```text
backend/app/
  core/
    safety.py           SafetyController: the single motion latch
    config.py
    env_file.py
  engine/
    graph.py            workflow JSON -> validated ExecutionGraph
    plan.py             ExecutionGraph -> ExecutionPlan (hardware + firmware resolved)
    scheduler.py        ready-set scheduling, join barriers, loop scopes
    resources.py        logical resource derivation + ordered lock acquisition
    runtime.py          RunContext handed to handlers
    runs.py             run store, journal, event stream
  controllers/
    registry.py         controller identity, USB-serial binding, port resolution
    fingerprint.py      firmware bundle hashing
    handshake.py        ID? / PONG protocol, preflight compare
    transport.py        SerialTransport port + SimulatedTransport
  packages/
    <package_id>/
      package.json      shared device roles, naming, resources
      functions/<function_id>/{manifest.json,handler.py}
  services/            (existing drivers, wrapped not rewritten)
  api/routes/
```

## The pieces

### 1. Safety is one authority

`SafetyController` is a process singleton owning a single latch:

```text
armed -> stopping -> latched -> recovering -> armed
```

Everything that can produce motion registers as a `StoppableActor`
(Pi GPIO service, each open serial session, each flash subprocess). E-Stop sets
the latch, then fans out `stop()` to every registered actor. Every motion entry
point consults exactly one flag.

Rules:

- Clearing the latch is an explicit operator action. Starting new work must
  never imply it. This removes the auto-rearm that made E-Stop advisory.
- `GET /api/safety` exposes latch state, which actors reported, and what
  physical state became uncertain, so the UI can show it and refuse to run.
- Rearm is refused while any physical state is still `uncertain` and
  unconfirmed.

### 2. Physical state carries certainty

Physical facts are three-valued, not two-valued. `PhysicalStateStore` records
each fact as `{value, certainty: known|uncertain, reason, updated_at}` and is
written as **intent before motion**, then confirmed after:

```text
before pickup:  {held: 3, certainty: uncertain, phase: "engaging"}
after success:  {held: 3, certainty: known}
after E-Stop:   {held: 3, certainty: uncertain, reason: "estop during engage"}
```

An E-Stop therefore no longer claims the head is empty. The next `pickup`
refuses until the operator confirms what is physically on the gantry, instead of
driving a loaded head into the rack. Same treatment for gantry calibration and
Z position.

### 3. Controller identity is the Hardware Map ID

One namespace. The Hardware Map's `controller-*` id is the only controller
identity; it is bound to the USB descriptor serial number. The port is a runtime
lookup, never an identity. `_board_id_from_port` is deleted and the existing
`esp32 ttyUSB0` / `esp32 ttyUSB1` / `esp32 controller-ykkl80` workspaces are
migrated to `firmware/controllers/<controller_id>/`.

### 4. Firmware fingerprint is the ping

A controller's expected firmware is hashed into a `fingerprint` over the
canonicalised routine set, the resolved pin table, and the source contents. The
firmware answers `ID?` with:

```json
{"controller_id": "...", "fingerprint": "...", "protocol": 2, "routines": ["..."]}
```

That one reply is the liveness check, the identity check, and the "is the right
code actually on it" check. Preflight resolves each controller by serial number,
asks `ID?`, compares, and **flashes only on mismatch** — so flashing becomes
rare instead of happening before every run. A controller that answers with the
wrong `controller_id` is a hard error, never a silent warning.

Code generation (per-controller `generated_config.h` + `generated_routines.h`
emitted from the Hardware Map, with cross-controller routines fanned out to
every controller owning a required device) is the next pass. The fingerprint
schema is designed now so that generation slots in without changing the
protocol.

### 5. The engine executes a graph as a graph

Compile before moving. `ExecutionPlan` is built and validated up front:
hardware resolved, firmware preflighted, cycles outside loop scopes rejected,
unreachable nodes reported, joins identified. Blocking errors surface before
anything moves rather than mid-motion.

Then schedule:

- A node is ready when every **activated** incoming flow edge has delivered.
- Control blocks activate only the edge they chose, so `if` runs one branch.
- Fan-out spawns concurrent tasks; fan-in is a real join barrier.
- `while` / `for` / `loop_over` are re-entrant scopes with an iteration counter
  and a max-iteration guard.
- Every step receives `{"$in": <merged upstream>, "$run": {...},
  "$blocks": {node_id: result}}` and uses the parts it cares about.
- Per-node policy is honoured: `timeout`, `retry(n, backoff)`,
  `on_error: stop | continue | error_path`.

### 6. Resource locks make parallelism safe

Each function declares the logical resources it needs, derived from its devices:
`gantry.xy`, `z.left`, `syringe.head_b`, `controller:<id>:serial`. The scheduler
acquires them in a fixed global order before running a node, so:

- two branches that both want `gantry.xy` serialise automatically
- a Z move and a syringe dispense genuinely overlap
- deadlock is impossible (total order over resource ids)

This is what makes "a split runs in parallel" a safe statement about a machine
with one physical gantry.

### 7. Packages own hardware families

A package owns the shared device set, the pin/variable naming scheme, and the
shared inputs for one hardware assembly:

| Package | Functions |
| --- | --- |
| `gantry_xy` | calibrate, move_xy, move_circle, test_repeatability |
| `z_axis` | calibrate, move |
| `toolchanger` | pickup, drop |
| `syringe_7` | dispense, prime, wash, calibrate |
| `controller` | connect, disconnect, test_motor |

Device **roles** carry `required: true|false` and a `min_required` count — the
granularity hook. `syringe_7` declares `head_a..head_g` all optional with
`min_required: 1`, so disabling head B removes only head B. `z_axis` declares
`z_left`/`z_right` optional with `min_required: 1`, so a disabled left Z leaves
the right one movable. Degradation is reported in the result payload and in the
preflight report; it never silently reads as full success.

### 8. Run API

```text
POST   /api/runs                     -> run_id      (workflow, mode: run|dry_run)
GET    /api/runs/{id}                -> snapshot    (for reconnect)
GET    /api/runs/{id}/events         -> SSE         (node/phase/log/safety events)
POST   /api/runs/{id}/cancel
POST   /api/runs/{id}/pause | /resume
POST   /api/runs/{id}/resume-from/{node_id}
GET    /api/safety                   -> latch state + uncertain physical state
POST   /api/safety/stop | /rearm
POST   /api/safety/confirm-physical-state
```

Runs journal to append-only JSONL, so a backend restart can still say what
happened and where it stopped.

## Getting back on track

The "if there is a problem, get back on track" requirement is met by four
mechanisms, in order of preference:

1. **Preflight** — the plan refuses to start when hardware, firmware or graph
   structure is wrong, and says exactly what to fix.
2. **Per-node policy** — timeout, retry with backoff, and an explicit error path
   handle the recoverable cases without operator involvement.
3. **Certainty tracking** — anything a fault made unknowable is marked
   uncertain rather than guessed, and blocks resume until confirmed.
4. **Journal + resume-from** — a stopped run can be inspected and restarted from
   a chosen node instead of from the beginning.

## Phases

| Phase | Content | Closes |
| --- | --- | --- |
| 1a | SafetyController, `GET /api/safety`, explicit rearm | 11, 12 |
| 1b | PhysicalStateStore with certainty; toolhead fix | 13 |
| 1c | Simulation transport (simulated ports + firmware responder) | — |
| 2 | Controller registry, fingerprint handshake, preflight, schema_version | 15, 18, 20; 16 partially |
| 3 | Run engine, resource locks, run API + SSE, cached handlers | 1–9, 14, 17 |
| 4 | Function packages, role-level degradation | 10 |
| 5 | Frontend becomes a viewer; workflows stop embedding definitions | 12, 19 |

Simulation is Phase 1c rather than last because with no hardware on the bench it
is the prerequisite for verifying every phase after it.
