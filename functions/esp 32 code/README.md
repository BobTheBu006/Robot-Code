# ESP32 Function Builder Structure

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
- `firmware/main.ino`: the local Arduino source edited from the Robot Control UI.
- `workflow-functions/*.json`: blueprint files that generate workflow block manifests for the canvas.

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
    "outputs": []
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
- Put firmware tuning, pins, and board-wiring fields in `advanced_builder_inputs`.
- Keep actual source code changes in `firmware/main.ino`.
