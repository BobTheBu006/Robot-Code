"""Identity generation at flash time, and flashing only what is wrong.

Covers the gap that made the handshake inert: `render_identity_header` existed
but nothing ever wrote it into a sketch, so every board answered `ID?` with an
empty identity, preflight could only read that as "cannot verify", and the run
reflashed everything anyway.

These tests never touch a real board or the repo-root state files.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.controllers.fingerprint import (
    GENERATED_IDENTITY_FILENAME,
    FirmwareBundle,
    PinAssignment,
    render_identity_header,
)
from app.services.esp32_builder import Esp32BuilderService


def _make_workspace(root: Path, board_id: str, *, sources: dict[str, str] | None = None) -> Path:
    workspace = root / "functions" / "esp 32 code" / f"esp32 {board_id}"
    (workspace / "firmware").mkdir(parents=True, exist_ok=True)
    (workspace / "workflow-functions").mkdir(parents=True, exist_ok=True)
    for name, content in (sources or {"main.ino": "void setup(){}\nvoid loop(){}\n"}).items():
        (workspace / "firmware" / name).write_text(content, encoding="utf-8")
    (workspace / "board.json").write_text(
        json.dumps(
            {
                "board_id": board_id,
                "display_name": f"Board {board_id}",
                "port": "/dev/ttyUSB9",
                "firmware_entry_file": "firmware/main.ino",
                "fqbn": "esp32:esp32:esp32",
            }
        ),
        encoding="utf-8",
    )
    return workspace


class IdentityHeaderContentTests(unittest.TestCase):
    def test_header_carries_the_human_readable_name(self) -> None:
        header = render_identity_header(
            FirmwareBundle(controller_id="z-axis", controller_name="Double Z axis and pumps")
        )
        self.assertIn('#define ROBOT_CONTROLLER_ID "z-axis"', header)
        self.assertIn('#define ROBOT_CONTROLLER_NAME "Double Z axis and pumps"', header)

    def test_renaming_a_controller_does_not_force_a_reflash(self) -> None:
        # The name is for humans. If it fed the fingerprint, editing a label in
        # the Hardware Map would make every board look stale.
        plain = FirmwareBundle(controller_id="z-axis", controller_name="Z")
        renamed = FirmwareBundle(controller_id="z-axis", controller_name="Z axis controller")
        self.assertEqual(plain.fingerprint(), renamed.fingerprint())

    def test_quotes_in_a_name_cannot_break_the_generated_header(self) -> None:
        header = render_identity_header(
            FirmwareBundle(controller_id='we"ird', controller_name='say "hi"\\done')
        )
        # Every embedded quote must be escaped, or the sketch will not compile.
        for line in header.splitlines():
            if line.startswith("#define ROBOT_CONTROLLER_ID ") or line.startswith(
                "#define ROBOT_CONTROLLER_NAME "
            ):
                value = line.split(" ", 2)[2]
                self.assertTrue(value.startswith('"') and value.endswith('"'))
                inner = value[1:-1]
                # No unescaped quote may appear inside the literal.
                self.assertNotIn('"', inner.replace('\\"', ""))


class SketchIdentityStampingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.functions_dir = self.root / "backend" / "app" / "functions"
        self.functions_dir.mkdir(parents=True, exist_ok=True)
        self.service = Esp32BuilderService(repo_root=self.root, app_functions_dir=self.functions_dir)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_prepared_sketch_contains_a_generated_identity_header(self) -> None:
        workspace = _make_workspace(self.root, "board-a")
        metadata = self.service._load_board_metadata(workspace)

        sketch_dir, _ = self.service._prepare_sketch_dir("board-a", workspace, metadata)

        header = sketch_dir / GENERATED_IDENTITY_FILENAME
        self.assertTrue(header.exists(), "flashing must stamp identity into the sketch")
        contents = header.read_text(encoding="utf-8")
        self.assertIn('#define ROBOT_CONTROLLER_ID "board-a"', contents)
        self.assertIn("#define ROBOT_FIRMWARE_FINGERPRINT", contents)

    def test_identity_survives_a_firmware_change_as_a_new_fingerprint(self) -> None:
        workspace = _make_workspace(self.root, "board-a")
        metadata = self.service._load_board_metadata(workspace)
        first = self.service.build_firmware_bundle("board-a", workspace, metadata).fingerprint()

        (workspace / "firmware" / "main.ino").write_text("void setup(){int x=1;}\n", encoding="utf-8")
        second = self.service.build_firmware_bundle("board-a", workspace, metadata).fingerprint()

        self.assertNotEqual(first, second, "editing firmware must invalidate the fingerprint")

    def test_a_bundle_failure_does_not_block_flashing(self) -> None:
        # The sketch still compiles without the header, reporting an empty
        # identity, which preflight treats as "flash it once" - degraded but
        # not stuck. A raised exception here would make the board unflashable.
        workspace = _make_workspace(self.root, "board-a")
        metadata = self.service._load_board_metadata(workspace)

        def explode(*_args, **_kwargs):
            raise RuntimeError("hardware map unreadable")

        self.service.build_firmware_bundle = explode  # type: ignore[method-assign]
        sketch_dir, _ = self.service._prepare_sketch_dir("board-a", workspace, metadata)

        self.assertTrue((sketch_dir / "board_a.ino").exists())
        self.assertFalse((sketch_dir / GENERATED_IDENTITY_FILENAME).exists())


class WorkspaceIdentityStabilityTests(unittest.TestCase):
    """A workspace's recorded identity must not follow whatever is plugged in."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        functions_dir = self.root / "backend" / "app" / "functions"
        functions_dir.mkdir(parents=True, exist_ok=True)
        self.service = Esp32BuilderService(repo_root=self.root, app_functions_dir=functions_dir)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_a_different_board_on_the_same_port_does_not_rewrite_identity(self) -> None:
        from app.services.serial_ports import SerialPortInfo

        first = SerialPortInfo(
            device="/dev/ttyUSB0", description="CP2102N", hardware_id="hw-1", serial_number="SERIAL-ONE"
        )
        self.service._ensure_board_workspace(first)
        workspace = self.service._resolve_workspace_dir(self.service._board_id_from_port("/dev/ttyUSB0"))
        self.assertEqual(self.service._load_board_metadata(workspace)["serial_number"], "SERIAL-ONE")

        # A different physical board is now on the same port. Before the fix
        # this silently restamped the workspace, which is how every workspace
        # ended up claiming the same serial and flashes hit the wrong board.
        second = SerialPortInfo(
            device="/dev/ttyUSB0", description="CP2102N", hardware_id="hw-2", serial_number="SERIAL-TWO"
        )
        self.service._ensure_board_workspace(second)

        self.assertEqual(
            self.service._load_board_metadata(workspace)["serial_number"],
            "SERIAL-ONE",
            "recorded identity must be stable, not a mirror of what is plugged in",
        )

    def test_identity_is_still_recorded_when_it_is_not_yet_known(self) -> None:
        from app.services.serial_ports import SerialPortInfo

        port = SerialPortInfo(
            device="/dev/ttyUSB1", description="CP2102N", hardware_id="hw-9", serial_number="SERIAL-NEW"
        )
        self.service._ensure_board_workspace(port)
        workspace = self.service._resolve_workspace_dir(self.service._board_id_from_port("/dev/ttyUSB1"))

        self.assertEqual(self.service._load_board_metadata(workspace)["serial_number"], "SERIAL-NEW")


if __name__ == "__main__":
    unittest.main()
