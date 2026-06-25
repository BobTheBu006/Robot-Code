import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.esp32_builder import Esp32WorkflowFirmwarePlanRequest
from app.services.esp32_builder import Esp32BuilderService


class Esp32WorkflowFirmwarePlanTests(unittest.TestCase):
    def _make_service(self, temporary_directory: str) -> Esp32BuilderService:
        repo_root = Path(temporary_directory)
        app_functions_dir = repo_root / "backend" / "app" / "functions"
        workspace_dir = repo_root / "functions" / "esp 32 code" / "esp32 ttyUSB0"
        (workspace_dir / "firmware").mkdir(parents=True)
        (workspace_dir / "firmware" / "main.ino").write_text("// test firmware\n", encoding="utf-8")
        (workspace_dir / "board.json").write_text(
            json.dumps(
                {
                    "board_id": "ttyUSB0",
                    "display_name": "Test ESP32",
                    "port": "COM7",
                    "firmware_entry_file": "firmware/main.ino",
                    "fqbn": "esp32:esp32:esp32",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return Esp32BuilderService(repo_root=repo_root, app_functions_dir=app_functions_dir)

    def test_plan_groups_and_deduplicates_routines_by_board(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            service = self._make_service(temporary_directory)
            request = Esp32WorkflowFirmwarePlanRequest(
                items=[
                    {
                        "block_id": "node-1",
                        "block_name": "Dispense A",
                        "board_id": "ttyUSB0",
                        "requirements": [
                            {
                                "routine_id": "dispense",
                                "controller_role": "builder_board",
                                "source": "firmware/main.ino",
                                "protocol": "serial-text",
                                "entry_point": "dispense",
                                "required_device_ids": ["syringe-a"],
                            }
                        ],
                    },
                    {
                        "block_id": "node-2",
                        "block_name": "Dispense B",
                        "board_id": "ttyUSB0",
                        "requirements": [
                            {
                                "routine_id": "dispense",
                                "controller_role": "builder_board",
                                "source": "firmware/main.ino",
                                "protocol": "serial-text",
                                "entry_point": "dispense",
                                "required_device_ids": ["syringe-b"],
                            }
                        ],
                    },
                ]
            )

            plan = service.plan_workflow_firmware(request)

        self.assertTrue(plan.ok)
        self.assertEqual(len(plan.boards), 1)
        self.assertEqual(plan.boards[0].board_id, "ttyUSB0")
        self.assertEqual(len(plan.boards[0].routines), 1)
        routine = plan.boards[0].routines[0]
        self.assertTrue(routine.source_exists)
        self.assertEqual(routine.block_ids, ["node-1", "node-2"])
        self.assertEqual(routine.required_device_ids, ["syringe-a", "syringe-b"])

    def test_plan_reports_missing_firmware_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            service = self._make_service(temporary_directory)
            request = Esp32WorkflowFirmwarePlanRequest(
                items=[
                    {
                        "block_id": "node-1",
                        "board_id": "ttyUSB0",
                        "requirements": [
                            {
                                "routine_id": "missing",
                                "controller_role": "builder_board",
                                "source": "firmware/missing.ino",
                            }
                        ],
                    }
                ]
            )

            plan = service.plan_workflow_firmware(request)

        self.assertFalse(plan.ok)
        self.assertEqual(plan.boards[0].missing_sources, ["firmware/missing.ino"])
        self.assertTrue(any("was not found" in error for error in plan.errors))

    def test_plan_rejects_sources_outside_board_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            service = self._make_service(temporary_directory)
            request = Esp32WorkflowFirmwarePlanRequest(
                items=[
                    {
                        "block_id": "node-1",
                        "board_id": "ttyUSB0",
                        "requirements": [
                            {
                                "routine_id": "unsafe",
                                "controller_role": "builder_board",
                                "source": "../outside.ino",
                            }
                        ],
                    }
                ]
            )

            plan = service.plan_workflow_firmware(request)

        self.assertFalse(plan.ok)
        self.assertTrue(any("outside board workspace" in error for error in plan.errors))


if __name__ == "__main__":
    unittest.main()
