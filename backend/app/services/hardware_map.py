import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.models.function_manifest import FunctionManifest
from app.models.hardware_map import (
    HardwareBoardMapping,
    HardwareDeviceMapping,
    HardwareMap,
    HardwareMapSaveResponse,
    HardwarePinMapping,
)


class HardwareMapError(RuntimeError):
    pass


def _pin(pin_id: str, signal: str, gpio: int | str, function_input_key: str | None = None) -> HardwarePinMapping:
    return HardwarePinMapping(
        id=pin_id,
        signal=signal,
        gpio=str(gpio),
        function_input_key=function_input_key,
    )


class HardwareMapService:
    def __init__(self, hardware_map_path: Path) -> None:
        self._hardware_map_path = hardware_map_path

    def load_map(self) -> HardwareMap:
        if not self._hardware_map_path.exists():
            return self._default_map()

        try:
            with self._hardware_map_path.open("r", encoding="utf-8") as hardware_map_file:
                payload = json.load(hardware_map_file)
            return HardwareMap.model_validate(payload)
        except json.JSONDecodeError as exc:
            raise HardwareMapError(
                f"hardware-map.json contains invalid JSON: {exc.msg}"
            ) from exc
        except ValidationError as exc:
            raise HardwareMapError(
                f"hardware-map.json failed validation: {exc.errors()[0]['msg']}"
            ) from exc

    def save_map(self, hardware_map: HardwareMap) -> HardwareMapSaveResponse:
        self._hardware_map_path.parent.mkdir(parents=True, exist_ok=True)
        saved_at = datetime.now(tz=timezone.utc)
        payload = hardware_map.model_copy(update={"version": 1, "updated_at": saved_at})

        with self._hardware_map_path.open("w", encoding="utf-8") as hardware_map_file:
            hardware_map_file.write(payload.model_dump_json(indent=2))
            hardware_map_file.write("\n")

        return HardwareMapSaveResponse(
            path=str(self._hardware_map_path),
            saved_at=saved_at,
            hardware_map=payload,
        )

    def apply_function_defaults(
        self,
        manifest: FunctionManifest,
        inputs: dict[str, str | float | bool | None],
    ) -> dict[str, str | float | bool | None]:
        hardware_map = self.load_map()
        resolved_inputs = dict(inputs)
        input_keys = {input_definition.key for input_definition in [*manifest.inputs, *manifest.advanced_inputs]}

        if "tool_port" in input_keys and not resolved_inputs.get("tool_port"):
            board = self._board_for_manifest(hardware_map, manifest)
            if board:
                resolved_inputs["tool_port"] = board.usb_port

        pins_by_input_key = {
            pin.function_input_key: pin.gpio
            for device in hardware_map.devices
            for pin in device.pins
            if pin.function_input_key and pin.gpio != "-" and pin.signal != "-"
        }

        for input_key in input_keys:
            if input_key == "tool_port" or "pin" not in input_key:
                continue
            if resolved_inputs.get(input_key) in {None, ""} and input_key in pins_by_input_key:
                resolved_inputs[input_key] = pins_by_input_key[input_key]

        return resolved_inputs

    def _board_for_manifest(self, hardware_map: HardwareMap, manifest: FunctionManifest) -> HardwareBoardMapping | None:
        if manifest.builder_board_id:
            for board in hardware_map.boards:
                if board.id == manifest.builder_board_id:
                    return board

        default_port = next(
            (
                input_definition.default
                for input_definition in [*manifest.inputs, *manifest.advanced_inputs]
                if input_definition.key == "tool_port"
            ),
            None,
        )
        if default_port:
            for board in hardware_map.boards:
                if board.usb_port == str(default_port):
                    return board

        return hardware_map.boards[0] if hardware_map.boards else None

    def _default_map(self) -> HardwareMap:
        syringe_board = HardwareBoardMapping(
            id="ttyUSB0",
            label="Syringe ESP32",
            usb_port="/dev/ttyUSB0",
            notes="Default syringe controller mapping. Edit this if the Pi assigns a different USB device.",
        )
        gantry_board = HardwareBoardMapping(
            id="ttyUSB1",
            label="Gantry ESP32",
            usb_port="/dev/ttyUSB1",
            notes="Default gantry controller mapping. Edit this if the Pi assigns a different USB device.",
        )

        syringe_heads = [
            ("a", "A", 33, 32),
            ("b", "B", 25, 4),
            ("c", "C", 26, 5),
            ("d", "D", 27, 18),
            ("e", "E", 14, 19),
            ("f", "F", 12, 21),
            ("g", "G", 13, 22),
        ]
        syringe_devices = [
            HardwareDeviceMapping(
                id=f"syringe-head-{head_key}",
                board_id=syringe_board.id,
                name=f"Syringe Head {head_label}",
                kind="stepper_motor",
                pins=[
                    _pin(f"head-{head_key}-dir", "direction", dir_pin, f"head_{head_key}_dir_pin"),
                    _pin(f"head-{head_key}-step", "step", step_pin, f"head_{head_key}_step_pin"),
                    _pin(f"head-{head_key}-enable", "enable", "-", None),
                    _pin(f"head-{head_key}-ms1", "micro_step_1", "-", None),
                    _pin(f"head-{head_key}-ms2", "micro_step_2", "-", None),
                    _pin(f"head-{head_key}-ms3", "micro_step_3", "-", None),
                ],
            )
            for head_key, head_label, step_pin, dir_pin in syringe_heads
        ]

        gantry_devices = [
            HardwareDeviceMapping(
                id="x-axis-motor",
                board_id=gantry_board.id,
                name="X Axis Motor",
                kind="stepper_motor",
                pins=[
                    _pin("x-dir", "direction", 17, "x_dir_pin"),
                    _pin("x-step", "step", 16, "x_step_pin"),
                    _pin("x-enable", "enable", "-", None),
                    _pin("x-ms1", "micro_step_1", "-", None),
                    _pin("x-ms2", "micro_step_2", "-", None),
                    _pin("x-ms3", "micro_step_3", "-", None),
                ],
            ),
            HardwareDeviceMapping(
                id="y-axis-motor",
                board_id=gantry_board.id,
                name="Y Axis Motor",
                kind="stepper_motor",
                pins=[
                    _pin("y-dir", "direction", 19, "y_dir_pin"),
                    _pin("y-step", "step", 18, "y_step_pin"),
                    _pin("y-enable", "enable", "-", None),
                    _pin("y-ms1", "micro_step_1", "-", None),
                    _pin("y-ms2", "micro_step_2", "-", None),
                    _pin("y-ms3", "micro_step_3", "-", None),
                ],
            ),
            HardwareDeviceMapping(
                id="left-z-motor",
                board_id=gantry_board.id,
                name="Left Z Motor",
                kind="stepper_motor",
                pins=[
                    _pin("z-left-dir", "direction", 17, "z_left_dir_pin"),
                    _pin("z-left-step", "step", 16, "z_left_step_pin"),
                    _pin("z-left-enable", "enable", "-", None),
                    _pin("z-left-ms1", "micro_step_1", "-", None),
                    _pin("z-left-ms2", "micro_step_2", "-", None),
                    _pin("z-left-ms3", "micro_step_3", "-", None),
                ],
            ),
            HardwareDeviceMapping(
                id="right-z-motor",
                board_id=gantry_board.id,
                name="Right Z Motor",
                kind="stepper_motor",
                pins=[
                    _pin("z-right-dir", "direction", 19, "z_right_dir_pin"),
                    _pin("z-right-step", "step", 18, "z_right_step_pin"),
                    _pin("z-right-enable", "enable", "-", None),
                    _pin("z-right-ms1", "micro_step_1", "-", None),
                    _pin("z-right-ms2", "micro_step_2", "-", None),
                    _pin("z-right-ms3", "micro_step_3", "-", None),
                ],
            ),
            HardwareDeviceMapping(
                id="x-min-limit-switch",
                board_id=gantry_board.id,
                name="X Min Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("x-min-limit", "signal", 21, "x_min_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="x-max-limit-switch",
                board_id=gantry_board.id,
                name="X Max Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("x-max-limit", "signal", 22, "x_max_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="y-min-limit-switch",
                board_id=gantry_board.id,
                name="Y Min Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("y-min-limit", "signal", 23, "y_min_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="y-max-limit-switch",
                board_id=gantry_board.id,
                name="Y Max Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("y-max-limit", "signal", 25, "y_max_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="z-left-min-limit-switch",
                board_id=gantry_board.id,
                name="Left Z Min Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("z-left-min-limit", "signal", 21, "z_left_min_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="z-left-max-limit-switch",
                board_id=gantry_board.id,
                name="Left Z Max Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("z-left-max-limit", "signal", 22, "z_left_max_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="z-right-min-limit-switch",
                board_id=gantry_board.id,
                name="Right Z Min Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("z-right-min-limit", "signal", 23, "z_right_min_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="z-right-max-limit-switch",
                board_id=gantry_board.id,
                name="Right Z Max Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("z-right-max-limit", "signal", 25, "z_right_max_limit_pin"),
                ],
            ),
        ]

        return HardwareMap(
            version=1,
            boards=[syringe_board, gantry_board],
            devices=[*syringe_devices, *gantry_devices],
            updated_at=None,
        )


hardware_map_service = HardwareMapService(
    hardware_map_path=Path(__file__).resolve().parents[3] / "hardware-map.json"
)
