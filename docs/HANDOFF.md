# Handoff: backend rebuild, continuing on the Raspberry Pi

Written for the next AI agent (or human) picking this up **on the Pi, with the
robot attached**. The previous work was done on a Windows development machine
with no hardware, which is the single most important thing to know: several
things are implemented and unit-tested but have **never touched a real board**.

Read `docs/BACKEND_ARCHITECTURE_V2.md` first — it is the agreed design and the
defect-to-phase map. This file is the current state and what to do next.

---

## 0. Session update — first session actually on the Pi

Everything below this section was written without hardware. This section is
what changed once it ran on the real machine. **Robot power supply was
unplugged for all of it, so nothing could move.**

**Step 1 is done: the firmware compiles.** All five sketches build with the
`ID?` handler, including the standalone case with no `generated_identity.h`
(the `__has_include` guard works). Verified through the app's own
`build_firmware` path, so it is the same compile the backend performs:

| sketch | flash |
| --- | --- |
| `esp32 ttyUSB0` | 336,772 B (25%) |
| `esp32 ttyUSB1` | 315,140 B (24%) |
| `esp32 controller-ykkl80` | 315,472 B (24%) |
| `firmware/syringe-controller` (standalone) | 305,208 B (23%) |
| `firmware/z-axis-controller` (standalone) | 315,472 B (24%) |

**The identity handshake now works end to end on real hardware.** This was the
largest "implemented but never run against a board" item. The Z controller was
flashed through the app's own path and asked who it was:

```
ID? -> {"controller_id":"controller-ykkl80","name":"Double Z axis and pumps",
        "fingerprint":"c91541999072da3d","protocol":1,
        "routines":["calibrate_z","move_z"]}
```

and preflight then made all three decisions correctly against that live board:

| situation | verdict | behaviour |
| --- | --- | --- |
| firmware matches | `ok` | flash skipped (7 s instead of ~30 s) |
| a pin changed in the Hardware Map | `needs_flash` | fingerprint mismatch detected |
| board reports a different controller id | `wrong_controller` | **refuses to flash** |

That last row is the fix for "flashing hit the wrong board": a board that says
it is something else is no longer overwritten.

What made it work is the missing link described in section 4a — `flash_firmware`
now actually writes `generated_identity.h`. Before, `render_identity_header`
existed but nothing called it, so every board answered with an empty identity.

**Both controllers now self-identify, with both plugged in at once.** The
syringe controller was connected later in the same session and brought up:

```
/dev/ttyUSB0  serial 58d72d4c…  ->  controller-ykkl80  "Double Z axis and pumps"
/dev/ttyUSB1  serial 8012ef3b…  ->  controller-x83xnc  "7 syringe pump controller"
```

Preflight returns `ok` for both (no reflash), and the wrong-board case was
tested for real: aiming the syringe firmware at the Z board's port returns
`wrong_controller` and refuses. **This is the defect that used to overwrite a
working controller, now provably closed on hardware.** The syringe protocol
still works after reflashing (`SPEED`, `SET HEAD PINS` answer normally).

This required creating the workspace `esp32 controller-x83xnc`, which never
existed — section 3 notes the syringe controller had no workspace at all, which
is exactly why `plan_workflow_firmware` could not resolve it and downgraded it
to "externally programmed". The syringe firmware only lived at
`firmware/syringe-controller/`, outside any workspace. The syringe manifests
(`dispense`, `prime_syringes`, `7_syringe_dispenser_slow_and_good`) now declare
`builder_board_id: controller-x83xnc`; `dispense` previously claimed `ttyUSB1`,
which is the **Z** board.

**Section 2a is now confirmed with both boards present: the serials are
unique** (`58d72d4c…` vs `8012ef3b…`). The boards never shared a factory
serial; the duplication was purely the overwrite bug, now fixed.

**Access door interlock added (Pi GPIO 13).** A switch on the access door
gates *runs*, not all motion: a single block test with the door open still
works, because that is how the machine gets brought up and the operator is
standing there. Run all is refused, with a deliberate override for when it is
needed. Enforced backend-side via a run session, which also watches the door
for the run's duration and stops every actor through the safety controller if
it opens. Kept separate from the E-Stop latch on purpose - verified on hardware
that an E-Stop still latches while the door override is on. See section 4c.

**All 14 blocks are implemented.** `dispense` was still the generated
"not implemented" placeholder; it and the 7-syringe preset now share one input
mapping. The `ttyUSB0` board references on the Pi-driven blocks are retired -
see section 4c.

**The suite is green on the Pi: 74/74.** It was 8 failing (1 failure,
7 errors) purely from running on real hardware. See section 4a for what that
uncovered — one of them was a genuine production bug and one was a unit test
quietly driving the real gantry.

**Section 2's premise about USB serials is wrong — see section 2a.** The
conclusion (do not trust the serial as recorded) still holds, but for a
different and *fixable* reason. Read 2a before acting on section 2.

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

## 2a. Correction: the boards are NOT sharing one factory serial

Section 2 states that all three workspaces record the same USB serial because
"these are cheap CP2102N bridges that were never given unique serials at the
factory". **That inference is wrong.** The evidence:

`board.json` serials recorded over time, from git history:

| workspace | commit | date | serial | USB location |
| --- | --- | --- | --- | --- |
| `esp32 ttyUSB0` | aec21f8 | 2026-04-02 | `76ae3066…` | 3-1 |
| `esp32 ttyUSB0` | 4c86318 | 2026-06-26 | `b4ca1bab…` | 1-2 |
| `esp32 ttyUSB0` | d501505 | 2026-07-06 | `b4ca1bab…` | 3-2 |
| `esp32 ttyUSB0` | ac0d2b3 | 2026-07-19 | `b4ca1bab…` | 3-1 |
| `esp32 ttyUSB1` | 61623c5 | 2026-04-02 | `b4ca1bab…` | 1-2 |
| `esp32 ttyUSB1` | 57b8b07 | 2026-08-07 | `58d72d4c…` | 3-2 |

Three *distinct* serials appear (`76ae3066`, `b4ca1bab`, `58d72d4c`), and the
same serial appears at three different USB locations. Boards that shared a
factory serial would show one value everywhere; this shows the opposite.

**The real cause is that the workspace metadata is overwritten by whatever is
plugged in.** `Esp32BuilderService._ensure_board_workspace` (esp32_builder.py,
~line 725) writes:

```python
"serial_number": port.serial_number or existing_metadata.get("serial_number"),
```

The connected port's serial always wins. `_ensure_board_workspace` runs for
every connected port on `list_boards()` / `get_board()`, and the workspace is
chosen by port name (`/dev/ttyUSB1` → workspace `esp32 ttyUSB1`). So plugging
one board into a port stamps *that board's* serial onto *that port's*
workspace. All three currently read `58d72d4c…` because the Z board is the
only one connected and has visited all of those ports.

**What this changes:**

- The serial is probably a *usable* discriminator between the two physical
  boards. What is not usable is `board.json`'s record of it, because it is
  continuously overwritten.
- So the fix is not necessarily "abandon serial identity" — it may be "stop
  auto-overwriting recorded identity", i.e. treat `board.json` identity as an
  assertion made once, not a mirror of whatever is plugged in.
- `ID?` firmware identity is still the most robust answer and is still worth
  finishing. This just means the interim situation is less dire than section 2
  implies, and that the auto-stamp is a bug worth fixing regardless.

**Still an owner decision — not taken.** Confirm by plugging in each board
alone and recording its serial. What is *not* in doubt: with only one board
connected, every workspace resolves to it, so a flash aimed at the syringe
controller can still land on the Z controller. The section 2 bring-up
procedure remains the safe path until identity is settled.

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

### 4a. Fixed in the first on-Pi session

**Production bug — the GPIO loader could not fall back.**
`gpio_backend._load_rpi_gpio` caught only `ImportError`. The `rpi-lgpio` shim
executes real code at import against whatever `lgpio` it finds, so a version
skew raises `AttributeError` (`module 'lgpio' has no attribute
'SET_PULL_NONE'`) instead. That escaped the loader and crashed
`load_gpio_backend()` outright — meaning a `pip` upgrade on the Pi would take
the gantry down rather than fall back to the lgpio adapter, which is the entire
purpose of that function. Now catches `Exception` and reports the type.

**A unit test was driving the real gantry.** The three
`test_raspberry_gantry` routing tests call the full `calibrate_xy` / `move_xy`
path. On the Windows dev machine there was no GPIO library, so they silently
fell back to simulation and passed. On the Pi they configured real pins,
stepped real motors, and then failed on whatever the real limit switches read.
They only ever assert *routing* (`controller == "raspberry-pi"`), so they now
pin `ROBOT_GPIO_SIMULATE=1` explicitly. The fallback test additionally denies
`lgpio` (`sys.modules["lgpio"] = None`), since on the Pi lgpio really is
installed and it would otherwise fall through to real hardware instead of
simulation. **If the power supply had been connected, that suite run would
have moved the machine.**

**`test_reports_both_reasons_when_no_backend_is_available`** assumed both GPIO
libraries were absent — true on a laptop, false on the Pi. It now blocks both
imports explicitly.

**The three backend defects listed in Step 4 are done:**

- `test_function` hardcoded `ok=True`, so a handler returning `{"ok": false}`
  read as success and a workflow kept running past a failed block. It now
  honours the handler's own `ok`, surfacing `error`/`message` when false.
- `_load_handler_module` re-imported the handler on every call, so `cancel`
  ran against a *different module instance* than the run it meant to abort —
  any module-level state (open serial session, stop flag) was invisible to it.
  Modules are now cached, keyed on path + mtime so editing a handler still
  hot-reloads without a backend restart.
- `GET /api/functions` had write side effects (it regenerated manifests, which
  rewrites `hardware-map.json`) and the frontend polls it after every block
  run. Discovery is now read-only; the regeneration moved to
  `POST /api/functions/sync`. Blueprint edits still propagate because
  `esp32_builder` already calls `sync_generated_functions()` from its own
  save/delete/list endpoints.

Result: **74/74 tests pass on the Pi**, and the suite no longer touches
hardware (runtime 10s → 0.7s, which is itself the tell that it had been
stepping real motors).

### 4b. Identity handshake wired up (same session)

**`flash_firmware` now writes `generated_identity.h`.** This was the missing
link: `render_identity_header` existed but had no caller, so every flashed
board reported an empty identity and preflight could only ever say "cannot
verify → flash it". `_prepare_sketch_dir` now stamps the header into the sketch
immediately before compiling, so identity ships with the firmware.

**`Esp32BuilderService.build_firmware_bundle(board_id, workspace_dir, metadata)`**
assembles what should be on a controller: routine ids from the manifests whose
`builder_board_id` is that board, the resolved pin table for the devices the
Hardware Map places on it, and hashes of the firmware sources. Changing any of
those changes the fingerprint, so the board stops matching and gets reflashed;
a rebuild that changes nothing keeps matching and is skipped.

**Controller name added** (was requested): the header now also defines
`ROBOT_CONTROLLER_NAME` and `ID?` returns a `name` field, so a board can say
"I am the Double Z axis and pumps controller" rather than only an opaque id.
The name is deliberately **excluded from the fingerprint** — renaming a
controller in the Hardware Map must not make every board look stale. Names and
ids are escaped for the C string literal, so a stray quote in the Hardware Map
cannot emit a header that fails to compile.

**`flash_firmware(board_id, skip_if_current=True)`** asks the board first:
`ok` → skip, `wrong_controller` → refuse with an error, anything else → flash.
`preflight_board(board_id)` exposes the verdict on its own for a caller that
wants to decide for itself. The default is still `skip_if_current=False`, so
nothing silently changed behaviour for existing callers — **the run path still
needs to opt in** (see next steps).

**Workspace identity is no longer overwritten by whatever is plugged in.**
`_ensure_board_workspace` used to prefer the connected port's serial over the
recorded one; it now only fills identity in when it is genuinely unknown. This
is the section 2a bug. Note the corollary: `board.json` files written *before*
this fix may still hold a wrong serial, so treat existing recorded serials as
suspect until each board has been seen alone.

8 tests added (`tests/test_identity_flash_path.py`), **82/82 pass**.


### 4c. Access door, block audit and the ttyUSB0 cleanup (same session)

**Access door.** `backend/app/services/access_door.py` reads GPIO 13 (closed
switch = closed door, so the pin reads high when open - confirmed against the
real switch). `GET /api/safety` now carries `access_door` and `run_allowed`;
`POST /api/safety/access-door/override` toggles the override, which is not
persisted. `POST /api/safety/run-session/start|end` is what a run calls: start
is refused while the door blocks a run or the stop is latched, and it watches
the door until end. The watch runs only during a run - polling it while idle
would stop the machine every time someone reached in, which is exactly when
block testing is wanted.

**Skip ESP32 flashing is gone.** Flashing is decided by asking the board
whether its firmware is already correct, so the manual toggle had no purpose;
the toolbar slot is now the door override.

**Firmware prep also runs for a single block test**, not just Run all, so a
controller missing the routine a block calls gets flashed without having to run
the whole workflow.

**Handshake no longer resets the board.** Opening the port the ordinary way
toggles DTR/RTS and reset the ESP32, forcing a 2 s boot wait per board per run.
The port is now opened without asserting those lines and drained until quiet.
Firmware prep for both controllers: ~15 s -> ~3.8 s. Note the trap found on the
way: a *fixed short* settle reads the board's boot banner as the answer to
`ID?`, which parses as "no identity" and reflashes a good controller. Drain
until quiet, never for a fixed interval.

**Block audit.** All 14 blocks implemented, none stubbed. Seven carried
`builder_board_id: ttyUSB0` while the Hardware Map placed their hardware on
`raspberry-pi`. Corrected; `calibrate_xy`'s blueprint moved to
`functions/esp 32 code/retired-blueprints/` because a blueprint's workspace is
what sets `builder_board_id`, so editing the generated manifest never stuck.

**Controller ids are now stable.** The Hardware Map named boards after ports
(`ttyUSB0`/`ttyUSB1`) while the firmware reported `controller-ykkl80` /
`controller-x83xnc`, so preflight refused every flash as `wrong_controller`.
The boards were renamed to the ids the firmware reports and each records its
USB serial. Port-derived ids cannot work here - the ports renumbered twice in
one session.

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

### Step 1 — verify the firmware compiles (DONE — see section 0)

All five sketches compile. Nothing here is blocked any more. The command below
is kept because it is still the way to re-check after editing the header; note
the sketch folder name must match the `.ino` name, which is why going through
`esp32_builder.build_firmware(board_id)` is easier than calling arduino-cli by
hand on `firmware/`:

```bash
cd backend && ./.venv/bin/python -c \
  "import sys; sys.path.insert(0,'.'); \
   from app.services.esp32_builder import esp32_builder_service as s; \
   print(s.build_firmware('ttyUSB1').ok)"
```

The remaining unverified half is a **real board answering `ID?`**, which is
gated on the identity decision below.

### Step 1 (original, for reference) — verify the firmware compiles

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

### Step 1b — what is left on identity (do this next)

The mechanism works; what remains is data and wiring:

1. **Make the run path opt into `skip_if_current=True`.** Today the frontend
   still calls flash unconditionally, so runs reflash every board even though
   the board can now say it is already correct. This is the change that
   actually delivers "stop reflashing everything".
2. **Bring the syringe controller up the same way.** It was not connected this
   session. Do it alone on the bus (section 2 procedure), flash it, confirm
   `ID?` reports `controller-x83xnc`. After that both boards self-identify and
   the USB-serial ambiguity stops mattering for good.
3. **Reconcile the ids** — see the mismatch below, which the bundle builder
   makes visible: asking for board `controller-ykkl80` yields `pins: []`
   because the Hardware Map puts the Z motors on board `ttyUSB1`, while
   `calibrate_z`/`move_z` declare `builder_board_id: controller-ykkl80`. The
   fingerprint is therefore computed over an empty pin table for that board.
   Not wrong yet — nothing depends on those pins being in the fingerprint —
   but it means a Z pin change would *not* trigger a reflash. Fix it as part
   of the namespace migration.
4. Likewise `dispense` declares `builder_board_id: ttyUSB1` (the Z board) while
   its devices sit on the syringe board, so board `ttyUSB1`'s bundle currently
   claims a `dispense` routine. Same migration.

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

~~Two backend defects to fix while you are in there:~~ **All three are done —
see section 4a.** (`test_function` `ok=True`, `_load_handler_module`
re-importing, and `GET /api/functions` write side effects.)

One follow-up they created: the frontend still calls `GET /api/functions`
expecting the sync side effect (it refreshes the block catalog after every
successful run so placed blocks pick up regenerated manifests). That still
works, because the catalog is re-read — but if a *blueprint* changed and the
manifests need regenerating, the frontend should now call
`POST /api/functions/sync` instead. Worth doing when Phase 5 touches the
frontend.

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
