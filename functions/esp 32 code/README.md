# ESP32 Board Workspace Structure

Read `../../docs/ARCHITECTURE_CONTRACTS.md` before changing board workspaces, workflow-function blueprints, or firmware behavior.

Each connected board gets its own workspace folder:

```text
functions/esp 32 code/
  README.md
  esp32 ttyUSB0/
    board.json
    NOTES.md
    firmware/
      main.ino
    workflow-functions/
      dispense.json
```

## What each file does

- `board.json`: metadata for the board and the serial port currently associated with it.
- `firmware/main.ino`: the local Arduino source edited from the Robot Control UI or directly in the board workspace.
- `workflow-functions/*.json`: blueprint files that generate workflow block manifests for the canvas.

## Build and flash flow

1. Edit `firmware/main.ino` or one of the workflow-function blueprint JSON files.
2. Save the file.
3. Use `Build firmware` to compile the sketch on the Pi.
4. Use `Build + Flash` to upload it to the connected ESP32 on the configured serial port.

Most ESP32 dev boards can enter the bootloader automatically through the USB serial adapter's DTR/RTS lines. If upload ever fails to connect, hold the board's `BOOT` button as flashing starts and release it once the upload begins.

The long-term target is workflow-aware firmware assembly: each controller should be flashed with all routines needed by the active workflow, based on the Hardware Map and the blocks used in that workflow.

## Blueprint format

Each blueprint file should contain:

```json
{
  "manifest": {
    "id": "dispense",
    "display_name": "Dispense Syringe Batch",
    "category": "Robot Actions",
    "description": "High-level syringe dispense action.",
    "version": "0.1.0",
    "inputs": [],
    "hardware_devices": [],
    "outputs": [
      {
        "key": "next",
        "label": "Next",
        "type": "flow",
        "description": "Continue when this action completes."
      }
    ]
  },
  "advanced_builder_inputs": [],
  "firmware_entry_file": "firmware/main.ino",
  "protocol": "serial-text"
}
```

## How blocks are created

1. The Pi scans every `workflow-functions/*.json` file.
2. The `manifest` section is synced into `backend/app/functions/<id>/manifest.json`.
3. If the function folder does not exist yet, the Pi creates a placeholder handler.
4. The normal `/api/functions` discovery endpoint then exposes that block to the workflow editor.

## Recommended split

- Put runtime parameters in `manifest.inputs`.
- Use `manifest.outputs` only for control-flow paths. Normal robot actions should have one `next` flow output; use the block settings error path for failures. Do not add outputs for returned data like status text, measurements, or raw controller replies.
- Put firmware tuning, pins, and board-wiring fields in `advanced_builder_inputs`.
- Put required controller routines in `manifest.firmware_requirements`. Use stable routine IDs and point at the firmware source or fragment that must be included when a workflow uses the block.
- Put every actuator, motor, servo, or sensor the function uses in `manifest.hardware_devices`. Use stable device IDs that match the Hardware Map, and set each pin's `function_input_key` to the matching runtime or advanced input. The Hardware Map creates or updates those devices so function inputs can be resolved from the real wiring.
- Advanced functions should reference shared Hardware Map devices instead of keeping an unrelated private pin list. If a function moves syringe head A, it should declare/reference the same `syringe-head-a` device used by the physical hardware map.
- Treat hardware and code as related but separate. The same syringe pump hardware can support multiple firmware routines and workflow functions.
- Keep actual source code changes in `firmware/main.ino`.
- Use `board.json` to override the active `fqbn` or firmware entry file for a specific board workspace if needed.

## Workflow block types

- Basic blocks come from the editor itself and from the Hardware Map. Adding a stepper motor creates a basic stepper move block. Adding a servo creates a basic servo angle block using the servo rotation range from the Hardware Map. Adding a sensor creates a basic sensor read block.
- Advanced functions come from these ESP32 workflow-function blueprints and run through the backend function endpoint.
- Compound functions are made in the Workflow Editor by selecting directly connected blocks, right-clicking the selection, and choosing `Create compound function`.
