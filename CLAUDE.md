# Robot control — agent context

A lab-automation robot, running on the Raspberry Pi it controls. **This box is
the machine.** Commands here move real hardware.

Longer references live in `docs/`: `HANDOFF.md` (current state and history),
`BACKEND_ARCHITECTURE_V2.md` (design and defect map), `CLOSED_LOOP_XY_PLAN.md`
(the closed-loop XY work in progress). This file is the orientation.

---

## What the machine is

A CoreXY gantry with a tool-changer rack, a dual Z axis, a 7-syringe pump and
5 peristaltic pumps. A browser UI edits a block-based workflow; the Pi
coordinates; ESP32 controllers do low-level motor work.

## Who owns what

| Controller | Owns |
| --- | --- |
| **Raspberry Pi GPIO** | CoreXY A/B motors, XY limit switches, all four Z limit switches, access-door switch, gantry driver enable |
| **`controller-ykkl80`** | Both Z motors, 5 peristaltic pumps, their shared driver enable |
| **`controller-x83xnc`** | 7-syringe pump |
| **`xy-closed-loop`** | Not built. Disabled in the Hardware Map. Planned home for closed-loop XY. |

The Z axis is deliberately **split**: motors on the ESP32, limit switches on
the Pi (`hybrid_z_axis.py`). The Pi watches the switch and sends `STOP` over
serial the instant it trips.

## The rules that matter

**`hardware-map.json` is the source of truth for pins.** Not manifests, not
code. Handlers resolve pins from it at run time via
`hardware_map_service.apply_function_defaults`, which *overwrites* whatever a
manifest declares. Manifest pin defaults are frequently stale and reading them
will mislead you.

**Never edit pins in `hardware-map.json` without asking.** Standing owner
instruction.

**Never run motion blocks without explicit permission** — anything that moves
the gantry, Z, or dispenses. Ask first, every time, even to verify a fix.

**Run tests with `ROBOT_GPIO_SIMULATE=1`.** Without it the suite drives real
GPIO on this machine. Two tests pin the flag *off* deliberately because they
exercise the executed path against an injected fake backend.

```bash
cd backend && ROBOT_GPIO_SIMULATE=1 ./.venv/bin/python -m unittest discover -s tests -t .
```

333 tests, stdlib `unittest`, no pytest.

## The pogo connector (dynamic tools)

The toolhead's spring-pin connector carries Pi GPIO 2/3/14/15 (SDA, SCL, TXD,
RXD) and the USB port the 7-syringe pump uses. It is `connectors` in the
Hardware Map. **Only groups attach to it**: each group is one tool, with a
per-pin mode (I²C / UART / GPIO / unused), an optional USB controller, a
verification method (ESP32 fingerprint, USB serial, TXD–RXD loopback, or none)
and an optional rack slot. `services/pogo_connector.py` activates one group at
a time: verify first, then set pin functions with `pinctrl`, then record it in
`connector-state.json`. Devices in any other tool group are unavailable to
functions, with a reason. Pick-up activates the slot's group (or empties the
connector for a tool with no connector); drop and Disconnect Tool park the pins.
A failed verification leaves the connector empty — never the old tool.

## Safety architecture

- **One safety authority** (`core/safety.py`): a single `threading.Event`
  shared by reference with every motion driver. Services register as
  `StoppableActor`s; the flag is set before any actor is called.
- **Access door** on Pi GPIO 13 gates *runs*, not all motion — a single block
  test with the door open is allowed, because that is how the machine gets
  brought up with someone standing there.
- **Physical state** (`physical_state.py`): facts the machine cannot sense,
  like which tool is on the head. An interrupted tool change marks it
  *uncertain* and refuses to move until a person confirms — guessing "empty"
  is what drives a loaded head into the rack. The UI raises a dialog for this.
- **Position survives an abort.** Drivers adopt the steps actually taken, not
  the steps commanded. An E-Stop must never cost the calibration.
- **Motors power down when idle** (`motor_power.py`): enable, settle, move,
  then a linger timer rather than an immediate cut, so consecutive blocks do
  not power-cycle the drivers. Polarity is **per domain** — the CoreXY TB6600s
  and the TB67S109s on the Z/pump board disagree, and this was measured on the
  machine, not read off a datasheet. Do not "correct" it.

## The workflow engine

`backend/app/engine/` — `plan.py` compiles and validates the graph,
`conditions.py` evaluates `if`/`while` conditions (an AST walk over a small
allowed grammar, deliberately **not** `eval`), `scheduler.py` walks the plan,
`journal.py` records what ran.

**The engine decides, the browser executes.** The browser opens a run, is
handed the blocks that are due, runs them, reports back. Control flow —
which branch, how many loop iterations, who waits for whom — is decided
backend-side where it is tested.

## Gotchas that have cost real time

- **Some manifests are generated** from ESP32 workspace blueprints
  (`move_gantry_xy`, `move_gantry_circle`, `dispense`,
  `7_syringe_dispenser_slow_and_good`). Editing those manifests directly does
  nothing — the next regeneration overwrites it. Edit the blueprint, or put
  the value in the Hardware Map.
- **Placed workflow blocks used to freeze their definition.** Fixed: they now
  reconcile against the live catalog. If a block seems to ignore a change you
  made, check that reconciliation still runs.
- **Test the entry point, not the helper.** A `NameError` once reached the
  machine with every test green, because the tests exercised `run_sequence`
  while the bug was in `pickup()`.
- **The step rate has a ceiling** set by the step pulse width
  (`ROBOT_GPIO_STEP_PULSE_SECONDS`, currently 15 µs → ~2500 RPM). Requests
  above it are silently clamped; moves now report requested vs achieved.
- **Python bit-bangs the CoreXY steps.** That, not the electrical ceiling, is
  usually the real speed limit.

## Working style the owner expects

Verify against the machine rather than reasoning about it — read the GPIO,
read the reply, re-run the build. Several bugs this project has hit looked
exactly like something else (an enable polarity that was really a stale state
flag; a "backwards" motor that was really a released pin). Say plainly what is
verified and what is not.
