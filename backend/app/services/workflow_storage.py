import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from app.models.workflows import (
    SUPPORTED_WORKFLOW_SCHEMA_VERSIONS,
    WORKFLOW_SCHEMA_VERSION,
    WorkflowFileResponse,
    WorkflowFileSummary,
    WorkflowListResponse,
    WorkflowSaveResponse,
)

DEFAULT_WORKFLOW_FILENAME = "active-workflow.json"
FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
DIRECTORY_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9._ -]+$")


class WorkflowStorageError(RuntimeError):
    pass


class WorkflowNotFoundError(FileNotFoundError):
    pass


class WorkflowStorageService:
    def __init__(self, workflows_dir: Path) -> None:
        self._workflows_dir = workflows_dir

    def _default_filename(self) -> str:
        configured_filename = os.getenv("WORKFLOW_DEFAULT_FILENAME", DEFAULT_WORKFLOW_FILENAME).strip()
        return self._normalize_filename(configured_filename)

    def _normalize_filename(self, filename: str) -> str:
        candidate = filename.strip()
        if not candidate:
            raise WorkflowStorageError("Workflow filename cannot be empty.")

        if not candidate.endswith(".json"):
            candidate = f"{candidate}.json"

        if not FILENAME_PATTERN.fullmatch(candidate):
            raise WorkflowStorageError(
                "Workflow filename may only contain letters, numbers, dots, dashes, and underscores."
            )

        return candidate

    def _ensure_workflows_dir(self) -> Path:
        self._workflows_dir.mkdir(parents=True, exist_ok=True)
        return self._workflows_dir

    def _normalize_directory(self, directory: str | None) -> str:
        if directory is None:
            return ""

        candidate = directory.strip().replace("\\", "/").strip("/")
        if not candidate:
            return ""

        segments = [segment.strip() for segment in candidate.split("/") if segment.strip()]
        if not segments:
            return ""

        for segment in segments:
            if segment in {".", ".."} or not DIRECTORY_SEGMENT_PATTERN.fullmatch(segment):
                raise WorkflowStorageError(
                    "Workflow path may only contain folder names with letters, numbers, spaces, dots, dashes, and underscores."
                )

        return "/".join(segments)

    def _workflow_path(self, filename: str, directory: str | None = None) -> Path:
        normalized_filename = self._normalize_filename(filename)
        normalized_directory = self._normalize_directory(directory)
        base_dir = self._ensure_workflows_dir()
        target_dir = base_dir / normalized_directory if normalized_directory else base_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        workflow_path = (target_dir / normalized_filename).resolve()

        if base_dir.resolve() not in workflow_path.parents:
            raise WorkflowStorageError("Workflow path must stay inside the workflows folder.")

        return workflow_path

    def _coerce_schema_version(self, value: object, filename: str) -> int:
        if isinstance(value, bool):
            raise WorkflowStorageError(f"Workflow file '{filename}' has an invalid schema version.")

        if isinstance(value, int):
            return value

        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())

        raise WorkflowStorageError(f"Workflow file '{filename}' has an invalid schema version.")

    def normalize_workflow_payload(self, workflow: dict[str, object], filename: str = "workflow") -> dict[str, object]:
        schema_version = self._coerce_schema_version(
            workflow.get("schema_version", workflow.get("version", WORKFLOW_SCHEMA_VERSION)),
            filename,
        )

        if schema_version not in SUPPORTED_WORKFLOW_SCHEMA_VERSIONS:
            supported_versions = ", ".join(str(version) for version in sorted(SUPPORTED_WORKFLOW_SCHEMA_VERSIONS))
            raise WorkflowStorageError(
                f"Workflow file '{filename}' uses unsupported schema_version {schema_version}. "
                f"Supported versions: {supported_versions}."
            )

        normalized_workflow = dict(workflow)
        normalized_workflow["schema_version"] = schema_version
        normalized_workflow["version"] = schema_version

        nodes = normalized_workflow.get("nodes", [])
        edges = normalized_workflow.get("edges", [])
        if not isinstance(nodes, list):
            raise WorkflowStorageError(f"Workflow file '{filename}' must contain a list in 'nodes'.")
        if not isinstance(edges, list):
            raise WorkflowStorageError(f"Workflow file '{filename}' must contain a list in 'edges'.")

        normalized_workflow["nodes"] = nodes
        normalized_workflow["edges"] = edges
        return normalized_workflow

    def list_workflows(self) -> WorkflowListResponse:
        workflows_dir = self._ensure_workflows_dir()
        summaries: list[WorkflowFileSummary] = []

        for path in sorted(workflows_dir.rglob("*.json")):
            stat = path.stat()
            summaries.append(
                WorkflowFileSummary(
                    filename=path.name,
                    path=str(path),
                    updated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    size_bytes=stat.st_size,
                )
            )

        return WorkflowListResponse(
            default_filename=self._default_filename(),
            workflows=summaries,
        )

    def load_default_workflow(self) -> WorkflowFileResponse:
        return self.load_workflow(self._default_filename())

    def load_workflow(self, filename: str) -> WorkflowFileResponse:
        workflow_path = self._workflow_path(filename)
        if not workflow_path.exists():
            raise WorkflowNotFoundError(f"Workflow file not found: {workflow_path.name}")

        try:
            with workflow_path.open("r", encoding="utf-8") as workflow_file:
                workflow = json.load(workflow_file)
        except json.JSONDecodeError as exc:
            raise WorkflowStorageError(
                f"Workflow file '{workflow_path.name}' contains invalid JSON: {exc.msg}"
            ) from exc

        if not isinstance(workflow, dict):
            raise WorkflowStorageError(
                f"Workflow file '{workflow_path.name}' must contain a JSON object at the top level."
            )

        workflow = self.normalize_workflow_payload(workflow, workflow_path.name)

        return WorkflowFileResponse(
            filename=workflow_path.name,
            path=str(workflow_path),
            workflow=workflow,
        )

    def save_default_workflow(self, workflow: dict[str, object]) -> WorkflowSaveResponse:
        return self.save_workflow(self._default_filename(), workflow, directory=None)

    def save_workflow(
        self,
        filename: str,
        workflow: dict[str, object],
        directory: str | None = None,
    ) -> WorkflowSaveResponse:
        workflow_path = self._workflow_path(filename, directory)
        normalized_workflow = self.normalize_workflow_payload(workflow, workflow_path.name)

        try:
            payload = json.dumps(normalized_workflow, indent=2)
        except TypeError as exc:
            raise WorkflowStorageError(
                f"Workflow could not be serialized to JSON: {exc}"
            ) from exc

        with workflow_path.open("w", encoding="utf-8") as workflow_file:
            workflow_file.write(payload)
            workflow_file.write("\n")

        saved_at = datetime.now(tz=timezone.utc)
        return WorkflowSaveResponse(
            filename=workflow_path.name,
            path=str(workflow_path),
            saved_at=saved_at,
        )


workflow_storage_service = WorkflowStorageService(
    workflows_dir=Path(__file__).resolve().parents[3] / "workflows"
)
