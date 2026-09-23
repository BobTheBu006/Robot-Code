import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.models.function_manifest import FunctionManifest
from app.models.hardware_map import (
    HardwareBoardConnectionStatus,
    HardwareBoardMapping,
    HardwareConnectorMapping,
    HardwareConnectorPin,
    HardwareDeviceMapping,
    HardwareGroupMapping,
    HardwareMap,
    HardwareMapSaveResponse,
    HardwarePinMapping,
)
from app.services.serial_ports import list_serial_ports


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
    def __init__(self, hardware_map_path: Path, active_connector_groups=None) -> None:
        self._hardware_map_path = hardware_map_path
        # Which tool groups are docked on a connector right now. Injected so
        # tests do not read the machine's connector state.
        self._active_connector_groups = active_connector_groups

    def active_connector_group_ids(self) -> set[str]:
        if self._active_connector_groups is not None:
            return set(self._active_connector_groups())
        from app.services.pogo_connector import connector_state_store

        return connector_state_store.active_group_ids()

    def _group_covers(self, group: HardwareGroupMapping, device: HardwareDeviceMapping) -> bool:
        return device.id in group.member_ids or bool(device.board_id and device.board_id in group.member_ids)

    def _undocked_tool_group(
        self,
        hardware_map: HardwareMap,
        device: HardwareDeviceMapping,
        active_group_ids: set[str] | None = None,
    ) -> HardwareGroupMapping | None:
        """The connector tool this device belongs to, if that tool is not the
        one docked. Hardware on an absent tool must not be driven: its pins are
        wired to whatever tool *is* on the head."""
        tool_groups = [
            group for group in hardware_map.groups if group.connector_id and self._group_covers(group, device)
        ]
        if not tool_groups:
            return None
        active = self.active_connector_group_ids() if active_group_ids is None else active_group_ids
        if any(group.id in active for group in tool_groups):
            return None
        return tool_groups[0]

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

    def _sync_device_enabled_with_groups(self, hardware_map: HardwareMap) -> HardwareMap:
        """A device's stored enabled flag always mirrors the board and any
        hardware groups it belongs to - turning a board or group off shows
        every device under it as off, and turning it back on shows them all
        as on again, like a breaker cutting power to everything downstream.
        No per-device override survives independent of its board/group: if a
        specific device needs to stay off, that has to be set again after the
        board or group is re-enabled.
        """
        board_enabled = {board.id: board.enabled for board in hardware_map.boards}

        # Resolve every group to the concrete set of device ids it covers,
        # since a group's member_ids can list board ids to cover every device
        # on that board without naming each one.
        group_disabled_device_ids: set[str] = set()
        for group in hardware_map.groups:
            if group.enabled:
                continue
            for device in hardware_map.devices:
                if device.id in group.member_ids or (device.board_id and device.board_id in group.member_ids):
                    group_disabled_device_ids.add(device.id)

        updated_devices = []
        changed = False
        for device in hardware_map.devices:
            target_enabled = board_enabled.get(device.board_id, device.enabled)
            if device.id in group_disabled_device_ids:
                target_enabled = False
            if target_enabled != device.enabled:
                device = device.model_copy(update={"enabled": target_enabled})
                changed = True
            updated_devices.append(device)

        if not changed:
            return hardware_map
        return hardware_map.model_copy(update={"devices": updated_devices})

    def save_map(self, hardware_map: HardwareMap) -> HardwareMapSaveResponse:
        hardware_map = self._sync_device_enabled_with_groups(hardware_map)
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

    def verify_board_connection(self, board_id: str) -> HardwareBoardConnectionStatus:
        """Check whether the physical device on a board's usb_port is the one
        expected — used by the "Connect controller"/"Disconnect controller"
        workflow blocks to catch a missed or wrong USB swap before a workflow
        acts on the wrong hardware.
        """
        hardware_map = self.load_map()
        board = next((candidate for candidate in hardware_map.boards if candidate.id == board_id), None)
        if board is None:
            raise HardwareMapError(f"Unknown controller '{board_id}' in the hardware map.")

        live_ports = {port.device: port for port in list_serial_ports()}
        live_port = live_ports.get(board.usb_port)
        detected_serial_number = live_port.serial_number if live_port else None
        detected_hardware_id = live_port.hardware_id if live_port else None
        connected = live_port is not None

        if not board.dynamic:
            # Non-dynamic controllers are expected to just always be there;
            # presence on the port is enough, there's no identity to compare.
            matched = connected
            message = (
                f"{board.label} is connected on {board.usb_port}."
                if connected
                else f"Nothing is connected on {board.usb_port} (expected {board.label})."
            )
            return HardwareBoardConnectionStatus(
                board_id=board.id,
                label=board.label,
                usb_port=board.usb_port,
                dynamic=board.dynamic,
                expected_serial_number=board.expected_serial_number,
                detected_serial_number=detected_serial_number,
                detected_hardware_id=detected_hardware_id,
                connected=connected,
                matched=matched,
                message=message,
            )

        if not board.expected_serial_number:
            raise HardwareMapError(
                f"{board.label} is marked as dynamically connected but has no expected device identity "
                "captured yet. Open it in the Hardware Map and capture the currently connected device first."
            )

        if not connected:
            message = f"Nothing is connected on {board.usb_port} (expected {board.label})."
        elif detected_serial_number and detected_serial_number == board.expected_serial_number:
            message = f"{board.label} is connected on {board.usb_port}."
        elif detected_serial_number:
            message = (
                f"The device on {board.usb_port} does not match {board.label} "
                f"(expected serial {board.expected_serial_number}, found {detected_serial_number})."
            )
        else:
            message = (
                f"The device on {board.usb_port} does not report a USB serial number, "
                f"so it cannot be confirmed as {board.label}."
            )

        matched = connected and detected_serial_number is not None and detected_serial_number == board.expected_serial_number

        return HardwareBoardConnectionStatus(
            board_id=board.id,
            label=board.label,
            usb_port=board.usb_port,
            dynamic=board.dynamic,
            expected_serial_number=board.expected_serial_number,
            detected_serial_number=detected_serial_number,
            detected_hardware_id=detected_hardware_id,
            connected=connected,
            matched=matched,
            message=message,
        )

    def sync_manifest_devices(self, manifests: list[FunctionManifest]) -> HardwareMap:
        hardware_map = self.load_map()
        devices = list(hardware_map.devices)
        changed = False

        for manifest in manifests:
            if not manifest.hardware_devices:
                continue

            input_defaults = self._input_defaults(manifest)

            for device_reference in manifest.hardware_devices:
                if self._assigned_device_for_manifest_device(hardware_map, manifest.id, device_reference.id):
                    continue

                next_device = HardwareDeviceMapping(
                    id=device_reference.id,
                    board_id="",
                    name=device_reference.name,
                    kind=device_reference.kind,
                    enabled=False,
                    sensor_kind=device_reference.sensor_kind,
                    rotation_min_deg=device_reference.rotation_min_deg,
                    rotation_max_deg=device_reference.rotation_max_deg,
                    calibration_ml_per_200_steps=device_reference.calibration_ml_per_200_steps,
                    pins=[
                        HardwarePinMapping(
                            id=pin.id,
                            signal=pin.signal,
                            gpio=self._pin_gpio_from_reference(pin.gpio, pin.function_input_key, input_defaults),
                            function_input_key=pin.function_input_key,
                            notes=pin.notes,
                        )
                        for pin in device_reference.pins
                    ],
                    notes=device_reference.notes,
                )
                device_index = next((index for index, device in enumerate(devices) if device.id == next_device.id), None)
                if device_index is None:
                    devices.append(next_device)
                    changed = True
                    continue

                merged_device = self._merge_device(devices[device_index], next_device)
                if merged_device.model_dump() != devices[device_index].model_dump():
                    devices[device_index] = merged_device
                    changed = True

        if not changed:
            return hardware_map

        return self.save_map(
            hardware_map.model_copy(update={"devices": devices})
        ).hardware_map

    def apply_function_defaults(
        self,
        manifest: FunctionManifest,
        inputs: dict[str, str | float | bool | None],
    ) -> dict[str, str | float | bool | None]:
        hardware_map = self.load_map()
        disabled_reasons = self._disabled_dependency_reasons(hardware_map, manifest)
        if disabled_reasons:
            raise HardwareMapError("Hardware disabled: " + " ".join(disabled_reasons))

        resolved_inputs = dict(inputs)
        input_keys = {input_definition.key for input_definition in [*manifest.inputs, *manifest.advanced_inputs]}

        if "tool_port" in input_keys and not resolved_inputs.get("tool_port"):
            board = self._board_for_manifest(hardware_map, manifest)
            if board:
                resolved_inputs["tool_port"] = board.usb_port

        pins_by_input_key = {
            pin.function_input_key: pin.gpio
            for device in self._resolved_manifest_devices(hardware_map, manifest)
            for pin in device.pins
            if self._device_is_enabled(hardware_map, device)
            and device.board_id
            and pin.function_input_key
            and pin.gpio != "-"
            and pin.signal != "-"
        }

        for input_key in input_keys:
            if input_key == "tool_port" or "pin" not in input_key:
                continue
            if input_key in pins_by_input_key:
                resolved_inputs[input_key] = pins_by_input_key[input_key]

        return resolved_inputs

    def _board_for_manifest(self, hardware_map: HardwareMap, manifest: FunctionManifest) -> HardwareBoardMapping | None:
        mapped_board_ids = {
            device.board_id
            for device in self._resolved_manifest_devices(hardware_map, manifest)
            if self._device_is_enabled(hardware_map, device) and device.board_id
        }
        if len(mapped_board_ids) == 1:
            mapped_board_id = next(iter(mapped_board_ids))
            if mapped_board_id == "raspberry-pi":
                return None

            for board in hardware_map.boards:
                if board.id == mapped_board_id and board.enabled:
                    return board

        if manifest.builder_board_id:
            for board in hardware_map.boards:
                if board.id == manifest.builder_board_id and board.enabled:
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
                if board.usb_port == str(default_port) and board.enabled:
                    return board

        return next((board for board in hardware_map.boards if board.enabled), None)

    def _device_is_enabled(self, hardware_map: HardwareMap, device: HardwareDeviceMapping) -> bool:
        if not device.enabled:
            return False

        if device.board_id and device.board_id != "raspberry-pi":
            board = next((candidate for candidate in hardware_map.boards if candidate.id == device.board_id), None)
            if board and not board.enabled:
                return False

        for group in hardware_map.groups:
            if not group.enabled and device.id in group.member_ids:
                return False
            if not group.enabled and device.board_id and device.board_id in group.member_ids:
                return False

        if self._undocked_tool_group(hardware_map, device) is not None:
            return False

        return True

    def _disabled_dependency_reasons(self, hardware_map: HardwareMap, manifest: FunctionManifest) -> list[str]:
        reasons: list[str] = []
        for device_reference in manifest.hardware_devices:
            device = self._resolve_manifest_device(hardware_map, manifest.id, device_reference.id)
            if not device:
                continue
            if not self._device_is_enabled(hardware_map, device):
                tool = self._undocked_tool_group(hardware_map, device)
                if tool is not None:
                    reasons.append(
                        f"{manifest.display_name} requires {device.name}, which is on tool '{tool.name}', "
                        "but that tool is not connected. Pick it up or add a Connect Tool block first."
                    )
                    continue
                reasons.append(f"{manifest.display_name} requires {device.name}, but it is disabled in the Hardware Map.")
        return reasons

    def _assignment_for(
        self,
        hardware_map: HardwareMap,
        function_id: str,
        device_id: str,
    ):
        return next(
            (
                assignment
                for assignment in hardware_map.function_assignments
                if assignment.function_id == function_id and assignment.device_id == device_id
            ),
            None,
        )

    def _assigned_device_for_manifest_device(
        self,
        hardware_map: HardwareMap,
        function_id: str,
        device_id: str,
    ) -> HardwareDeviceMapping | None:
        assignment = self._assignment_for(hardware_map, function_id, device_id)
        if not assignment or not assignment.hardware_device_id:
            return None

        return next(
            (
                device
                for device in hardware_map.devices
                if device.id == assignment.hardware_device_id
            ),
            None,
        )

    def _resolve_manifest_device(
        self,
        hardware_map: HardwareMap,
        function_id: str,
        device_id: str,
    ) -> HardwareDeviceMapping | None:
        return self._assigned_device_for_manifest_device(hardware_map, function_id, device_id) or next(
            (
                device
                for device in hardware_map.devices
                if device.id == device_id
            ),
            None,
        )

    def _resolved_manifest_devices(
        self,
        hardware_map: HardwareMap,
        manifest: FunctionManifest,
    ) -> list[HardwareDeviceMapping]:
        devices: list[HardwareDeviceMapping] = []
        seen_device_ids: set[str] = set()
        for device_reference in manifest.hardware_devices:
            device = self._resolve_manifest_device(hardware_map, manifest.id, device_reference.id)
            if device and device.id not in seen_device_ids:
                devices.append(device)
                seen_device_ids.add(device.id)
        return devices

    def _input_defaults(self, manifest: FunctionManifest) -> dict[str, str]:
        defaults: dict[str, str] = {}
        for input_definition in [*manifest.inputs, *manifest.advanced_inputs]:
            if input_definition.default not in {None, ""}:
                defaults[input_definition.key] = str(input_definition.default)
        return defaults

    def _board_id_for_device_reference(
        self,
        hardware_map: HardwareMap,
        manifest: FunctionManifest,
        requested_board_id: str | None,
    ) -> str:
        if requested_board_id:
            return requested_board_id

        if manifest.builder_board_id:
            return manifest.builder_board_id

        board = self._board_for_manifest(hardware_map, manifest)
        if board:
            return board.id

        return f"{manifest.id}-controller"

    def _ensure_board(
        self,
        boards: list[HardwareBoardMapping],
        board_id: str,
        manifest: FunctionManifest,
        default_port: str | None,
    ) -> tuple[HardwareBoardMapping, bool]:
        if board_id == "raspberry-pi":
            return HardwareBoardMapping(
                id="raspberry-pi",
                label="Raspberry Pi",
                usb_port="GPIO/I2C",
                notes="Virtual controller for devices wired directly to Raspberry Pi GPIO or I2C.",
            ), False

        existing_board = next((board for board in boards if board.id == board_id), None)
        if existing_board:
            return existing_board, False

        usb_port = default_port or (f"/dev/{board_id}" if board_id.startswith(("tty", "ttyUSB", "ttyACM")) else "-")
        board = HardwareBoardMapping(
            id=board_id,
            label=f"{manifest.display_name} Controller",
            usb_port=usb_port,
            notes=f"Auto-created because {manifest.display_name} declares hardware devices.",
        )
        boards.append(board)
        return board, True

    def _pin_gpio_from_reference(
        self,
        gpio: str | float | None,
        function_input_key: str | None,
        input_defaults: dict[str, str],
    ) -> str:
        if gpio not in {None, ""}:
            return self._stringify_gpio(gpio)

        if function_input_key and function_input_key in input_defaults:
            return self._stringify_gpio(input_defaults[function_input_key])

        return "-"

    def _stringify_gpio(self, value: str | float) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))

        string_value = str(value)
        if string_value.endswith(".0"):
            return string_value[:-2]

        return string_value

    def _merge_device(
        self,
        existing_device: HardwareDeviceMapping,
        next_device: HardwareDeviceMapping,
    ) -> HardwareDeviceMapping:
        existing_pins = list(existing_device.pins)
        merged_pins = list(existing_pins)

        for next_pin in next_device.pins:
            pin_index = next(
                (
                    index
                    for index, existing_pin in enumerate(merged_pins)
                    if existing_pin.id == next_pin.id
                    or (
                        next_pin.function_input_key
                        and existing_pin.function_input_key == next_pin.function_input_key
                    )
                    or existing_pin.signal == next_pin.signal
                ),
                None,
            )
            if pin_index is None:
                merged_pins.append(next_pin)
                continue

            existing_pin = merged_pins[pin_index]
            gpio = existing_pin.gpio
            if gpio in {"", "-"} and next_pin.gpio not in {"", "-"}:
                gpio = next_pin.gpio

            merged_pins[pin_index] = existing_pin.model_copy(update={
                "id": existing_pin.id or next_pin.id,
                "signal": next_pin.signal,
                "gpio": gpio,
                "function_input_key": next_pin.function_input_key or existing_pin.function_input_key,
                "notes": existing_pin.notes or next_pin.notes,
            })

        return existing_device.model_copy(update={
            "board_id": existing_device.board_id or next_device.board_id,
            "name": existing_device.name or next_device.name,
            "kind": next_device.kind,
            "sensor_kind": next_device.sensor_kind,
            "rotation_min_deg": existing_device.rotation_min_deg if existing_device.rotation_min_deg is not None else next_device.rotation_min_deg,
            "rotation_max_deg": existing_device.rotation_max_deg if existing_device.rotation_max_deg is not None else next_device.rotation_max_deg,
            "calibration_ml_per_200_steps": (
                existing_device.calibration_ml_per_200_steps
                if existing_device.calibration_ml_per_200_steps is not None
                else next_device.calibration_ml_per_200_steps
            ),
            "pins": merged_pins,
            "notes": existing_device.notes or next_device.notes,
        })

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
        peristaltic_pumps = [
            ("beads-medium-pump", "Beads Medium Pump", "beads_medium_pump"),
            ("beads-creation-pump", "Beads Creation Pump", "beads_creation_pump"),
            ("beads-solution-pump", "Beads Solution Pump", "beads_solution_pump"),
        ]
        peristaltic_pump_devices = [
            HardwareDeviceMapping(
                id=pump_id,
                board_id=syringe_board.id,
                name=pump_name,
                kind="stepper_motor",
                calibration_ml_per_200_steps=1.0,
                pins=[
                    _pin(f"{pump_id}-dir", "direction", "-", f"{input_prefix}_dir_pin"),
                    _pin(f"{pump_id}-step", "step", "-", f"{input_prefix}_step_pin"),
                    _pin(f"{pump_id}-enable", "enable", "-", None),
                    _pin(f"{pump_id}-ms1", "micro_step_1", "-", None),
                    _pin(f"{pump_id}-ms2", "micro_step_2", "-", None),
                    _pin(f"{pump_id}-ms3", "micro_step_3", "-", None),
                ],
                notes="Peristaltic pump stepper. Calibrate by entering mL per 200 full steps.",
            )
            for pump_id, pump_name, input_prefix in peristaltic_pumps
        ]

        gantry_devices = [
            HardwareDeviceMapping(
                id="x-axis-motor",
                board_id="raspberry-pi",
                name="CoreXY A Motor",
                kind="stepper_motor",
                pins=[
                    _pin("x-dir", "direction", 27, "x_dir_pin"),
                    _pin("x-step", "step", 17, "x_step_pin"),
                    _pin("x-enable", "enable", "-", None),
                    _pin("x-ms1", "micro_step_1", "-", None),
                    _pin("x-ms2", "micro_step_2", "-", None),
                    _pin("x-ms3", "micro_step_3", "-", None),
                ],
                notes="Stable ID kept for compatibility; this is CoreXY motor A, not an independent X-only gantry motor.",
            ),
            HardwareDeviceMapping(
                id="y-axis-motor",
                board_id="raspberry-pi",
                name="CoreXY B Motor",
                kind="stepper_motor",
                pins=[
                    _pin("y-dir", "direction", 24, "y_dir_pin"),
                    _pin("y-step", "step", 23, "y_step_pin"),
                    _pin("y-enable", "enable", "-", None),
                    _pin("y-ms1", "micro_step_1", "-", None),
                    _pin("y-ms2", "micro_step_2", "-", None),
                    _pin("y-ms3", "micro_step_3", "-", None),
                ],
                notes="Stable ID kept for compatibility; this is CoreXY motor B, not an independent Y-only gantry motor.",
            ),
            HardwareDeviceMapping(
                id="left-z-motor",
                board_id=gantry_board.id,
                name="Z Axis Motor",
                kind="stepper_motor",
                pins=[
                    _pin("z-left-dir", "direction", 33, "z_left_dir_pin"),
                    _pin("z-left-step", "step", 32, "z_left_step_pin"),
                    _pin("z-left-enable", "enable", "-", None),
                    _pin("z-left-ms1", "micro_step_1", "-", None),
                    _pin("z-left-ms2", "micro_step_2", "-", None),
                    _pin("z-left-ms3", "micro_step_3", "-", None),
                ],
                notes="Single Z axis motor. Stable legacy ID kept for compatibility.",
            ),
            HardwareDeviceMapping(
                id="right-z-motor",
                board_id="",
                name="Legacy Right Z Motor",
                kind="stepper_motor",
                pins=[
                    _pin("z-right-dir", "direction", 5, "z_right_dir_pin"),
                    _pin("z-right-step", "step", 4, "z_right_step_pin"),
                    _pin("z-right-enable", "enable", "-", None),
                    _pin("z-right-ms1", "micro_step_1", "-", None),
                    _pin("z-right-ms2", "micro_step_2", "-", None),
                    _pin("z-right-ms3", "micro_step_3", "-", None),
                ],
                notes="Legacy placeholder for older dual-Z maps. Leave unconnected for the current single-Z CoreXY robot.",
            ),
            HardwareDeviceMapping(
                id="x-min-limit-switch",
                board_id="raspberry-pi",
                name="X Min Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("x-min-limit", "signal", 5, "x_min_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="x-max-limit-switch",
                board_id="raspberry-pi",
                name="X Max Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("x-max-limit", "signal", 6, "x_max_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="y-min-limit-switch",
                board_id="raspberry-pi",
                name="Y Min Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("y-min-limit", "signal", 12, "y_min_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="y-max-limit-switch",
                board_id="raspberry-pi",
                name="Y Max Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("y-max-limit", "signal", 13, "y_max_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="z-left-min-limit-switch",
                board_id=gantry_board.id,
                name="Z Min Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("z-left-min-limit", "signal", 12, "z_left_min_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="z-left-max-limit-switch",
                board_id=gantry_board.id,
                name="Z Max Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("z-left-max-limit", "signal", 13, "z_left_max_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="z-right-min-limit-switch",
                board_id="",
                name="Legacy Right Z Min Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("z-right-min-limit", "signal", 14, "z_right_min_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="z-right-max-limit-switch",
                board_id="",
                name="Legacy Right Z Max Limit Switch",
                kind="sensor",
                sensor_kind="position_limit_switch",
                pins=[
                    _pin("z-right-max-limit", "signal", 15, "z_right_max_limit_pin"),
                ],
            ),
            HardwareDeviceMapping(
                id="raspberry-aht20",
                board_id="raspberry-pi",
                name="Raspberry AHT20 Temperature + Humidity",
                kind="sensor",
                sensor_kind="aht20_temperature_humidity",
                pins=[
                    HardwarePinMapping(
                        id="raspberry-aht20-scl",
                        signal="scl",
                        gpio="3",
                        notes="Raspberry Pi I2C SCL1.",
                    ),
                    HardwarePinMapping(
                        id="raspberry-aht20-sda",
                        signal="sda",
                        gpio="2",
                        notes="Raspberry Pi I2C SDA1.",
                    ),
                ],
                notes="AHT20 development board connected directly to Raspberry Pi I2C.",
            ),
        ]

        return HardwareMap(
            version=1,
            boards=[syringe_board, gantry_board],
            devices=[*syringe_devices, *peristaltic_pump_devices, *gantry_devices],
            connectors=[default_pogo_connector()],
            updated_at=None,
        )


def default_pogo_connector() -> HardwareConnectorMapping:
    """The toolhead's spring-pin connector as wired on this machine.

    GPIO numbers traced on the 12-pin cable; alternate functions measured on
    the Pi 5 with `pinctrl funcs` (a3 = I2C1, a4 = UART0 / /dev/ttyAMA0).
    """
    return HardwareConnectorMapping(
        id="pogo-connector",
        label="Pogo connector",
        pins=[
            HardwareConnectorPin(name="SDA", gpio="2", peripheral="i2c", alt_function="a3"),
            HardwareConnectorPin(name="SCL", gpio="3", peripheral="i2c", alt_function="a3"),
            HardwareConnectorPin(name="TXD", gpio="14", peripheral="uart", alt_function="a4"),
            HardwareConnectorPin(name="RXD", gpio="15", peripheral="uart", alt_function="a4"),
        ],
        usb_port="/dev/ttyUSB1",
        notes="USB is the port the 7-syringe pump (controller-x83xnc) uses.",
    )


hardware_map_service = HardwareMapService(
    hardware_map_path=Path(__file__).resolve().parents[3] / "hardware-map.json"
)
