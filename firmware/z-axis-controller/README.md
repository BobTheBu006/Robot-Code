# Dual Z-Axis Controller Firmware

> **The canonical source now lives in the builder workspace:**
> `functions/esp 32 code/esp32 controller-ykkl80/firmware/main.ino`
>
> That is the copy the app compiles and flashes. Edit it there, not here.
> This directory is kept only as the recovery archive of where the firmware
> came from; the copy in it may lag behind.

Firmware for the "Double Z axis and pumps" ESP32 (hardware map board
`controller-ykkl80`). Drives two Z motors; the four limit switches are NOT
wired to this board - they go straight to Raspberry Pi GPIO, and the Pi
decides when to stop (see `backend/app/services/hybrid_z_axis.py`).

Originally recovered from `functions/esp 32 code/esp32 ttyUSB1/firmware/main.ino`,
the combined CoreXY+Z controller firmware from before the XY gantry moved to
Raspberry Pi GPIO. It still contains the XY/CoreXY command handlers; they are
harmless to leave in (never invoked) since this board only has Z motors wired.

Serial protocol (115200 baud):
- `SET Z PINS <leftStep> <leftDir> <rightStep> <rightDir>`
- `STEP Z <leftSteps> <rightSteps> <rpm> <trapezoidFlag> <accelRpmPerSec>`
  - Open-loop move; this board reads no limit switches for it. Replies
    `OK STEP Z <leftDone> <rightDone>` with the steps actually travelled, or
    `OK STOP STEP Z <leftDone> <rightDone>` if the host sent `STOP` mid-move.
  - The host seeks a switch by commanding the whole travel and sending `STOP`
    the instant its own GPIO sees the switch trip. `runDualAxisMove` checks for
    `STOP` between every step, so overtravel is one step period, and the axis
    moves smoothly instead of hopping between short bursts.
- `STOP` - abort the move in progress.
- `PING` -> `PONG`

**Do not send this board the limit-switch pin numbers from the Hardware Map.**
Those are Raspberry Pi GPIO numbers. `SET Z LIMITS` with them configures ESP32
GPIO 6, which is wired to this chip's internal SPI flash - it hangs the board
with a watchdog reset. The hybrid Z service never sends `SET Z LIMITS`.
