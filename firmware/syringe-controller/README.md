# 7-Syringe Pump Controller Firmware

Firmware currently running on the pre-flashed syringe ESP32
(hardware map board `controller-x83xnc`, /dev/ttyUSB0).

Recovered from git history: last modified in commit fb4489e
("fixed advanced setting bugs also added parallel dispensing"),
back when it lived at `functions/esp 32 code/esp32 ttyUSB0/firmware/main.ino`
before that workspace was repurposed for the gantry firmware.

7 steppers: STEP pins 33/25/26/27/14/12/13, DIR pins 32/4/5/18/19/21/22.
Serial protocol (115200 baud): JSON/CSV dispense commands plus
SPEED / INTAKE SPEED / OUTTAKE SPEED — the backend's
syringe_controller.py speaks this protocol.

This board is deliberately NOT a builder workspace: the workflow firmware
planner treats it as externally programmed and never reflashes it. If you
ever need to reflash the syringe ESP32, use this source.
