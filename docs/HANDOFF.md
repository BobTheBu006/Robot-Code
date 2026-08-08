# Handoff: backend rebuild, continuing on the Raspberry Pi

Written for the next AI agent (or human) picking this up **on the Pi, with the
robot attached**. The previous work was done on a Windows development machine
with no hardware, which is the single most important thing to know: several
things are implemented and unit-tested but have **never touched a real board**.

Read `docs/BACKEND_ARCHITECTURE_V2.md` first — it is the agreed design and the
defect-to-phase map. This file is the current state and what to do next.

---

## 1. The aim

A local-first, modular lab-robot platform. A Raspberry Pi coordinates; a
browser UI edits hardware maps and workflows; ESP32 controllers run low-level
motor/sensor code.

The rebuild exists because the orchestration layer was unreliable in three ways
the operator hit constantly:

1. **Workflows ran in an unpredictable order.** Blocks fired in the order the
   wires happened to be drawn, joins fired early, `if` ran both branches, loops
   never looped, and a failed block did not stop the run.
2. **E-Stop was advisory.** Five services each owned a private stop flag,
   `/rearm` cleared two of them, and starting any new work silently cleared the
   latch. After a stop mid tool-change the machine claimed the head was empty
   while a tool was physically on it.
3. **Flashing hit the wrong board, or no board.** Two incompatible controller-ID
   namespaces meant a controller the plan could not resolve was silently
   downgraded to "externally programmed" and never flashed — the run then
   proceeded against whatever firmware happened to be on it.

The agreed decisions:

| Decision | Choice |
| --- | --- |
| Blast radius | Keep the hardware drivers, replace the orchestration above them |
| Firmware | Identity + fingerprint handshake and preflight now; code generation next |
| Parallel branches | Genuinely concurrent, gated by logical resource locks |
| Verification | Simulation-first; hardware was unavailable during development |

**Why the drivers were kept:** `raspberry_gantry.py`, `gantry_controller.py`,
`hybrid_z_axis.py` and `syringe_controller.py` are ~180 KB of hardware-tuned
code (CoreXY step timing, trapezoidal accel, fast-touch/backoff/slow-touch limit
probing, partial-travel adoption after an aborted move). That behaviour was
tuned against the physical machine and cannot be re-derived from a desk. Do not
rewrite them. Wrap them.

---

## 2. STOP: read this before flashing anything

**All three ESP32 workspaces record the same USB serial number.**

```
serial 58d72d4c84bcf01191f2167148e9de0f
    board_id=ttyUSB0             usb location=1-2
    board_id=ttyUSB1             usb location=3-2
    board_id=controller-ykkl80   usb location=(not recorded)
```

These are cheap CP2102N bridges that were never given unique serials at the
factory. This matters enormously, because `Esp32BuilderService._resolve_flash_port`
deliberately prefers the USB serial number over the port name, on the reasoning
that the serial identifies the physical chip. **On this hardware that reasoning
is false.** Every workspace resolves to whichever board currently enumerates
with that serial, so a flash aimed at the syringe controller can land on the
Z-axis controller.

This is very likely the concrete cause of "many problems with flashing".

Consequences for the design:

- USB serial number **cannot** be the controller identity here.
- The only fields that distinguish the two boards are the USB topology
  locations (`1-2` vs `3-2`), which are stable only while the cables stay in
  the same physical ports.
- Therefore **firmware-reported identity (`ID?`) is the only trustworthy
  identity**, which is exactly what has been built — but it has a bootstrap
  problem: a board must be flashed once before it can say who it is.

**Safe bootstrap procedure, to be done by hand the first time:**

1. Unplug both ESP32s.
2. Plug in **one** board only.
3. Confirm exactly one port enumerates: `ls -l /dev/ttyUSB*`.
4. Flash it with the workspace you intend for that physical board.
5. Verify: `python3 -c "import serial,time; p=serial.Serial('/dev/ttyUSB0',115200,timeout=2); time.sleep(2); p.write(b'ID?\n'); print(p.readline())"`
   — it must report the controller id you expect.
6. Unplug it, plug in the other, repeat.
7. Only then plug both in and let preflight verify them.

Do not skip this. Automating it before the boards can identify themselves means
guessing which board is which, and guessing wrong overwrites a working
controller.

Longer term, pick one: reprogram the CP2102N serials to be unique (Silicon Labs
`cp210x` utilities), or record the USB location as a tiebreaker in the Hardware
Map, or accept `ID?` as the sole authority after a one-time manual bring-up.
This is a judgement call for the project owner — **ask, do not decide it
silently.**

---

## 3. The identity mess, exactly as it stands

Four different names exist for what appear to be two physical controllers.

**`hardware-map.json` boards:**

| id | usb_port | enabled | label |
| --- | --- | --- | --- |
| `controller-x83xnc` | `/dev/ttyUSB0` | **false** | 7 syringe pump controller |
| `ttyUSB1` | `/dev/ttyUSB1` | true | Double Z axis and pumps |

**Workspace directories** under `functions/esp 32 code/`:
`esp32 ttyUSB0`, `esp32 ttyUSB1`, `esp32 controller-ykkl80`.

**Function manifests** reference: `ttyUSB0`, `ttyUSB1`, `controller-ykkl80`.

Cross-referencing:

- `controller-ykkl80` is referenced by `calibrate_z` and `move_z` manifests and
  by `workflows/active-workflow.json`, but **no board with that id exists in the
  Hardware Map**. The Z motors are on board `ttyUSB1`.
- `controller-x83xnc` (the syringe controller, and the only board carrying the
  seven syringe-head devices) has **no workspace directory at all**, so
  `plan_workflow_firmware` cannot resolve it and warns it "has no firmware
  workspace; treating it as externally programmed". It is then excluded from the
  flash list.
- `dispense` declares `builder_board_id: "ttyUSB1"` but its devices sit on
  `ttyUSB0` — internally inconsistent, almost certainly wrong.

**Device placement** (19 devices):

- `raspberry-pi` (9): CoreXY A/B motors, X min/max, Y min limit switches, all
  four Z limit switches. The XY gantry and every limit switch is driven from Pi
  GPIO, not from an ESP32.
- `ttyUSB1` (2): `z-left-motor`, `z-right-motor`.
- `controller-x83xnc` (7): `syringe-head-a` … `syringe-head-g`, all disabled.
- unconnected (1): `y-max-limit-switch`, disabled.

Note the shape this implies: the Z axis is genuinely **cross-controller** —
motors on an ESP32, limit switches on Pi GPIO. That is the case the architecture
has to handle properly, and it is why `hybrid_z_axis.py` exists.

**On `function_assignments`:** there are 54 rows and **all 54 are identity
mappings** (`device_id == hardware_device_id`). The indirection currently buys
nothing while adding a second place that can go stale. Collapse it to
non-identity overrides only — but keep the field, since real overrides are the
point of Contract 1.

---

## 4. Where the work stands

### Done and unit-tested (74 tests pass)

**Phase 1a — one safety authority.** `backend/app/core/safety.py`.
A single `threading.Event` shared *by reference* with every motion driver, so a
hot stepping loop and an HTTP request consult the same boolean. The flag is set
before any actor is called, so a blocking serial write cannot delay an abort.
All five services self-register as `StoppableActor`s at import. New routes:
`GET /api/safety`, `POST /api/safety/stop|rearm|confirm-physical-state`.
`/api/emergency-stop` remains as a shim for the current frontend.

**Behaviour change to be aware of:** `rearm` now *refuses* while any physical
fact is unconfirmed. The frontend calls it before every block test, which is how
a pressed E-Stop used to get silently cleared.

**Phase 1b — physical state with certainty.** `backend/app/services/physical_state.py`.
Facts are three-valued (known / uncertain / absent) and written as **intent
before motion**, confirmed after. A stop mid-pickup leaves
`{held: 2, certainty: uncertain}` — the conservative belief — instead of the old
confident "empty". A stop while *idle* correctly leaves a settled tool known.
The legacy `toolhead-state.json` migrates in as uncertain. New file:
`physical-state.json` (gitignored).

**Phase 1c — thin simulation.** `backend/app/controllers/simulation.py`.
Answers `ID?`, `PING`, `STOP` honestly; acknowledges everything else without
modelling it. Deliberately *not* a machine simulator. Models three real board
states: correct firmware, pre-handshake firmware (does not recognise `ID?`), and
plugged-in-but-wedged. Simulated boards appear through `list_serial_ports()`.
Enable with `ROBOT_SIMULATED_CONTROLLERS`.

**Phase 2a — fingerprint and preflight.** `backend/app/controllers/{fingerprint,preflight,transport}.py`.
Fingerprint hashes routine set + resolved pin table + protocol + source
contents, canonicalised so collection order cannot change it. Five verdicts;
`WRONG_CONTROLLER` blocks the run rather than warning.

**Firmware `ID?` support.** `firmware/shared/controller_identity.h`, copied
beside all five sketches with an `ID?` branch added to each dispatch.
`__has_include`-guarded so the sketches still build standalone.

**Incidental fixes:** POSIX-only `/tmp` and `killpg` in the flash path (E-Stop
never killed an upload on Windows); `test_gpio_backend` was already failing
before any of this work because it read the mutable repo-root `gantry-state.json`
— state paths are now overridable via `ROBOT_GANTRY_STATE_FILE`,
`ROBOT_Z_GANTRY_STATE_FILE`, `ROBOT_PHYSICAL_STATE_FILE`.

### Implemented but NEVER run against hardware

Treat all of this as unverified:

- The `ID?` handler in the five `.ino` files. **There was no C++ toolchain or
  arduino-cli on the development machine, so the firmware was never compiled.**
  The header uses only `Serial.print`, an `inline` function and `__has_include`
  (GCC 5+; the ESP32 toolchain is well past that), so it is expected to build —
  but that is reasoning, not evidence. **Compile it first, before anything else.**
- `SerialTransport` — the 2-second post-open settle and the `readline` loop were
  written against the datasheet behaviour of ESP32 auto-reset, not observed.
- The whole preflight path against real boards.

### Not started

- **Phase 2b:** unify the ID namespaces, migrate workspaces and
  `hardware-map.json`, wire preflight into the flash path.
- **Phase 3:** the run engine. This is the biggest remaining piece and closes 9
  of the 20 listed defects, including "runs randomly".
- **Phase 4:** function packages and partial-hardware degradation.
- **Phase 5:** frontend becomes a viewer over the run API.

---

## 5. What to do next, in order

### Step 1 — verify the firmware compiles (blocks everything else)

```bash
cd "/home/robot/robot control/Robot-Code"
.arduino-cli/../tools/arduino-cli/arduino-cli compile \
  --config-file .arduino-cli/arduino-cli.yaml \
  --fqbn esp32:esp32:esp32 \
  "functions/esp 32 code/esp32 ttyUSB1/firmware"
```

If `controller_identity.h` does not compile, fix it there and in the other four
copies. If it does, do the manual one-board-at-a-time bring-up from section 2
and confirm a real board answers `ID?`.

### Step 2 — decide the identity strategy with the owner

Section 2 lists the three options. This changes the migration, so settle it
before writing the migration.

### Step 3 — Phase 2b, the migration

**Back up `hardware-map.json` and `workflows/*.json` before touching them.**
This is real machine configuration, not test data.

The migration must:

- give every controller one stable id, used by the Hardware Map, the workspace
  directory, and the manifests
- rewrite `devices[].board_id`, `builder_board_id`, and the saved workflows to
  match, keeping Contract 10 (missing references stay visible, nothing silently
  deleted)
- add `schema_version` to `hardware-map.json` (Contract 13 requires it; it
  currently only has `version: 1`)
- reconcile `controller-x83xnc` (no workspace) and `controller-ykkl80` (no
  board), which are probably a missing workspace and a stale board id
  respectively — **confirm with the owner which physical board is which** rather
  than inferring it
- resolve the duplicated firmware trees: `firmware/z-axis-controller/main.ino`
  and `functions/esp 32 code/esp32 controller-ykkl80/firmware/main.ino` were
  byte-identical before the `ID?` patch, and `firmware/syringe-controller/`
  mirrors a workspace too. The workspace copies are what actually get flashed.
  Deleting a tree is the owner's call.

Then wire `preflight_controller` into the run path so runs stop reflashing
everything, and have `flash_firmware` write `generated_identity.h` (from
`render_identity_header`) into the sketch before compiling.

### Step 4 — Phase 3, the run engine

Design is in `BACKEND_ARCHITECTURE_V2.md` §5–§6 and §8. Summary: compile the
graph to a validated `ExecutionPlan` before anything moves; a node is ready when
every *activated* incoming edge has delivered; control blocks activate only the
edge they chose; fan-in is a real join barrier; loops are re-entrant scopes with
an iteration guard; every node acquires its logical resources
(`gantry.xy`, `z.left`, `syringe.head_b`, `controller:<id>:serial`) in a fixed
global order so two branches wanting the gantry serialise while a Z move and a
dispense genuinely overlap.

Two backend defects to fix while you are in there:

- `function_discovery.test_function` **hardcodes `ok=True`**, so a handler
  returning `{"ok": false}` reads as success.
- `_load_handler_module` re-imports the handler on **every** call, so
  `POST /{id}/cancel` operates on a fresh module instance unrelated to the one
  running. Cache the modules.
- `GET /api/functions` has write side effects (it rewrites `hardware-map.json`),
  and the frontend calls it after every successful block run. Make discovery
  read-only; move the sync to an explicit endpoint.

---

## 6. Practical: running things on the Pi

```bash
cd "/home/robot/robot control/Robot-Code"

./start-all.sh            # backend + frontend
./start-backend.sh        # backend only, uvicorn on 0.0.0.0:8000

# tests (stdlib unittest, no pytest needed)
cd backend && ./.venv/bin/python -m unittest discover -s tests -t .
```

Frontend `http://<pi>:5173`, backend `http://<pi>:8000`, API docs `/docs`.

**Simulation on the Pi** (useful for testing preflight logic without unplugging
the real boards):

```bash
export ROBOT_SIMULATED_CONTROLLERS='[
  {"device":"SIM0","serial_number":"SIM-0001",
   "controller_id":"controller-x83xnc","fingerprint":"deadbeefdeadbeef",
   "routines":["dispense","prime"]}
]'
```

Simulated ports appear alongside real ones in `list_serial_ports()`. Unset it
before real runs so nothing resolves to a fake board.

**Check the safety latch** at any time:

```bash
curl -s localhost:8000/api/safety | python3 -m json.tool
```

---

## 7. Conventions and gotchas

- **Tests are stdlib `unittest`**, with `sys.path.insert(0, parents[1])` at the
  top of each file. There is a `.pytest_cache` but no pytest dependency.
- **Never let tests write repo-root state.** `gantry-state.json`,
  `z-gantry-state.json`, `physical-state.json` are live machine state. Use the
  `ROBOT_*_STATE_FILE` env overrides. A test that pollutes these makes the suite
  order-dependent — that bug already happened once.
- **Comments explain why, not what.** The existing code documents the hardware
  reasoning behind non-obvious choices (why the flag is set before the fan-out,
  why partial travel is adopted after an aborted move). Match that.
- **Contracts are binding.** `docs/ARCHITECTURE_CONTRACTS.md` is the governing
  document; `BACKEND_ARCHITECTURE_V2.md` is how it gets implemented. Contract 10
  in particular (missing references stay visible, never silently deleted) is
  easy to violate during a migration.
- **`docs/PROJECT_STATUS.md` and `AGENTS.md` are referenced by both READMEs but
  do not exist.** Either write them or fix the references.
- Saved workflows embed a **frozen copy of every block definition** in
  `node.data.block`, which is why `workflows/Test_1.json` is 820 KB and why
  stale definitions leak into runs. Phase 5 replaces this with `block_id` +
  `version` resolved from the catalog at load.
- The gantry is **CoreXY**, not independent X/Y. `x-axis-motor` and
  `y-axis-motor` are compatibility names for CoreXY A and B.

---

## 8. Safety notes for whoever runs this next

- The E-Stop latch is now real and **will refuse to clear** while a physical
  fact is uncertain. That is intended. Clear it via
  `POST /api/safety/confirm-physical-state` then `POST /api/safety/rearm`, after
  physically checking the machine. Do not "fix" this by making rearm
  unconditional — that is the bug that was removed.
- After any stop mid tool-change, **look at the gantry before confirming.** The
  system deliberately does not guess.
- Calibration routines intentionally drive into limit switches (fast-touch,
  backoff, slow-touch). During normal motion a limit hit is a fault. Do not
  "fix" a calibration routine that appears to be crashing into a limit on
  purpose.
- First real-hardware run of anything in section 4 should be done with the
  motors powered down, watching the serial log, before letting it move.
