"""The dynamic pogo connector: tools as Hardware Map groups, one active at a time.

What matters on the machine: a tool that cannot be confirmed fails loudly and
leaves the connector empty; hardware on a tool that is not docked cannot be
driven; and a pick-up hands the connector to the tool now on the head.
"""

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.controllers.preflight import ControllerPreflightResult, PreflightVerdict
from app.models.function_manifest import FunctionManifest
from app.models.hardware_map import (
    FunctionHardwareAssignment,
    HardwareBoardMapping,
    HardwareDeviceMapping,
    HardwareGroupMapping,
    HardwareMap,
    HardwarePinMapping,
)
from app.services.hardware_map import HardwareMapError, HardwareMapService, default_pogo_connector
from app.services.pogo_connector import (
    ConnectorError,
    ConnectorStateStore,
    PogoConnectorService,
    SimulatedPinDriver,
)

LOOPBACK = frozenset({"14", "15"})


def _group(group_id: str = "camera-tool", **fields) -> HardwareGroupMapping:
    payload = {"id": group_id, "name": group_id.replace("-", " ").title(), "connector_id": "pogo-connector"}
    payload.update(fields)
    return HardwareGroupMapping.model_validate(payload)


def _map(*groups: HardwareGroupMapping, devices=(), boards=(), assignments=()) -> HardwareMap:
    return HardwareMap(
        boards=list(boards),
        devices=list(devices),
        groups=list(groups),
        connectors=[default_pogo_connector()],
        function_assignments=list(assignments),
    )


class _Rig:
    """A connector service over a temporary state file and simulated pins."""

    def __init__(self, hardware_map: HardwareMap, *, shorted=()) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.hardware_map = hardware_map
        self.store = ConnectorStateStore(Path(self._dir.name) / "connector-state.json")
        self.pins = SimulatedPinDriver(shorted=set(shorted))
        self.service = PogoConnectorService(
            state_store=self.store,
            pin_driver=self.pins,
            load_map=lambda: self.hardware_map,
            usb_settle_seconds=0.0,
        )

    def close(self) -> None:
        self._dir.cleanup()


class ModelValidationTests(unittest.TestCase):
    def test_a_map_without_connectors_still_loads(self) -> None:
        # Every map saved before this feature existed.
        self.assertEqual(HardwareMap.model_validate({"groups": [{"id": "g", "name": "G"}]}).connectors, [])

    def test_a_group_on_an_unknown_connector_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown connector"):
            _map(_group(connector_id="nope"))

    def test_a_pin_the_connector_does_not_have_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not have"):
            _map(_group(pin_modes={"MISO": "gpio"}))

    def test_uart_on_an_i2c_pin_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot carry UART"):
            _map(_group(pin_modes={"SDA": "uart"}))

    def test_half_an_i2c_bus_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must use all"):
            _map(_group(pin_modes={"SDA": "i2c"}))

    def test_a_loopback_tool_cannot_also_use_its_shorted_pins(self) -> None:
        with self.assertRaisesRegex(ValueError, "shorted"):
            _map(_group(verification="loopback", pin_modes={"TXD": "uart", "RXD": "uart"}))

    def test_usb_verification_needs_a_controller(self) -> None:
        with self.assertRaisesRegex(ValueError, "names no USB controller"):
            _map(_group(verification="fingerprint"))

    def test_two_tools_cannot_share_a_rack_slot(self) -> None:
        with self.assertRaisesRegex(ValueError, "both claim rack slot 2"):
            _map(_group("a", toolhead_index=2), _group("b", toolhead_index=2))

    def test_connector_fields_on_a_plain_group_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "not attached to a connector"):
            _map(HardwareGroupMapping(id="g", name="G", toolhead_index=1))

    def test_the_live_hardware_map_still_validates(self) -> None:
        path = Path(__file__).resolve().parents[2] / "hardware-map.json"
        hardware_map = HardwareMapService(path).load_map()
        self.assertEqual([c.id for c in hardware_map.connectors], ["pogo-connector"])


class LoopbackTests(unittest.TestCase):
    def test_a_shorted_tool_is_confirmed(self) -> None:
        rig = _Rig(_map(_group(verification="loopback")), shorted=[LOOPBACK])
        self.addCleanup(rig.close)

        result = rig.service.activate("camera-tool")

        self.assertTrue(result.verified)
        self.assertEqual(rig.store.active_group_id("pogo-connector"), "camera-tool")
        # Nothing is left driven once the test is over.
        self.assertEqual(rig.pins.state["14"], ("input", "none"))

    def test_an_empty_connector_fails_loudly_and_stays_empty(self) -> None:
        rig = _Rig(_map(_group(verification="loopback")))
        self.addCleanup(rig.close)

        with self.assertRaisesRegex(ConnectorError, "no TXD-RXD loopback"):
            rig.service.activate("camera-tool")

        self.assertIsNone(rig.store.active_group_id("pogo-connector"))
        for gpio in ("2", "3", "14", "15"):
            self.assertEqual(rig.pins.state[gpio], ("input", "none"), f"GPIO {gpio} parked")

    def test_a_failure_forgets_the_previous_tool(self) -> None:
        # The accident to prevent: tool A stays "connected" after B failed.
        rig = _Rig(_map(_group("a"), _group("b", verification="loopback")))
        self.addCleanup(rig.close)
        rig.service.activate("a")

        with self.assertRaises(ConnectorError):
            rig.service.activate("b")

        self.assertEqual(rig.store.active_group_ids(), set())


class PinModeTests(unittest.TestCase):
    def test_modes_route_pins_to_their_peripherals(self) -> None:
        group = _group(pin_modes={"SDA": "i2c", "SCL": "i2c", "TXD": "uart", "RXD": "gpio"})
        rig = _Rig(_map(group))
        self.addCleanup(rig.close)

        result = rig.service.activate("camera-tool")

        self.assertEqual(rig.pins.state["2"], ("alt", "a3"))
        self.assertEqual(rig.pins.state["3"], ("alt", "a3"))
        self.assertEqual(rig.pins.state["14"], ("alt", "a4"))
        self.assertEqual(rig.pins.state["15"], ("input", "none"), "GPIO is left for the tool's blocks")
        self.assertEqual(result.pin_modes["RXD"], "gpio")

    def test_a_tool_with_nothing_to_check_connects_with_a_warning(self) -> None:
        rig = _Rig(_map(_group()))
        self.addCleanup(rig.close)

        result = rig.service.activate("camera-tool")

        self.assertFalse(result.verified, "never reported as verified")
        self.assertTrue(result.warnings)
        self.assertIn("not verified", result.message)

    def test_disconnect_parks_every_pin(self) -> None:
        rig = _Rig(_map(_group(pin_modes={"SDA": "i2c", "SCL": "i2c"})))
        self.addCleanup(rig.close)
        rig.service.activate("camera-tool")

        rig.service.deactivate()

        self.assertEqual(rig.pins.state["2"], ("input", "none"))
        self.assertEqual(rig.store.active_group_ids(), set())

    def test_a_disabled_tool_cannot_be_connected(self) -> None:
        rig = _Rig(_map(_group(enabled=False)))
        self.addCleanup(rig.close)
        with self.assertRaisesRegex(ConnectorError, "disabled"):
            rig.service.activate("camera-tool")


def _preflight(verdict: PreflightVerdict, reported: str | None = "tool-esp") -> ControllerPreflightResult:
    return ControllerPreflightResult(
        controller_id="tool-esp",
        verdict=verdict,
        message=f"preflight said {verdict.value}",
        reported_controller_id=reported,
    )


class FingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        board = HardwareBoardMapping(id="tool-esp", label="Tool ESP32", usb_port="/dev/ttyUSB1")
        self.rig = _Rig(_map(_group(verification="fingerprint", usb_board_id="tool-esp"), boards=[board]))
        self.addCleanup(self.rig.close)

    def _activate_with(self, *results):
        from app.services import esp32_builder

        with mock.patch.object(esp32_builder.esp32_builder_service, "preflight_board", side_effect=list(results)):
            return self.rig.service.activate("camera-tool")

    def test_the_expected_esp32_is_confirmed(self) -> None:
        self.assertTrue(self._activate_with(_preflight(PreflightVerdict.OK)).verified)

    def test_a_different_esp32_fails_loudly(self) -> None:
        with self.assertRaisesRegex(ConnectorError, "wrong_controller"):
            self._activate_with(_preflight(PreflightVerdict.WRONG_CONTROLLER, reported="other"))
        self.assertEqual(self.rig.store.active_group_ids(), set())

    def test_the_right_board_with_stale_firmware_is_still_the_right_tool(self) -> None:
        result = self._activate_with(_preflight(PreflightVerdict.NEEDS_FLASH))
        self.assertIn("needs flashing", result.message)

    def test_a_board_still_enumerating_is_waited_for(self) -> None:
        self.rig.service._usb_settle_seconds = 5.0
        with mock.patch("app.services.pogo_connector.USB_POLL_INTERVAL_SECONDS", 0.0):
            result = self._activate_with(
                _preflight(PreflightVerdict.NOT_CONNECTED),
                _preflight(PreflightVerdict.OK),
            )
        self.assertTrue(result.verified)


def _manifest() -> FunctionManifest:
    return FunctionManifest.model_validate({
        "id": "read_camera",
        "display_name": "Read Camera",
        "category": "Robot Actions",
        "description": "Uses the camera tool.",
        "version": "0.1.0",
        "inputs": [{"key": "trigger_pin", "label": "Trigger", "type": "string"}],
        "hardware_devices": [
            {"id": "camera-trigger", "name": "Camera Trigger", "kind": "servo",
             "pins": [{"id": "trig", "signal": "trigger", "function_input_key": "trigger_pin"}]},
        ],
    })


class FunctionGatingTests(unittest.TestCase):
    def _service(self, active: set[str]) -> HardwareMapService:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        service = HardwareMapService(Path(self._dir.name) / "hardware-map.json", active_connector_groups=lambda: active)
        device = HardwareDeviceMapping(
            id="camera-trigger", board_id="raspberry-pi", name="Camera Trigger", kind="servo",
            pins=[HardwarePinMapping(id="trig", signal="trigger", gpio="15", function_input_key="trigger_pin")],
        )
        service.save_map(_map(
            _group(member_ids=["camera-trigger"], pin_modes={"RXD": "gpio"}),
            devices=[device],
            assignments=[FunctionHardwareAssignment(function_id="read_camera", device_id="camera-trigger",
                                                    hardware_device_id="camera-trigger")],
        ))
        return service

    def test_hardware_on_an_undocked_tool_is_refused_with_the_reason(self) -> None:
        with self.assertRaisesRegex(HardwareMapError, "tool 'Camera Tool', but that tool is not connected"):
            self._service(active=set()).apply_function_defaults(_manifest(), {})

    def test_the_docked_tool_gets_its_pins(self) -> None:
        inputs = self._service(active={"camera-tool"}).apply_function_defaults(_manifest(), {})
        self.assertEqual(inputs["trigger_pin"], "15")

    def test_an_undocked_tool_is_not_persisted_as_disabled(self) -> None:
        # Docking is run-time state; the saved map must not flip enabled flags.
        service = self._service(active=set())
        self.assertTrue(service.load_map().devices[0].enabled)


class ToolheadLinkTests(unittest.TestCase):
    def test_picking_up_a_slot_connects_its_tool(self) -> None:
        rig = _Rig(_map(_group("camera-tool", toolhead_index=3)))
        self.addCleanup(rig.close)

        results = rig.service.connect_for_toolhead(3)

        self.assertEqual([r.group_id for r in results], ["camera-tool"])
        self.assertEqual(rig.store.active_group_id("pogo-connector"), "camera-tool")

    def test_a_tool_without_a_connector_leaves_it_empty(self) -> None:
        rig = _Rig(_map(_group("camera-tool", toolhead_index=3)))
        self.addCleanup(rig.close)
        rig.service.activate("camera-tool")

        results = rig.service.connect_for_toolhead(1)

        self.assertIsNone(results[0].group_id)
        self.assertEqual(rig.store.active_group_ids(), set())

    def test_an_already_connected_tool_is_not_reverified_on_request(self) -> None:
        rig = _Rig(_map(_group("camera-tool", toolhead_index=3, verification="loopback")), shorted=[LOOPBACK])
        self.addCleanup(rig.close)
        rig.service.activate("camera-tool")
        rig.pins.shorted.clear()  # would fail if the loopback ran again

        results = rig.service.connect_for_toolhead(3, reverify=False)

        self.assertEqual(results[0].group_id, "camera-tool")


# ---- the block entry points ----------------------------------------------


class _Positions:
    pass


class _FakeToolheadService:
    def __init__(self, state) -> None:
        self.state = state
        self.calls: list[str] = []

    def pickup(self, *, position, **_kwargs):
        self.calls.append(f"pickup {position.index}")
        self.state.held = position.index
        return []

    def drop(self, *, position, **_kwargs):
        self.calls.append(f"drop {position.index}")
        self.state.held = None
        return []


class _FakeHeldState:
    def __init__(self, held=None) -> None:
        self.held = held

    def held_index(self):
        return self.held


class _FakeDefaults:
    def apply_toolhead_defaults(self, _values):
        return {}

    def current_toolhead_defaults(self):
        return {}


class BlockEntryPointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rig = _Rig(_map(_group("camera-tool", toolhead_index=2, verification="loopback")), shorted=[LOOPBACK])
        self.addCleanup(self.rig.close)

    def _handler(self, function_id: str, held=None):
        module = importlib.import_module(f"app.functions.{function_id}.handler")
        state = _FakeHeldState(held)
        toolhead = _FakeToolheadService(state)
        for name, value in {
            "pogo_connector_service": self.rig.service,
            "toolhead_state_store": state,
            "toolhead_service": toolhead,
            "workspace_defaults_service": _FakeDefaults(),
        }.items():
            if hasattr(module, name):
                patcher = mock.patch.object(module, name, value)
                patcher.start()
                self.addCleanup(patcher.stop)
        return module, toolhead

    def test_connect_tool_activates_the_selected_group(self) -> None:
        module, _ = self._handler("connect_tool")
        result = module.execute({}, {"connector_group_id": "camera-tool"})
        self.assertEqual(result["group_id"], "camera-tool")
        self.assertTrue(result["verified"])

    def test_connect_tool_fails_when_the_tool_is_not_there(self) -> None:
        module, _ = self._handler("connect_tool")
        self.rig.pins.shorted.clear()
        with self.assertRaises(ConnectorError):
            module.execute({}, {"connector_group_id": "camera-tool"})

    def test_connect_tool_needs_a_selection(self) -> None:
        module, _ = self._handler("connect_tool")
        with self.assertRaisesRegex(ValueError, "Select which tool"):
            module.execute({}, {"connector_group_id": ""})

    def test_disconnect_tool_empties_the_connector(self) -> None:
        self.rig.service.activate("camera-tool")
        module, _ = self._handler("disconnect_tool")
        module.execute({}, {})
        self.assertEqual(self.rig.store.active_group_ids(), set())

    def test_pickup_connects_the_slot_tool(self) -> None:
        module, toolhead = self._handler("pickup_toolhead")
        result = module.execute({}, {"toolhead_index": 2})
        self.assertEqual(toolhead.calls, ["pickup 2"])
        self.assertEqual(result["connector"][0]["group_id"], "camera-tool")
        self.assertEqual(self.rig.store.active_group_id("pogo-connector"), "camera-tool")

    def test_pickup_of_a_tool_without_a_connector_leaves_it_empty(self) -> None:
        self.rig.service.activate("camera-tool")
        module, _ = self._handler("pickup_toolhead", held=None)
        module.execute({}, {"toolhead_index": 1})
        self.assertEqual(self.rig.store.active_group_ids(), set())

    def test_pickup_reports_a_failed_connector_check_as_such(self) -> None:
        module, _ = self._handler("pickup_toolhead")
        self.rig.pins.shorted.clear()
        with self.assertRaisesRegex(RuntimeError, "Toolhead 2 is on the head, but its connector check failed"):
            module.execute({}, {"toolhead_index": 2})

    def test_drop_releases_the_connector(self) -> None:
        self.rig.service.activate("camera-tool")
        module, toolhead = self._handler("drop_toolhead", held=2)
        module.execute({}, {})
        self.assertEqual(toolhead.calls, ["drop 2"])
        self.assertEqual(self.rig.store.active_group_ids(), set())


class OperatorConfirmTests(unittest.TestCase):
    """Answering the "which tool is on the head?" dialog moves the connector."""

    def setUp(self) -> None:
        self.rig = _Rig(_map(_group("camera-tool", toolhead_index=2, verification="loopback")), shorted=[LOOPBACK])
        self.addCleanup(self.rig.close)
        from app.api.routes import safety as safety_routes
        from app.services import pogo_connector as pogo_module

        self.routes = safety_routes
        self.confirmed: list = []
        for target, name, value in [
            (pogo_module, "pogo_connector_service", self.rig.service),
            (safety_routes.physical_state_store, "confirm",
             lambda fact_id, value, operator="operator": self.confirmed.append((fact_id, value))),
            (safety_routes, "_snapshot_with_access_door", lambda: None),
            (safety_routes.SafetySnapshot, "model_validate", staticmethod(lambda payload: payload)),
        ]:
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _confirm(self, value):
        from app.models.safety import PhysicalStateConfirmRequest

        self.routes.confirm_physical_state(PhysicalStateConfirmRequest(fact_id="toolhead.held", value=value))

    def test_confirming_a_slot_connects_its_tool(self) -> None:
        self._confirm(2)
        self.assertEqual(self.confirmed, [("toolhead.held", 2)])
        self.assertEqual(self.rig.store.active_group_id("pogo-connector"), "camera-tool")

    def test_confirming_an_empty_head_empties_the_connector(self) -> None:
        self.rig.service.activate("camera-tool")
        self._confirm(None)
        self.assertEqual(self.rig.store.active_group_ids(), set())

    def test_a_failed_check_still_records_the_answer_and_says_why(self) -> None:
        self.rig.pins.shorted.clear()
        self._confirm(2)
        self.assertEqual(self.confirmed, [("toolhead.held", 2)], "the operator's answer stands")
        self.assertEqual(self.rig.store.active_group_ids(), set())
        status = self.rig.service.status()[0]
        self.assertIn("Could not connect tool", status["message"])

    def test_other_facts_leave_the_connector_alone(self) -> None:
        self.rig.service.activate("camera-tool")
        from app.models.safety import PhysicalStateConfirmRequest

        self.routes.confirm_physical_state(PhysicalStateConfirmRequest(fact_id="gantry.xy_calibrated", value=True))
        self.assertEqual(self.rig.store.active_group_id("pogo-connector"), "camera-tool")


class ContactEndpointTests(unittest.TestCase):
    def test_the_endpoint_reports_the_short_without_recording_anything(self) -> None:
        from app.api.routes import hardware_map as routes
        from app.services import pogo_connector as pogo_module

        rig = _Rig(_map(), shorted=[LOOPBACK])
        self.addCleanup(rig.close)
        with mock.patch.object(pogo_module, "pogo_connector_service", rig.service):
            self.assertTrue(routes.check_connector_contact()["ok"])
            rig.pins.shorted.clear()
            self.assertFalse(routes.check_connector_contact()["ok"])
        self.assertEqual(rig.store.read(), {}, "a check is not a connection")


if __name__ == "__main__":
    unittest.main()
