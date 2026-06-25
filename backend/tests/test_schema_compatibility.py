import tempfile
import unittest
from pathlib import Path
import sys

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.function_manifest import FUNCTION_MANIFEST_SCHEMA_VERSION, FunctionManifest
from app.models.workflows import WORKFLOW_SCHEMA_VERSION
from app.services.workflow_storage import WorkflowStorageError, WorkflowStorageService


class FunctionManifestSchemaCompatibilityTests(unittest.TestCase):
    def test_legacy_manifest_gets_current_schema_version(self) -> None:
        manifest = FunctionManifest.model_validate(
            {
                "id": "example",
                "display_name": "Example",
                "category": "Robot Actions",
                "description": "Legacy manifest without an explicit schema version.",
                "version": "0.1.0",
                "outputs": [
                    {
                        "key": "next",
                        "label": "Next",
                        "type": "flow",
                    }
                ],
            }
        )

        self.assertEqual(manifest.schema_version, FUNCTION_MANIFEST_SCHEMA_VERSION)

    def test_unsupported_manifest_schema_version_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            FunctionManifest.model_validate(
                {
                    "schema_version": 999,
                    "id": "example",
                    "display_name": "Example",
                    "category": "Robot Actions",
                    "description": "Future manifest that this backend cannot safely load.",
                    "version": "0.1.0",
                }
            )

    def test_firmware_requirements_are_validated_and_preserved(self) -> None:
        manifest = FunctionManifest.model_validate(
            {
                "schema_version": 1,
                "id": "example",
                "display_name": "Example",
                "category": "Robot Actions",
                "description": "Manifest with firmware requirements.",
                "version": "0.1.0",
                "firmware_requirements": [
                    {
                        "routine_id": "example_routine",
                        "controller_role": "builder_board",
                        "source": "firmware/main.ino",
                        "protocol": "serial-text",
                        "entry_point": "runExample",
                        "required_device_ids": ["example-stepper"],
                    }
                ],
            }
        )

        self.assertEqual(manifest.firmware_requirements[0].routine_id, "example_routine")
        self.assertEqual(manifest.firmware_requirements[0].required_device_ids, ["example-stepper"])


class WorkflowSchemaCompatibilityTests(unittest.TestCase):
    def test_save_and_load_add_current_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            service = WorkflowStorageService(Path(temporary_directory))
            service.save_workflow(
                "legacy",
                {
                    "nodes": [],
                    "edges": [],
                },
            )
            loaded = service.load_workflow("legacy.json")

        self.assertEqual(loaded.workflow["schema_version"], WORKFLOW_SCHEMA_VERSION)
        self.assertEqual(loaded.workflow["version"], WORKFLOW_SCHEMA_VERSION)
        self.assertEqual(loaded.workflow["nodes"], [])
        self.assertEqual(loaded.workflow["edges"], [])

    def test_unsupported_workflow_schema_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            service = WorkflowStorageService(Path(temporary_directory))

            with self.assertRaises(WorkflowStorageError):
                service.save_workflow(
                    "future",
                    {
                        "schema_version": 999,
                        "nodes": [],
                        "edges": [],
                    },
                )


if __name__ == "__main__":
    unittest.main()
