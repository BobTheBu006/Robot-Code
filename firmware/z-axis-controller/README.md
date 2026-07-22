# Dual Z-Axis Controller Firmware

Firmware for the "Double Z axis and pumps" ESP32 (hardware map board
`controller-ykkl80`). Drives two independently-homed Z motors (left/right)
against min and max limit switches on each side.

Copied from `functions/esp 32 code/esp32 ttyUSB1/firmware/main.ino` - the
original combined CoreXY+Z controller firmware from before the XY gantry
moved to Raspberry Pi GPIO. That file also still contains the XY/CoreXY
command handlers; they are harmless to leave in (never invoked) since this
board only has Z motors and Z limit switches wired, but a rebuild that trims
them down would be a reasonable cleanup later.

Serial protocol (115200 baud), matching `backend/app/services/gantry_controller.py`:
- `SET Z PINS <leftStepPin> <leftDirPin> <rightStepPin> <rightDirPin>`
- `SET Z LIMITS <leftMinPin> <leftMaxPin> <rightMinPin> <rightMaxPin>` (calibration path)
- `SET Z LIMITS <mode> <leftMinPin> <leftMaxPin> <rightMinPin> <rightMaxPin>` (move path)
- `CALIBRATE Z <leftTrackLengthCm> <rightTrackLengthCm> <rpm> <trapezoidFlag> <accelerationRpmPerSecond>`
  - Homes each side down to its min limit switch (sets 0), then up to its max
    limit switch, using the entered track length as the expected/safety
    travel budget. The actual measured travel becomes the calibrated track
    length - a real measurement, not a blind accept of the input.
- `MOVE Z <leftCm> <rightCm> <rpm> <trapezoidFlag> <accelerationRpmPerSecond> <onTheFlyCalibrationFlag> <maxDiffSteps>`

Requires four limit switches: left-min, left-max, right-min, right-max.
This board is deliberately NOT a builder workspace: the workflow firmware
planner treats it as externally programmed and never reflashes it. If it
ever needs reflashing, this is the source to use.
