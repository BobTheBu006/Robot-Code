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
| **Raspberry Pi GPIO** | All four Z limit switches, access-door switch, pogo connector and gripper servos |
| **`controller-ykkl80`** | Both Z motors, 5 peristaltic pumps, their shared driver enable |
| **`controller-x83xnc`** | 7-syringe pump |
| **`xy-closed-loop`** | CoreXY A/B motors, shared enable, X-min/X-max/Y-min limits. Open-loop for now; encoder feedback disabled. |

XY migration (2026-10-06, board replaced 2026-10-27): USB serial
`2ebcd7b203bdf0119170167148e9de0f`.
Motor A STEP/DIR = 25/26; B = 27/14; active-low shared enable = 13;
X-min/X-max/Y-min = 32/33/4; no Y-max (GPIO 16/17 read ~2.3 V unloaded on
the first board - do not use them). The builder generates the boot pin
header from the Hardware Map. Do not use the old generic ESP32 pin defaults.
Encoders: AS5600 A on SDA 21/SCL 22, B on SDA 19/SCL 18, 100 kHz I2C, enabled
in the Hardware Map (2026-10-27): Move XY fills their pins from the map and
reports following error. Measured 1600 steps/rev (256 counts per 100 steps);
encoder A counts against its motor - SET ENCODER SCALE 1600 1 0. Follow limit 80 counts (normal lag is ~2 full
steps = ~41 counts; one slip is 4 full steps = ~82). PID gains
are 0 (monitoring only) until tuned. A fresh ESP32 XY calibration is
required after the migration. Verified 2026-10-27: +X jog of 20 cm via
alternating TEST MOTOR A/B (both DIR 1) moved the carriage the right way. The Pi motion implementation remains available
as a fallback if the hardware is rewired and the map changed back.

The **Teach Tool Positions** block records rack slots by hand: while it
runs, the XY motors are off (firmware TEACH mode refuses anything that could
energise them), the editor's dialog shows the encoder-derived position, Save
stores a slot, Finish ends the teach - the gantry adopts the pushed-to
position, so calibration survives - and writes tool_N_x/y_cm into the
toolhead defaults. Endpoints: POST /api/robot/xy-teach/{start,position,end}.

**Deepwells** (`services/deepwell_positions.py`, `deepwell-positions.json`):
24 wells on the right Z platform, columns A-D along X, rows 1-6 along Y.
**Teach Deepwell Positions** uses the same hand-teach dialog: 3 corners (A1,
A6, D1) span the grid, or individual wells override it; a new corner teach
drops old overrides. **Deepwell Handling** takes/puts back a lid or a whole
plate: it runs Move Z / Gripper / Move XY / Pick Up through
`function_discovery_service.test_function` (right Z lifts at the well, left Z
at the target), picks up the gripper if the head is empty, and refuses to
start while a grab height is not above the travel height (the defaults).

The **Gripper** block already exists: Open/Close, slot 6, left Pi GPIO3 (SCL),
right Pi GPIO2 (SDA), closed -90/+90 degrees, open +30/-30 degrees. It requires
the gripper tool to be connected, ramps both servos, and holds until release. Pulses come from the Pi 5's
PIO block (`pwm-pio` overlay) - hardware-timed, no jitter; lgpio software
pulses jittered and are only the fallback. Using it detaches I2C from GPIO 2/3;
park (on drop) removes the overlays and reattaches I2C.

The Z axis is deliberately **split**: motors on the ESP32, limit switches on
the Pi (`hybrid_z_axis.py`). The Pi watches the switch and sends `STOP` over
serial the instant it trips. The stop names its source: `STOP Z_LEFT_MIN` (etc.) holds only
that motor and the other carries on, plain `STOP` stops everything. That
lets Calibrate Z home both sides at once; the Pi checks `FEATURES?` first,
because older firmware ignores a sourced stop mid-move. Move Z watches the switch
each moving side heads toward: a trip stops that motor and, unless the side
was going to the bottom, fails the move and drops that side's calibration.

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

463 tests, stdlib `unittest`, no pytest.

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
**Idle GPIO 2/3 are driven LOW**, never left as inputs: the Pi's 1.8 kOhm
pull-ups make a floating pin a constant HIGH, which a servo reads as "drive to
the end" - docking the gripper that way swung a claw into the next tool. A
connected gripper immediately holds closed; the backend re-applies the
connector state at start-up (boot leaves 2/3 with I2C, idle HIGH).

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

**Paths run side by side unless they share hardware.** A path is a straight
run of blocks (each feeding exactly one block nothing else feeds). When its
first block is due it claims the hardware of the whole path - an ESP32 board,
a Pi device, `toolhead` - and a path needing claimed hardware waits until the
holder's whole path is done. Hardware comes from the manifests via the
Hardware Map (`run_sessions._hardware_resolver`); a function block with none
listed claims everything and runs alone. The browser starts every due block
at once and starts new ones as each result comes back.

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
- The Pi fallback bit-bangs CoreXY steps in Python. The active XY controller
  now generates steps on the dedicated ESP32.

## Working style the owner expects

Verify against the machine rather than reasoning about it — read the GPIO,
read the reply, re-run the build. Several bugs this project has hit looked
exactly like something else (an enable polarity that was really a stale state
flag; a "backwards" motor that was really a released pin). Say plainly what is
verified and what is not.
