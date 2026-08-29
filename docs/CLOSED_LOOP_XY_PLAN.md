# Closed-loop XY: implementation plan

Written for the agent implementing this. Read all of it before starting stage 0
— the decisions in "Architecture" were made deliberately with the owner and are
not up for re-litigating mid-build.

The goal is **true closed-loop control**: position error is corrected
*continuously during a move*, not after it. PID, tuned later on the machine.

---

## Why this exists

The CoreXY motors lose steps. The bearings are worn and will get worse, and the
owner has said replacing them is not imminent. Today the machine only discovers
this at a tool change, when the X and Y re-home probes measure the accumulated
drift and reset it (see `_rehome_axis` in `raspberry_gantry.py`). That is a
backstop, not a fix — between tool changes the position quietly degrades, and a
stall mid-move is silent.

Encoders on the motor shafts make the loss visible as it happens, and let the
firmware put the steps back.

---

## Hardware

| Item | Detail |
| --- | --- |
| Controller | A **third ESP32**, dedicated to XY. Confirm availability before starting. |
| Encoders | 2 × **AS5047P-TS_EK_AB** adapter boards (Mouser), one per motor |
| Magnets | `AS5000-MD6H-2` diametric, 6 × 2.5 mm — ships with each kit |
| Mounting | On the **A and B motor shafts**. Not on belt idlers — see below. |
| Drivers | Existing TB6600s, step/dir, shared active-low ENABLE |
| Limits | The four XY switches **move off the Pi onto this ESP32** |

### Pin budget (~13, comfortable on an ESP32)

- 2 × step + 2 × dir = 4
- 1 × shared driver enable = 1
- 4 × limit switches = 4
- SPI: SCK, MISO, MOSI shared + 2 × CS = 5

Avoid GPIO 6–11 (flash), 34–39 (input only), 1/3 (UART to the Pi), and the
strapping pins 0, 2, 5, 12, 15. On a WROVER module also avoid 16/17 (PSRAM).
Record the final choice in `hardware-map.json`, never in code.

### Why motor shafts and not belt idlers

Each encoder then maps 1:1 to one motor, so there are **two independent PID
loops** with no coordinate transform. Measuring the axes instead would mean
every correction goes through the CoreXY transform (`a = x+y`, `b = x-y`),
coupling the two loops, and would put belt compliance *inside* the loop — the
usual source of oscillation. The trade accepted: this cannot detect belt slip
or a pulley slipping on its shaft. Those remain the tool-change re-home's job.

---

## Architecture decisions (settled — do not change without asking)

1. **The Pi-driven XY path stays.** `raspberry_gantry.py` keeps working and the
   hardware map chooses which path is live, exactly as it already does via
   `xy_hardware_is_on_raspberry_pi(context)`. This is the fallback if the loop
   misbehaves, and it is where today's tool-change re-home, drift reporting and
   direction-aware limit guard live. Do not delete or degrade it.
2. **Limit switches move to the XY ESP32.** Nothing in the control loop crosses
   the serial link. This frees Pi GPIO 20, 21 and 26.
3. **Following error halts the machine** past a tunable threshold. A stall must
   be loud. Never silently keep correcting into an obstruction.
4. **Extend the existing protocol.** The ESP32 XY firmware already has
   `SET XY PINS`, `SET XY LIMITS`, `MOVE XY`, `CALIBRATE XY`, and
   `gantry_controller.py` already drives them. Add to that vocabulary; do not
   invent a parallel one.

---

## The control design

### The hard constraint

A step/dir driver accepts **only step pulses**. There is no torque command. So
the loop cannot be a textbook servo — it works like a commercial closed-loop
stepper (iHSS57 and similar): a trajectory says where the axis *should* be, the
encoder says where it *is*, and PID trims how many steps get emitted.

```
trajectory(t) ──► target_steps ──┐
                                 ├──► error ──► PID ──► correction_steps
encoder ──► actual_steps ────────┘                          │
                                                            ▼
                              step generator setpoint = target + correction
                                          │  (rate-limited)
                                          ▼
                                     STEP/DIR pins
```

### Units

- AS5047P is **14-bit: 16384 counts/revolution**
- Motors run **800 steps/revolution**
- So **20.48 encoder counts per full step** — single-step loss is clearly visible
- Do all loop maths in **encoder counts**, convert to steps only when emitting

### The three things that must be true

1. **Loop rate 1 kHz**, on a dedicated FreeRTOS task pinned to core 1, or a
   timer ISR. It must not be blocked by serial handling.
2. **Step generation must be non-blocking.** This is the largest single piece of
   work. `runDualAxisMove` today is a blocking loop built on
   `delayMicroseconds` (see `main.ino` ~line 203) — a control loop cannot run
   inside it. Replace with a high-rate timer ISR (~100 kHz) holding a phase
   accumulator per axis, emitting a pulse when one is due.
3. **The PID output must be rate-limited.** A correction spike that commands
   steps faster than the motor can follow causes *more* loss, not less. Clamp
   the emitted step rate to the same ceiling a normal move uses.

### PID specifics

- Error term in encoder counts; output in steps
- **Derivative on measurement, not error** — avoids a kick when the setpoint moves
- **Integral clamped** (anti-windup), and **frozen while the output is saturated**
- Start with `Kp` small, `Ki = 0`, `Kd = 0`; the owner tunes on the machine
- Gains, the following-error limit and the loop rate are all **settings**, not
  constants — reachable over serial and stored in the hardware map

---

## Stages

Each stage ends in something testable on the machine. Do not start a stage
until the previous one is proven on hardware.

### Stage 0 — bring-up, no motion

**Goal:** the board exists, is identified, and nothing moves.

- New ESP32 workspace under `functions/esp 32 code/`, following the existing
  layout. Give it a controller id and let the identity handshake work — the
  `ID?` handler and fingerprint machinery already exist and must not be bypassed.
- Add the board and its devices to `hardware-map.json`: two steppers, four limit
  switches, two encoders, one shared enable.
- Wire the enable line into `motor_power_service` as its own power domain, the
  way `raspberry_gantry.py` does. **Check the polarity on the machine** — the
  TB6600s are active-low, and getting this backwards is silent (see
  `_register_power_domain`).

**Acceptance:** `POST /api/esp32-builder/boards/<id>/preflight` returns `ok`;
the board reports its identity; no motor is energised.

### Stage 1 — read and report

**Goal:** trustworthy position from both encoders.

- SPI driver for AS5047P. Verify frame format, parity and register addresses
  against the datasheet — do not trust this document for them.
- **Polling over SPI is sufficient**, and simpler than wiring ABI into the PCNT
  peripheral. At 10 MHz a 16-bit frame is ~2 µs, so two encoders at 1 kHz costs
  nothing. ABI stays available as an escape hatch if the loop ever needs it.
- Accumulate turns across wraps. The sensor is absolute over one revolution
  only; a poll must never miss half a revolution. At 1 kHz that is safe past any
  speed this machine can reach, but assert it rather than assume: if two
  consecutive reads differ by more than half a revolution, that is a fault.
- New command: `ENCODER?` returning raw angle, accumulated counts and a
  magnitude/error status per encoder.

**Acceptance:** turn each motor by hand one full revolution; accumulated count
changes by 16384 ± a small tolerance, and does not jump at the wrap. Rotate
several turns each way and confirm it returns to where it started.

### Stage 2 — following-error monitoring, no correction

**Goal:** step loss becomes loud. Still open-loop motion.

- Keep the existing blocking move loop for now. Read the encoders every N steps
  inside it and compute following error.
- Halt the move if `|error| > following_error_limit` (default ~10 full steps =
  ~205 counts). Report the axis and the measured error.
- Report the peak and final following error in the move reply, and surface it
  through `gantry_controller.py` into the move result — mirror the shape of the
  `speed` report added to `_move_result` in `raspberry_gantry.py`.

**Acceptance:** run normal moves and confirm errors stay small. Then stall an
axis by hand and confirm it halts promptly and names the axis. This stage alone
is worth having even if stage 3 slips.

### Stage 3 — in-motion PID correction

**Goal:** the loop closes. Error is corrected continuously *during* the move.

1. **Replace the blocking step generator** with the timer-ISR design above.
   Prove it open-loop first: moves must be as accurate and as smooth as before,
   with trapezoidal accel intact, before any feedback is added. Do not skip this
   — a bug here looks exactly like a tuning problem later.
2. **Trajectory generator** producing target position per loop tick from the
   existing trapezoidal profile.
3. **PID**, per the specifics above, output summed into the step setpoint.
4. **Commands:** `SET XY PID <kp> <ki> <kd>`, `SET XY FOLLOW LIMIT <counts>`,
   `XY PID?` to read them back.
5. **Tuning support:** stream or buffer `(t, target, actual, error, output)` so
   gains can be tuned against data rather than by feel. The owner has been
   burned by judging behaviour by eye this session — give them numbers.

**Acceptance:** commanded moves land within a few encoder counts. Apply drag by
hand mid-move and watch it corrected in flight rather than at the end. Exceeding
the limit still halts. Compare repeatability against the Pi path using the
existing repeatability block.

---

## Safety rules — non-negotiable

- **E-Stop wins.** The stop path must halt the loop and the step generator
  immediately, and must not be delayed by serial handling.
- **Limits abort motion in firmware**, on the same board, without a round trip.
- **Never correct past the following-error limit.** A machine that keeps pushing
  into an obstruction with a tool head and glassware attached is the dangerous
  failure, not a stopped one.
- **Come up disabled.** After reset, drivers must be off until the host asks —
  the same rule the Z/pump board follows.
- **Position survives an abort.** Adopt the steps actually taken, as the Pi path
  and the Z axis both now do. An E-Stop must not cost the calibration.

---

## Files this touches

- `functions/esp 32 code/esp32 <new-id>/firmware/main.ino` — new
- `backend/app/services/gantry_controller.py` — new commands, error reporting
- `backend/app/models/gantry.py` — PID and follow-limit fields
- `hardware-map.json` — board, steppers, limits, encoders, enable pin
- `backend/tests/` — a test per stage; see below

## Testing

The suite is stdlib `unittest`, run with `ROBOT_GPIO_SIMULATE=1`. Firmware
cannot be unit-tested here, so test the **Pi side**: protocol formatting, reply
parsing, error propagation, and that a following-error fault becomes a failed
block rather than a silent pass.

Note the lesson from this session's tests: exercise the path the operator
actually presses. Testing `run_sequence` while `pickup()` was broken let a
NameError reach the machine with every test green. Cover the handler entry
points, not only the helpers.

## What only the machine can tell you

Everything below has to be checked on hardware, not reasoned about:

- Enable polarity on the new board
- Encoder counting direction versus motor step direction, per axis — a sign
  error here turns the PID into positive feedback and the axis will run away.
  **Verify this before enabling the integral term.**
- Magnet centring and air gap. A poorly centred magnet produces a smoothly
  varying error that looks exactly like a real reading.
- Achievable loop rate with serial traffic in flight
