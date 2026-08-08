"""Identity handshake and preflight.

Closes the defect where the ESP32 builder derived controller ids from the port
name (`ttyUSB0`) while the Hardware Map generated `controller-*` ids. A board
whose id could not be resolved was quietly downgraded to "externally
programmed", excluded from the flash list, and the run continued against
whatever firmware happened to be on it.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.controllers.fingerprint import (
    GENERATED_IDENTITY_FILENAME,
    ControllerIdentity,
    FirmwareBundle,
    PinAssignment,
    hash_firmware_sources,
    render_identity_header,
)
from app.controllers.preflight import PreflightReport, PreflightVerdict, preflight_controller
from app.controllers.simulation import SimulatedControllerSpec, simulated_controllers


def _bundle(controller_id: str = "controller-x83xnc", **overrides) -> FirmwareBundle:
    defaults = dict(
        controller_id=controller_id,
        routines=["dispense", "prime"],
        pins=[PinAssignment("syringe-head-a", "step", "14")],
        source_hashes={"main.ino": "deadbeef"},
    )
    defaults.update(overrides)
    return FirmwareBundle(**defaults)


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_is_stable_across_collection_order(self) -> None:
        first = FirmwareBundle(
            controller_id="c1",
            routines=["b", "a"],
            pins=[PinAssignment("d2", "step", "5"), PinAssignment("d1", "dir", "4")],
            source_hashes={"z.h": "2", "a.ino": "1"},
        )
        second = FirmwareBundle(
            controller_id="c1",
            routines=["a", "b"],
            pins=[PinAssignment("d1", "dir", "4"), PinAssignment("d2", "step", "5")],
            source_hashes={"a.ino": "1", "z.h": "2"},
        )

        # Two builds that differ only in the order things were gathered must not
        # look like different firmware, or preflight would reflash every run.
        self.assertEqual(first.fingerprint(), second.fingerprint())

    def test_fingerprint_changes_when_a_pin_moves(self) -> None:
        moved = _bundle(pins=[PinAssignment("syringe-head-a", "step", "27")])

        # The Hardware Map is the source of truth for pins, so a rewire has to
        # invalidate the firmware on the board.
        self.assertNotEqual(_bundle().fingerprint(), moved.fingerprint())

    def test_fingerprint_changes_when_a_routine_is_added(self) -> None:
        self.assertNotEqual(
            _bundle().fingerprint(),
            _bundle(routines=["dispense", "prime", "wash"]).fingerprint(),
        )

    def test_fingerprint_changes_when_source_changes(self) -> None:
        self.assertNotEqual(
            _bundle().fingerprint(),
            _bundle(source_hashes={"main.ino": "cafebabe"}).fingerprint(),
        )

    def test_source_hashing_skips_the_generated_identity_header(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            firmware_dir = Path(raw_dir)
            (firmware_dir / "main.ino").write_text("void setup() {}", encoding="utf-8")
            before = hash_firmware_sources(firmware_dir)

            # The header carries the fingerprint, so hashing it would make the
            # fingerprint depend on itself and never converge.
            (firmware_dir / GENERATED_IDENTITY_FILENAME).write_text("#define X 1", encoding="utf-8")
            after = hash_firmware_sources(firmware_dir)

        self.assertEqual(before, after)
        self.assertEqual(list(before), ["main.ino"])

    def test_identity_header_carries_id_fingerprint_and_routines(self) -> None:
        header = render_identity_header(_bundle())

        self.assertIn('#define ROBOT_CONTROLLER_ID "controller-x83xnc"', header)
        self.assertIn(f'#define ROBOT_FIRMWARE_FINGERPRINT "{_bundle().fingerprint()}"', header)
        self.assertIn('"dispense", "prime"', header)


class IdentityParsingTests(unittest.TestCase):
    def test_parses_a_well_formed_reply(self) -> None:
        identity = ControllerIdentity.parse(
            '{"controller_id":"c1","fingerprint":"abc","protocol":1,"routines":["move"]}'
        )

        self.assertIsNotNone(identity)
        self.assertEqual(identity.controller_id, "c1")
        self.assertEqual(identity.routines, ("move",))

    def test_pre_handshake_firmware_reads_as_no_identity_rather_than_an_error(self) -> None:
        # Older sketches answer "ERR UNKNOWN CMD" to anything they do not know.
        self.assertIsNone(ControllerIdentity.parse("ERR UNKNOWN CMD"))
        self.assertIsNone(ControllerIdentity.parse("PONG"))
        self.assertIsNone(ControllerIdentity.parse(""))

    def test_malformed_json_does_not_raise(self) -> None:
        self.assertIsNone(ControllerIdentity.parse('{"controller_id": '))


class PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        simulated_controllers.clear()

    def tearDown(self) -> None:
        simulated_controllers.clear()

    def _register(self, **overrides) -> str:
        spec = SimulatedControllerSpec(
            device=overrides.pop("device", "SIM0"),
            serial_number=overrides.pop("serial_number", "SIM-0001"),
            controller_id=overrides.pop("controller_id", "controller-x83xnc"),
            fingerprint=overrides.pop("fingerprint", _bundle().fingerprint()),
            routines=overrides.pop("routines", ["dispense", "prime"]),
            **overrides,
        )
        simulated_controllers.register(spec)
        return spec.device

    def test_matching_board_needs_no_flash(self) -> None:
        port = self._register()

        result = preflight_controller(
            controller_id="controller-x83xnc", expected=_bundle(), port=port
        )

        self.assertEqual(result.verdict, PreflightVerdict.OK)
        self.assertFalse(result.needs_flash)

    def test_stale_firmware_is_flagged_for_flashing(self) -> None:
        port = self._register(fingerprint="0000000000000000")

        result = preflight_controller(
            controller_id="controller-x83xnc", expected=_bundle(), port=port
        )

        self.assertEqual(result.verdict, PreflightVerdict.NEEDS_FLASH)
        self.assertEqual(result.reported_fingerprint, "0000000000000000")

    def test_missing_routine_is_flagged_even_when_the_fingerprint_matches(self) -> None:
        # A board can report the right build yet not carry a routine this
        # workflow needs, e.g. after a partial hand-flash.
        port = self._register(routines=["dispense"])

        result = preflight_controller(
            controller_id="controller-x83xnc", expected=_bundle(), port=port
        )

        self.assertEqual(result.verdict, PreflightVerdict.NEEDS_FLASH)
        self.assertEqual(result.missing_routines, ["prime"])

    def test_a_different_board_on_the_port_is_a_hard_error_not_a_warning(self) -> None:
        port = self._register(controller_id="controller-ykkl80")

        result = preflight_controller(
            controller_id="controller-x83xnc", expected=_bundle(), port=port
        )

        # This is the case the old code turned into "treating it as externally
        # programmed" and carried on. Flashing here would overwrite an
        # unrelated controller.
        self.assertEqual(result.verdict, PreflightVerdict.WRONG_CONTROLLER)
        self.assertTrue(result.verdict.blocks_run)
        self.assertIn("controller-ykkl80", result.message)

    def test_pre_handshake_firmware_is_flashed_once(self) -> None:
        # A real board running the current sketches does not answer ID? with a
        # null identity - it does not recognise the command at all.
        port = self._register(
            controller_id=None, fingerprint=None, routines=[], supports_identity=False
        )

        result = preflight_controller(
            controller_id="controller-x83xnc", expected=_bundle(), port=port
        )

        self.assertEqual(result.verdict, PreflightVerdict.NEEDS_FLASH)
        self.assertIn("predates the identity handshake", result.message)

    def test_unplugged_controller_blocks_the_run(self) -> None:
        result = preflight_controller(
            controller_id="controller-x83xnc", expected=_bundle(), port=None
        )

        self.assertEqual(result.verdict, PreflightVerdict.NOT_CONNECTED)
        self.assertTrue(result.verdict.blocks_run)

    def test_wedged_board_is_reflashed_rather_than_trusted(self) -> None:
        port = self._register(unresponsive=True)

        result = preflight_controller(
            controller_id="controller-x83xnc", expected=_bundle(), port=port, timeout_seconds=0.01
        )

        self.assertEqual(result.verdict, PreflightVerdict.UNRESPONSIVE)
        self.assertFalse(result.verdict.blocks_run)

    def test_report_separates_blocking_errors_from_work_to_do(self) -> None:
        good = preflight_controller(
            controller_id="controller-a", expected=_bundle("controller-a"),
            port=self._register(device="SIM-A", controller_id="controller-a",
                                fingerprint=_bundle("controller-a").fingerprint()),
        )
        stale = preflight_controller(
            controller_id="controller-b", expected=_bundle("controller-b"),
            port=self._register(device="SIM-B", controller_id="controller-b", fingerprint="stale"),
        )
        missing = preflight_controller(
            controller_id="controller-c", expected=_bundle("controller-c"), port=None
        )

        report = PreflightReport(results=[good, stale, missing])

        self.assertFalse(report.ok)
        self.assertEqual(report.controllers_to_flash, ["controller-b"])
        self.assertEqual([result.controller_id for result in report.blocking_errors], ["controller-c"])


class SimulatedPortEnumerationTests(unittest.TestCase):
    def setUp(self) -> None:
        simulated_controllers.clear()

    def tearDown(self) -> None:
        simulated_controllers.clear()

    def test_simulated_boards_appear_to_the_existing_port_enumeration(self) -> None:
        from app.services.serial_ports import list_serial_ports

        simulated_controllers.register(
            SimulatedControllerSpec(device="SIM0", serial_number="SIM-0001", controller_id="c1")
        )

        ports = list_serial_ports()

        # Everything downstream resolves boards by USB serial number, so the
        # simulated board has to be visible through the same call.
        self.assertIn("SIM0", [port.device for port in ports])
        self.assertEqual(
            next(port.serial_number for port in ports if port.device == "SIM0"), "SIM-0001"
        )


if __name__ == "__main__":
    unittest.main()
