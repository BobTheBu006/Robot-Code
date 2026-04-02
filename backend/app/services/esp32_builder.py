import glob
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.models.esp32_builder import (
    Esp32BoardDetail,
    Esp32BoardListResponse,
    Esp32BoardSummary,
    Esp32BuilderFile,
    Esp32FileSaveResponse,
    Esp32FunctionBlueprint,
)


class Esp32BuilderError(RuntimeError):
    pass


@dataclass
class _SerialPortInfo:
    device: str
    description: str | None = None
    hardware_id: str | None = None
    serial_number: str | None = None


class Esp32BuilderService:
    def __init__(self, repo_root: Path, app_functions_dir: Path) -> None:
        self._repo_root = repo_root
        self._root_dir = repo_root / "functions" / "esp 32 code"
        self._app_functions_dir = app_functions_dir

    def list_boards(self) -> Esp32BoardListResponse:
        self._ensure_root_structure()

        connected_ports = self._list_serial_ports()
        connected_by_id = {
            self._board_id_from_port(port.device): port for port in connected_ports
        }

        for port in connected_ports:
            self._ensure_board_workspace(port)

        self.sync_generated_functions()

        boards: list[Esp32BoardSummary] = []
        seen_board_ids: set[str] = set()

        for board_id, port in connected_by_id.items():
            boards.append(self._build_board_summary(board_id, port, connected=True))
            seen_board_ids.add(board_id)

        for workspace_dir in sorted(self._workspace_dirs(), key=lambda path: path.name.lower()):
            metadata = self._load_board_metadata(workspace_dir)
            board_id = metadata.get("board_id") or self._board_id_from_workspace(workspace_dir)
            if board_id in seen_board_ids:
                continue

            boards.append(self._build_board_summary(board_id, None, connected=False))

        return Esp32BoardListResponse(boards=boards)

    def get_board(self, board_id: str) -> Esp32BoardDetail:
        self._ensure_root_structure()

        connected_ports = {
            self._board_id_from_port(port.device): port for port in self._list_serial_ports()
        }
        port = connected_ports.get(board_id)
        if port is not None:
            self._ensure_board_workspace(port)

        self.sync_generated_functions()

        workspace_dir = self._resolve_workspace_dir(board_id)
        if not workspace_dir.exists():
            raise Esp32BuilderError(f"Unknown ESP32 board '{board_id}'.")

        files = [self._read_workspace_file(path, workspace_dir) for path in self._editable_files(workspace_dir)]
        blueprints, errors = self._load_blueprints(workspace_dir)

        summary = self._build_board_summary(board_id, port, connected=port is not None)
        summary_data = summary.model_dump()
        summary_errors = list(summary_data.pop("errors", []))
        return Esp32BoardDetail(
            **summary_data,
            files=files,
            blueprints=blueprints,
            errors=[*summary_errors, *errors],
            instructions_path=str(self._instructions_path()),
        )

    def save_board_file(
        self,
        board_id: str,
        relative_path: str,
        content: str,
    ) -> Esp32FileSaveResponse:
        workspace_dir = self._resolve_workspace_dir(board_id)
        if not workspace_dir.exists():
            raise Esp32BuilderError(f"Unknown ESP32 board '{board_id}'.")

        target_path = (workspace_dir / relative_path).resolve()
        if workspace_dir not in target_path.parents and target_path != workspace_dir:
            raise Esp32BuilderError("Cannot write outside the selected ESP32 workspace.")

        if not target_path.suffix.lower() in {".ino", ".json", ".md", ".txt", ".py"}:
            raise Esp32BuilderError("Only text-based ESP32 workspace files can be edited from the UI.")

        if target_path.parent != workspace_dir and not target_path.parent.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.suffix.lower() == ".json" and "workflow-functions" in target_path.parts:
            self._validate_blueprint_content(content)

        target_path.write_text(content, encoding="utf-8")
        self.sync_generated_functions()

        return Esp32FileSaveResponse(
            board_id=board_id,
            relative_path=relative_path,
            saved_at=datetime.now(timezone.utc),
        )

    def sync_generated_functions(self) -> None:
        self._ensure_root_structure()

        for workspace_dir in self._workspace_dirs():
            blueprints, _errors = self._load_blueprints(workspace_dir)
            for blueprint in blueprints:
                manifest = blueprint.manifest
                function_dir = self._app_functions_dir / manifest.id
                function_dir.mkdir(parents=True, exist_ok=True)

                manifest_path = function_dir / "manifest.json"
                handler_path = function_dir / "handler.py"
                requirements_path = function_dir / "requirements.txt"

                manifest_path.write_text(
                    json.dumps(manifest.model_dump(), indent=2) + "\n",
                    encoding="utf-8",
                )

                if not handler_path.exists():
                    handler_path.write_text(
                        self._generated_placeholder_handler(manifest.id),
                        encoding="utf-8",
                    )

                if not requirements_path.exists():
                    requirements_path.write_text(
                        "# Add per-function runtime dependencies here.\n",
                        encoding="utf-8",
                    )

    def _ensure_root_structure(self) -> None:
        self._root_dir.mkdir(parents=True, exist_ok=True)
        instructions_path = self._instructions_path()
        if not instructions_path.exists():
            instructions_path.write_text(self._instructions_markdown(), encoding="utf-8")

    def _instructions_path(self) -> Path:
        return self._root_dir / "README.md"

    def _workspace_dirs(self) -> list[Path]:
        if not self._root_dir.exists():
            return []

        return [path for path in self._root_dir.iterdir() if path.is_dir() and path.name.startswith("esp32 ")]

    def _board_id_from_port(self, port: str) -> str:
        basename = Path(port).name or port
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", basename).strip("-")
        return normalized or "board"

    def _board_id_from_workspace(self, workspace_dir: Path) -> str:
        suffix = workspace_dir.name.removeprefix("esp32 ").strip()
        return self._board_id_from_port(suffix)

    def _workspace_dir_for_board_id(self, board_id: str) -> Path:
        matching_dir = self._root_dir / f"esp32 {board_id}"
        if matching_dir.exists():
            return matching_dir

        for workspace_dir in self._workspace_dirs():
            metadata = self._load_board_metadata(workspace_dir)
            if metadata.get("board_id") == board_id:
                return workspace_dir

        return matching_dir

    def _resolve_workspace_dir(self, board_id: str) -> Path:
        return self._workspace_dir_for_board_id(board_id)

    def _ensure_board_workspace(self, port: _SerialPortInfo) -> Path:
        board_id = self._board_id_from_port(port.device)
        workspace_dir = self._workspace_dir_for_board_id(board_id)
        firmware_dir = workspace_dir / "firmware"
        blueprint_dir = workspace_dir / "workflow-functions"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        firmware_dir.mkdir(parents=True, exist_ok=True)
        blueprint_dir.mkdir(parents=True, exist_ok=True)

        board_metadata_path = workspace_dir / "board.json"
        board_metadata = {
            "board_id": board_id,
            "display_name": f"ESP32 {Path(port.device).name}",
            "port": port.device,
            "description": port.description,
            "hardware_id": port.hardware_id,
            "serial_number": port.serial_number,
            "firmware_entry_file": "firmware/main.ino",
        }
        board_metadata_path.write_text(
            json.dumps(board_metadata, indent=2) + "\n",
            encoding="utf-8",
        )

        firmware_path = firmware_dir / "main.ino"
        if not firmware_path.exists():
            firmware_path.write_text(self._default_syringe_firmware(), encoding="utf-8")

        notes_path = workspace_dir / "NOTES.md"
        if not notes_path.exists():
            notes_path.write_text(self._default_workspace_notes(port), encoding="utf-8")

        blueprint_path = blueprint_dir / "dispense.json"
        if not blueprint_path.exists():
            blueprint_path.write_text(
                json.dumps(self._default_dispense_blueprint(port.device), indent=2) + "\n",
                encoding="utf-8",
            )

        return workspace_dir

    def _load_board_metadata(self, workspace_dir: Path) -> dict[str, str | None]:
        metadata_path = workspace_dir / "board.json"
        if not metadata_path.exists():
            return {
                "board_id": self._board_id_from_workspace(workspace_dir),
                "display_name": f"ESP32 {workspace_dir.name.removeprefix('esp32 ')}",
                "port": None,
            }

        try:
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {
                "board_id": self._board_id_from_workspace(workspace_dir),
                "display_name": f"ESP32 {workspace_dir.name.removeprefix('esp32 ')}",
                "port": None,
            }

    def _build_board_summary(
        self,
        board_id: str,
        port: _SerialPortInfo | None,
        connected: bool,
    ) -> Esp32BoardSummary:
        workspace_dir = self._workspace_dir_for_board_id(board_id)
        metadata = self._load_board_metadata(workspace_dir) if workspace_dir.exists() else {}
        blueprints, errors = self._load_blueprints(workspace_dir) if workspace_dir.exists() else ([], [])

        return Esp32BoardSummary(
            board_id=board_id,
            display_name=str(
                metadata.get("display_name")
                or (f"ESP32 {Path(port.device).name}" if port else f"ESP32 {board_id}")
            ),
            port=port.device if port else self._coerce_nullable_string(metadata.get("port")),
            connected=connected,
            description=(port.description if port else self._coerce_nullable_string(metadata.get("description"))),
            hardware_id=(port.hardware_id if port else self._coerce_nullable_string(metadata.get("hardware_id"))),
            serial_number=(port.serial_number if port else self._coerce_nullable_string(metadata.get("serial_number"))),
            workspace_path=str(workspace_dir),
            generated_function_ids=[blueprint.manifest.id for blueprint in blueprints],
            errors=errors,
        )

    def _coerce_nullable_string(self, value: object) -> str | None:
        return value if isinstance(value, str) and value.strip() else None

    def _load_blueprints(self, workspace_dir: Path) -> tuple[list[Esp32FunctionBlueprint], list[str]]:
        blueprint_dir = workspace_dir / "workflow-functions"
        if not blueprint_dir.exists():
            return [], []

        blueprints: list[Esp32FunctionBlueprint] = []
        errors: list[str] = []

        for blueprint_path in sorted(blueprint_dir.glob("*.json")):
            try:
                blueprint = Esp32FunctionBlueprint.model_validate_json(
                    blueprint_path.read_text(encoding="utf-8")
                )
            except Exception as exc:
                errors.append(f"{blueprint_path.name}: {exc}")
                continue

            blueprint.source_path = str(blueprint_path)
            blueprints.append(blueprint)

        return blueprints, errors

    def _validate_blueprint_content(self, content: str) -> None:
        try:
            Esp32FunctionBlueprint.model_validate_json(content)
        except Exception as exc:  # pragma: no cover - validation boundary
            raise Esp32BuilderError(f"Blueprint JSON is invalid: {exc}") from exc

    def _editable_files(self, workspace_dir: Path) -> list[Path]:
        editable_files: list[Path] = []
        for path in sorted(workspace_dir.rglob("*")):
            if not path.is_file():
                continue

            if path.name.startswith("."):
                continue

            if path.suffix.lower() not in {".ino", ".json", ".md", ".txt", ".py"}:
                continue

            editable_files.append(path)

        return editable_files

    def _read_workspace_file(self, path: Path, workspace_dir: Path) -> Esp32BuilderFile:
        relative_path = str(path.relative_to(workspace_dir))
        content = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()
        language_map = {
            ".ino": "cpp",
            ".json": "json",
            ".md": "markdown",
            ".txt": "text",
            ".py": "python",
        }

        return Esp32BuilderFile(
            relative_path=relative_path,
            absolute_path=str(path),
            language=language_map.get(suffix, "text"),
            editable=True,
            size_bytes=path.stat().st_size,
            content=content,
        )

    def _list_serial_ports(self) -> list[_SerialPortInfo]:
        try:
            from serial.tools import list_ports  # type: ignore

            ports = []
            for port in list_ports.comports():
                if not (str(port.device).startswith("/dev/ttyUSB") or str(port.device).startswith("/dev/ttyACM")):
                    continue

                ports.append(
                    _SerialPortInfo(
                        device=str(port.device),
                        description=getattr(port, "description", None),
                        hardware_id=getattr(port, "hwid", None),
                        serial_number=getattr(port, "serial_number", None),
                    )
                )

            if ports:
                return sorted(ports, key=lambda item: item.device)
        except Exception:
            pass

        fallback_ports = sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))
        return [_SerialPortInfo(device=port) for port in fallback_ports]

    def _default_workspace_notes(self, port: _SerialPortInfo) -> str:
        return (
            f"# ESP32 Workspace Notes\n\n"
            f"- Port: `{port.device}`\n"
            f"- Display: `{port.description or 'ESP32 board'}`\n"
            f"- This folder stores the local source files and block blueprint metadata that the Pi UI edits.\n"
            f"- Editing these files does not flash the board yet. It updates the local firmware workspace and generated workflow block definition.\n"
        )

    def _instructions_markdown(self) -> str:
        return """# ESP32 Function Builder Structure

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

- `board.json`: metadata for the connected board, including the active serial port.
- `firmware/main.ino`: the local Arduino source associated with that board.
- `workflow-functions/*.json`: block blueprints that generate workflow block manifests for the editor.

## Workflow function blueprint format

Each file under `workflow-functions/` should look like:

```json
{
  "manifest": {
    "id": "dispense",
    "display_name": "Dispense Syringe Batch",
    "category": "Robot Actions",
    "description": "High-level syringe dispense action.",
    "version": "0.1.0",
    "inputs": [
      {
        "key": "tool_port",
        "label": "ESP32 Port",
        "type": "file/path",
        "required": false,
        "default": "/dev/ttyUSB0"
      }
    ],
    "outputs": [
      {
        "key": "status",
        "label": "Status",
        "type": "string"
      }
    ]
  },
  "advanced_builder_inputs": [
    {
      "key": "step_pins",
      "label": "Step Pins",
      "type": "string",
      "required": false,
      "default": "33,25,26,27,14,12,13"
    }
  ],
  "firmware_entry_file": "firmware/main.ino",
  "protocol": "serial-text"
}
```

## How blocks are generated

- The Pi scans every `workflow-functions/*.json` blueprint.
- The blueprint's `manifest` section is written into `backend/app/functions/<id>/manifest.json`.
- If the function folder does not exist yet, the Pi creates a placeholder `handler.py` and `requirements.txt`.
- The workflow editor then discovers that manifest through the normal `/api/functions` endpoint.

## Recommended split

- Put normal runtime parameters in `manifest.inputs`.
- Put firmware wiring and board-specific tuning in `advanced_builder_inputs`.
- Keep source code changes in `firmware/main.ino`.
"""

    def _generated_placeholder_handler(self, function_id: str) -> str:
        return (
            "def execute(context: dict, inputs: dict) -> dict:\n"
            "    return {\n"
            '        "status": "not_implemented",\n'
            f'        "message": "Execution for generated ESP32 function \'{function_id}\' is not implemented yet.",\n'
            '        "inputs": inputs,\n'
            '        "mode": context.get("mode"),\n'
            "    }\n"
        )

    def _default_dispense_blueprint(self, port: str) -> dict[str, object]:
        return {
            "manifest": {
                "id": "dispense",
                "display_name": "Dispense Syringe Batch",
                "category": "Robot Actions",
                "description": "High-level syringe dispense action for the 7-head ESP32 syringe tool.",
                "version": "0.2.0",
                "inputs": [
                    {
                        "key": "tool_port",
                        "label": "ESP32 Port",
                        "type": "file/path",
                        "description": "Serial device path for the connected ESP32 syringe board.",
                        "required": False,
                        "default": port,
                        "placeholder": port,
                    },
                    {
                        "key": "calibration_file",
                        "label": "Calibration File",
                        "type": "file/path",
                        "description": "Calibration file used to convert dispense amounts into syringe motor steps.",
                        "required": True,
                        "default": str(self._repo_root / "functions" / "syringe control code" / "calibration.json"),
                        "placeholder": "/path/to/calibration.json",
                    },
                    {
                        "key": "speed",
                        "label": "Dispense Speed",
                        "type": "number",
                        "description": "Optional syringe speed to apply on the ESP32 before dispensing.",
                        "required": False,
                        "default": 100,
                    },
                    *[
                        {
                            "key": head,
                            "label": f"Head {head}",
                            "type": "number",
                            "description": f"Requested dispense amount for syringe head {head}.",
                            "required": True,
                            "default": 0,
                        }
                        for head in ("A", "B", "C", "D", "E", "F", "G")
                    ],
                ],
                "outputs": [
                    {
                        "key": "status",
                        "label": "Status",
                        "type": "string",
                        "description": "High-level status for the dispense request.",
                    },
                    {
                        "key": "reply",
                        "label": "Controller Reply",
                        "type": "string",
                        "description": "Raw serial reply returned by the ESP32 firmware.",
                    },
                ],
            },
            "advanced_builder_inputs": [
                {
                    "key": "spr",
                    "label": "Steps Per Revolution",
                    "type": "number",
                    "description": "Motor steps per full revolution used in the firmware.",
                    "required": False,
                    "default": 200,
                },
                {
                    "key": "rpm_default",
                    "label": "Default RPM",
                    "type": "number",
                    "description": "Default RPM used when no speed override is sent from the workflow.",
                    "required": False,
                    "default": 100,
                },
                {
                    "key": "microsteps",
                    "label": "Microsteps",
                    "type": "number",
                    "description": "Default microstep configuration passed to the A4988 driver.",
                    "required": False,
                    "default": 1,
                },
                {
                    "key": "step_pins",
                    "label": "Step Pins",
                    "type": "string",
                    "description": "Comma-separated GPIO pins for the seven step pins.",
                    "required": False,
                    "default": "33,25,26,27,14,12,13",
                },
                {
                    "key": "dir_pins",
                    "label": "Direction Pins",
                    "type": "string",
                    "description": "Comma-separated GPIO pins for the seven direction pins.",
                    "required": False,
                    "default": "32,4,5,18,19,21,22",
                },
                {
                    "key": "dir_signs",
                    "label": "Direction Signs",
                    "type": "string",
                    "description": "Comma-separated direction multipliers for the seven syringes.",
                    "required": False,
                    "default": "-1,-1,-1,-1,-1,-1,-1",
                },
            ],
            "firmware_entry_file": "firmware/main.ino",
            "protocol": "serial-text",
            "notes": "Basic runtime inputs are written to the workflow block. Advanced builder inputs describe firmware-level tuning and pin mapping.",
        }

    def _default_syringe_firmware(self) -> str:
        return """#include <Arduino.h>
#include "A4988.h"

const int NUM_SYRINGES = 7;
const int spr = 200;
int RPM = 100;
int Microsteps = 1;

int stepPins[NUM_SYRINGES] = {33, 25, 26, 27, 14, 12, 13};
int dirPins[NUM_SYRINGES]  = {32, 4, 5, 18, 19, 21, 22};

int dirSign[NUM_SYRINGES] = {-1, -1, -1, -1, -1, -1, -1};

A4988 stepper0(spr, dirPins[0], stepPins[0]);
A4988 stepper1(spr, dirPins[1], stepPins[1]);
A4988 stepper2(spr, dirPins[2], stepPins[2]);
A4988 stepper3(spr, dirPins[3], stepPins[3]);
A4988 stepper4(spr, dirPins[4], stepPins[4]);
A4988 stepper5(spr, dirPins[5], stepPins[5]);
A4988 stepper6(spr, dirPins[6], stepPins[6]);

A4988* steppers[NUM_SYRINGES] = {
  &stepper0, &stepper1, &stepper2, &stepper3,
  &stepper4, &stepper5, &stepper6
};

void applyRPM(int nextRPM) {
  if (nextRPM <= 0) {
    return;
  }

  RPM = nextRPM;
  for (int i = 0; i < NUM_SYRINGES; i++) {
    steppers[i]->begin(RPM, Microsteps);
  }

  Serial.print("OK SPEED ");
  Serial.println(RPM);
}

void dispenseSteps(long s0, long s1, long s2, long s3, long s4, long s5, long s6) {
  long steps[NUM_SYRINGES] = {s0, s1, s2, s3, s4, s5, s6};

  for (int i = 0; i < NUM_SYRINGES; i++) {
    if (steps[i] != 0) {
      steppers[i]->move(dirSign[i] * steps[i]);
      delay(100);
      steppers[i]->move(-dirSign[i] * steps[i]);

      Serial.print("SYRINGE ");
      Serial.print(i);
      Serial.println(" DONE");
    }
  }

  Serial.println("OK DISPENSE");
}

bool handleSpeedCommand(const String& cmd) {
  long nextRPM = 0;

  if (cmd.startsWith("SPEED ")) {
    int parsed = sscanf(cmd.c_str(), "SPEED %ld", &nextRPM);
    if (parsed == 1) {
      applyRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SPEED,")) {
    int parsed = sscanf(cmd.c_str(), "SPEED,%ld", &nextRPM);
    if (parsed == 1) {
      applyRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SET_SPEED,")) {
    int parsed = sscanf(cmd.c_str(), "SET_SPEED,%ld", &nextRPM);
    if (parsed == 1) {
      applyRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SET SPEED ")) {
    int parsed = sscanf(cmd.c_str(), "SET SPEED %ld", &nextRPM);
    if (parsed == 1) {
      applyRPM((int)nextRPM);
      return true;
    }
  }

  return false;
}

void setup() {
  Serial.begin(115200);

  for (int i = 0; i < NUM_SYRINGES; i++) {
    pinMode(stepPins[i], OUTPUT);
    pinMode(dirPins[i], OUTPUT);
    steppers[i]->begin(RPM, Microsteps);
  }

  Serial.println("READY");
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\\n');
    cmd.trim();

    if (cmd.startsWith("DISPENSE ")) {
      long s[NUM_SYRINGES] = {0, 0, 0, 0, 0, 0, 0};

      int parsed = sscanf(
        cmd.c_str(),
        "DISPENSE %ld %ld %ld %ld %ld %ld %ld",
        &s[0], &s[1], &s[2], &s[3], &s[4], &s[5], &s[6]
      );

      if (parsed == 7) {
        dispenseSteps(s[0], s[1], s[2], s[3], s[4], s[5], s[6]);
      } else {
        Serial.println("ERR BAD DISPENSE CMD");
      }
    }
    else if (handleSpeedCommand(cmd)) {
      // speed command handled above
    }
    else if (cmd == "PING") {
      Serial.println("PONG");
    }
    else {
      Serial.println("ERR UNKNOWN CMD");
    }
  }
}
"""


esp32_builder_service = Esp32BuilderService(
    repo_root=Path(__file__).resolve().parents[3],
    app_functions_dir=Path(__file__).resolve().parent.parent / "functions",
)
