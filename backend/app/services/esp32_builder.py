import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from app.models.esp32_builder import (
    Esp32BoardDetail,
    Esp32BoardListResponse,
    Esp32BoardSummary,
    Esp32BuilderFile,
    Esp32CustomBlockDeleteResponse,
    Esp32CustomBlockSaveResponse,
    Esp32FirmwareActionResponse,
    Esp32FileSaveResponse,
    Esp32FunctionBlueprint,
    Esp32ToolchainStatus,
    Esp32WorkflowFirmwareBoardPlan,
    Esp32WorkflowFirmwarePlanRequest,
    Esp32WorkflowFirmwarePlanResponse,
    Esp32WorkflowFirmwarePlanRoutine,
)
from app.services.serial_ports import SerialPortInfo as _SerialPortInfo
from app.services.serial_ports import list_serial_ports


class Esp32BuilderError(RuntimeError):
    pass


class Esp32BuilderService:
    ESP32_PACKAGE_INDEX_URL = "https://espressif.github.io/arduino-esp32/package_esp32_index.json"
    DEFAULT_FQBN = "esp32:esp32:esp32"
    AUTO_RESET_NOTE = (
        "ESP32 auto-reset usually works when the USB-UART bridge exposes DTR/RTS to EN and GPIO0. "
        "If upload still fails to connect, hold BOOT while the upload starts and release it when flashing begins."
    )

    def __init__(self, repo_root: Path, app_functions_dir: Path) -> None:
        self._repo_root = repo_root
        self._root_dir = repo_root / "functions" / "esp 32 code"
        self._app_functions_dir = app_functions_dir
        self._arduino_cli_dir = repo_root / ".arduino-cli"
        self._arduino_cli_config_file = self._arduino_cli_dir / "arduino-cli.yaml"
        self._arduino_cli_data_dir = self._arduino_cli_dir / "data"
        self._arduino_cli_downloads_dir = self._arduino_cli_dir / "downloads"
        self._arduino_cli_user_dir = self._arduino_cli_dir / "user"
        self._arduino_cli_build_dir = self._arduino_cli_dir / "build"
        self._arduino_cli_cache_dir = self._arduino_cli_dir / "cache"
        # Track in-flight compile/upload subprocesses so an E-Stop can kill them
        # mid-flash instead of letting the board finish flashing.
        self._flash_processes_guard = Lock()
        self._active_flash_processes: set[subprocess.Popen] = set()
        self._flash_stop_requested = False

    def emergency_stop(self) -> dict[str, object]:
        """Abort any compile/upload that is currently running.

        Kills the whole arduino-cli process group (it spawns esptool as a child),
        so flashing actually halts instead of running to completion.
        """
        with self._flash_processes_guard:
            self._flash_stop_requested = True
            processes = list(self._active_flash_processes)

        for process in processes:
            self._terminate_flash_process(process)

        return {
            "ok": True,
            "tool": "esp32_flash",
            "message": (
                f"Aborted {len(processes)} in-progress ESP32 flash process(es)."
                if processes
                else "No ESP32 flash was in progress."
            ),
        }

    def clear_flash_stop(self) -> None:
        """Reset the cancellation flag before starting a fresh flash run."""
        with self._flash_processes_guard:
            self._flash_stop_requested = False

    def _terminate_flash_process(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            process_group = os.getpgid(process.pid)
            os.killpg(process_group, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process_group, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # Process already gone, or no permission/POSIX group: fall back to
            # terminating just the immediate child.
            try:
                process.kill()
            except ProcessLookupError:
                pass

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

        metadata = self._load_board_metadata(workspace_dir)
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
            firmware_entry_file=self._firmware_entry_file(metadata),
            fqbn=self._board_fqbn(metadata),
            toolchain=self._toolchain_status(),
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

        self._write_text_atomic(target_path, content)
        self.sync_generated_functions()

        return Esp32FileSaveResponse(
            board_id=board_id,
            relative_path=relative_path,
            saved_at=datetime.now(timezone.utc),
        )

    def build_firmware(self, board_id: str) -> Esp32FirmwareActionResponse:
        self._ensure_root_structure()
        workspace_dir = self._resolve_workspace_dir(board_id)
        if not workspace_dir.exists():
            raise Esp32BuilderError(f"Unknown ESP32 board '{board_id}'.")

        metadata = self._load_board_metadata(workspace_dir)
        sketch_dir, sketch_entry_file = self._prepare_sketch_dir(board_id, workspace_dir, metadata)
        fqbn = self._board_fqbn(metadata)

        command = [
            *self._cli_prefix(),
            "compile",
            "--verbose",
            "--fqbn",
            fqbn,
            "--output-dir",
            str(self._arduino_cli_build_dir / board_id),
            str(sketch_dir),
        ]
        return self._run_firmware_action(
            board_id=board_id,
            action="build",
            fqbn=fqbn,
            port=self._coerce_nullable_string(metadata.get("port")),
            sketch_entry_file=sketch_entry_file,
            command=command,
            auto_reset_attempted=False,
        )

    def flash_firmware(self, board_id: str) -> Esp32FirmwareActionResponse:
        self.clear_flash_stop()
        self._ensure_root_structure()
        workspace_dir = self._resolve_workspace_dir(board_id)
        if not workspace_dir.exists():
            raise Esp32BuilderError(f"Unknown ESP32 board '{board_id}'.")

        metadata = self._load_board_metadata(workspace_dir)
        port = self._resolve_flash_port(board_id, metadata)

        sketch_dir, sketch_entry_file = self._prepare_sketch_dir(board_id, workspace_dir, metadata)
        fqbn = self._board_fqbn(metadata)
        build_dir = self._arduino_cli_build_dir / board_id

        compile_command = [
            *self._cli_prefix(),
            "compile",
            "--verbose",
            "--fqbn",
            fqbn,
            "--output-dir",
            str(build_dir),
            str(sketch_dir),
        ]
        compile_result = self._run_firmware_action(
            board_id=board_id,
            action="build",
            fqbn=fqbn,
            port=port,
            sketch_entry_file=sketch_entry_file,
            command=compile_command,
            auto_reset_attempted=False,
        )

        if not compile_result.ok:
            return Esp32FirmwareActionResponse(
                board_id=board_id,
                action="flash",
                ok=False,
                fqbn=fqbn,
                port=port,
                sketch_entry_file=sketch_entry_file,
                command=compile_command,
                log=compile_result.log,
                auto_reset_attempted=False,
                auto_reset_note=self.AUTO_RESET_NOTE,
            )

        upload_command = [
            *self._cli_prefix(),
            "upload",
            "--verbose",
            "--fqbn",
            fqbn,
            "--port",
            port,
            "--input-dir",
            str(build_dir),
            str(sketch_dir),
        ]
        return self._run_firmware_action(
            board_id=board_id,
            action="flash",
            fqbn=fqbn,
            port=port,
            sketch_entry_file=sketch_entry_file,
            command=upload_command,
            auto_reset_attempted=True,
        )

    def plan_workflow_firmware(
        self,
        request: Esp32WorkflowFirmwarePlanRequest,
    ) -> Esp32WorkflowFirmwarePlanResponse:
        self._ensure_root_structure()

        board_plans: dict[str, Esp32WorkflowFirmwareBoardPlan] = {}
        routine_lookup: dict[
            tuple[str, str, str, str | None, str | None, str | None],
            Esp32WorkflowFirmwarePlanRoutine,
        ] = {}
        response_warnings: list[str] = []
        response_errors: list[str] = []

        for item in request.items:
            board_id = item.board_id.strip()
            block_label = item.block_name or item.block_id
            if not board_id:
                response_errors.append(f"Block '{block_label}' does not target an ESP32 board.")
                continue

            workspace_dir = self._resolve_workspace_dir(board_id)
            if not workspace_dir.exists():
                # A board without a builder workspace is an externally
                # programmed controller (e.g. the pre-flashed syringe ESP32):
                # its blocks talk to it over serial as-is, so there is nothing
                # to build or flash. Excluding it from the board plans also
                # keeps it out of the flash list.
                message = (
                    f"ESP32 board '{board_id}' (referenced by block '{block_label}') has no firmware "
                    "workspace; treating it as externally programmed and leaving its firmware untouched."
                )
                if message not in response_warnings:
                    response_warnings.append(message)
                continue

            board_plan = board_plans.get(board_id)
            if board_plan is None:
                metadata = self._load_board_metadata(workspace_dir)
                board_plan = Esp32WorkflowFirmwareBoardPlan(
                    board_id=board_id,
                    workspace_path=str(workspace_dir),
                    firmware_entry_file=self._firmware_entry_file(metadata) if metadata else None,
                )
                board_plans[board_id] = board_plan

            for requirement in item.requirements:
                source_path, source_exists, source_error = self._resolve_firmware_requirement_source(
                    workspace_dir,
                    requirement.source,
                )
                if source_error:
                    message = f"{board_id}: {source_error}"
                    if message not in board_plan.errors:
                        board_plan.errors.append(message)
                    if message not in response_errors:
                        response_errors.append(message)

                if requirement.source and not source_exists:
                    missing_source = requirement.source
                    if missing_source not in board_plan.missing_sources:
                        board_plan.missing_sources.append(missing_source)
                    message = (
                        f"{board_id}: firmware source '{requirement.source}' for routine "
                        f"'{requirement.routine_id}' was not found."
                    )
                    if message not in response_errors:
                        response_errors.append(message)

                if not requirement.source:
                    message = (
                        f"{board_id}: routine '{requirement.routine_id}' has no explicit firmware source yet."
                    )
                    if message not in board_plan.warnings:
                        board_plan.warnings.append(message)
                    if message not in response_warnings:
                        response_warnings.append(message)

                routine_key = (
                    board_id,
                    requirement.routine_id,
                    requirement.controller_role,
                    requirement.source,
                    requirement.protocol,
                    requirement.entry_point,
                )
                routine = routine_lookup.get(routine_key)
                if routine is None:
                    routine = Esp32WorkflowFirmwarePlanRoutine(
                        routine_id=requirement.routine_id,
                        controller_role=requirement.controller_role,
                        source=requirement.source,
                        protocol=requirement.protocol,
                        entry_point=requirement.entry_point,
                        required_device_ids=list(requirement.required_device_ids),
                        description=requirement.description,
                        source_path=source_path,
                        source_exists=source_exists,
                        block_ids=[item.block_id],
                    )
                    routine_lookup[routine_key] = routine
                    board_plan.routines.append(routine)
                    continue

                if item.block_id not in routine.block_ids:
                    routine.block_ids.append(item.block_id)
                for device_id in requirement.required_device_ids:
                    if device_id not in routine.required_device_ids:
                        routine.required_device_ids.append(device_id)

        for board_plan in board_plans.values():
            board_plan.routines.sort(key=lambda routine: routine.routine_id.lower())

        return Esp32WorkflowFirmwarePlanResponse(
            ok=not response_errors,
            boards=list(board_plans.values()),
            warnings=response_warnings,
            errors=response_errors,
        )

    def sync_generated_functions(self) -> None:
        self._ensure_root_structure()

        for workspace_dir in self._workspace_dirs():
            metadata = self._load_board_metadata(workspace_dir)
            blueprints, _errors = self._load_blueprints(workspace_dir)
            for blueprint in blueprints:
                manifest = blueprint.manifest
                function_dir = self._app_functions_dir / manifest.id
                function_dir.mkdir(parents=True, exist_ok=True)

                manifest_path = function_dir / "manifest.json"
                handler_path = function_dir / "handler.py"
                requirements_path = function_dir / "requirements.txt"

                manifest_data = manifest.model_dump()
                manifest_data["builder_board_id"] = metadata.get("board_id") or self._board_id_from_workspace(workspace_dir)
                manifest_data["builder_source_path"] = blueprint.source_path
                manifest_data["builder_workspace_path"] = str(workspace_dir)
                manifest_data["builder_firmware_entry_file"] = blueprint.firmware_entry_file
                manifest_data["builder_base_function_id"] = blueprint.base_function_id
                if not manifest_data.get("firmware_requirements"):
                    manifest_data["firmware_requirements"] = [
                        self._default_firmware_requirement_for_blueprint(
                            manifest_id=manifest.id,
                            firmware_entry_file=blueprint.firmware_entry_file,
                            protocol=blueprint.protocol,
                            hardware_device_ids=[
                                device.id
                                for device in manifest.hardware_devices
                            ],
                        )
                    ]

                self._write_text_atomic(
                    manifest_path,
                    json.dumps(manifest_data, indent=2) + "\n",
                )

                if not handler_path.exists():
                    copied_handler = self._copy_base_function_file(
                        blueprint.base_function_id,
                        "handler.py",
                        handler_path,
                    )
                    if not copied_handler:
                        self._write_text_atomic(
                            handler_path,
                            self._generated_placeholder_handler(manifest.id),
                        )

                if not requirements_path.exists():
                    copied_requirements = self._copy_base_function_file(
                        blueprint.base_function_id,
                        "requirements.txt",
                        requirements_path,
                    )
                    if not copied_requirements:
                        self._write_text_atomic(
                            requirements_path,
                            "# Add per-function runtime dependencies here.\n",
                        )

    def save_custom_block(
        self,
        board_id: str,
        source_function_id: str,
        display_name: str,
        description: str | None,
        defaults: dict[str, str | float | bool | None],
    ) -> Esp32CustomBlockSaveResponse:
        self._ensure_root_structure()
        workspace_dir = self._resolve_workspace_dir(board_id)
        if not workspace_dir.exists():
            raise Esp32BuilderError(f"Unknown ESP32 board '{board_id}'.")

        blueprints, _errors = self._load_blueprints(workspace_dir)
        base_blueprint = next(
            (blueprint for blueprint in blueprints if blueprint.manifest.id == source_function_id),
            None,
        )
        if base_blueprint is None:
            raise Esp32BuilderError(
                f"Could not find source blueprint '{source_function_id}' in board '{board_id}'."
            )

        normalized_display_name = display_name.strip()
        if not normalized_display_name:
            raise Esp32BuilderError("Custom block name cannot be empty.")

        blueprint_dir = workspace_dir / "workflow-functions"
        blueprint_dir.mkdir(parents=True, exist_ok=True)

        function_id = self._unique_function_id(
            self._slugify_identifier(normalized_display_name),
            existing_ids={blueprint.manifest.id for blueprint in blueprints},
        )

        blueprint_payload = base_blueprint.model_dump()
        blueprint_payload["base_function_id"] = source_function_id
        blueprint_payload["source_path"] = None

        manifest_payload = blueprint_payload["manifest"]
        manifest_payload["id"] = function_id
        manifest_payload["display_name"] = normalized_display_name
        manifest_payload["description"] = (
            description.strip()
            if isinstance(description, str) and description.strip()
            else f"Reusable preset based on {base_blueprint.manifest.display_name}."
        )
        manifest_payload["inputs"] = self._apply_default_overrides(
            manifest_payload.get("inputs", []),
            defaults,
        )
        manifest_payload["advanced_inputs"] = self._apply_default_overrides(
            manifest_payload.get("advanced_inputs", []),
            defaults,
        )
        blueprint_payload["advanced_builder_inputs"] = self._apply_default_overrides(
            blueprint_payload.get("advanced_builder_inputs", []),
            defaults,
        )

        blueprint_path = blueprint_dir / f"{function_id}.json"
        self._write_text_atomic(
            blueprint_path,
            json.dumps(blueprint_payload, indent=2) + "\n",
        )

        self.sync_generated_functions()

        return Esp32CustomBlockSaveResponse(
            board_id=board_id,
            function_id=function_id,
            display_name=normalized_display_name,
            blueprint_path=str(blueprint_path),
            saved_at=datetime.now(timezone.utc),
        )

    def delete_custom_block(
        self,
        board_id: str,
        function_id: str,
    ) -> Esp32CustomBlockDeleteResponse:
        self._ensure_root_structure()
        workspace_dir = self._resolve_workspace_dir(board_id)
        if not workspace_dir.exists():
            raise Esp32BuilderError(f"Unknown ESP32 board '{board_id}'.")

        blueprints, _errors = self._load_blueprints(workspace_dir)
        blueprint = next(
            (item for item in blueprints if item.manifest.id == function_id),
            None,
        )
        if blueprint is None or not blueprint.source_path:
            raise Esp32BuilderError(f"Could not find reusable block '{function_id}' in board '{board_id}'.")

        if not blueprint.base_function_id:
            raise Esp32BuilderError("Only saved custom block presets can be deleted from the block library.")

        blueprint_path = Path(blueprint.source_path)
        if blueprint_path.exists():
            blueprint_path.unlink()

        function_dir = self._app_functions_dir / function_id
        if function_dir.exists():
            shutil.rmtree(function_dir)

        self.sync_generated_functions()

        return Esp32CustomBlockDeleteResponse(
            board_id=board_id,
            function_id=function_id,
            display_name=blueprint.manifest.display_name,
            blueprint_path=str(blueprint_path),
            deleted_at=datetime.now(timezone.utc),
        )

    def _ensure_root_structure(self) -> None:
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._arduino_cli_dir.mkdir(parents=True, exist_ok=True)
        self._arduino_cli_data_dir.mkdir(parents=True, exist_ok=True)
        self._arduino_cli_downloads_dir.mkdir(parents=True, exist_ok=True)
        self._arduino_cli_user_dir.mkdir(parents=True, exist_ok=True)
        self._arduino_cli_build_dir.mkdir(parents=True, exist_ok=True)
        self._arduino_cli_cache_dir.mkdir(parents=True, exist_ok=True)
        instructions_path = self._instructions_path()
        if not instructions_path.exists():
            self._write_text_atomic(instructions_path, self._instructions_markdown())
        self._ensure_cli_config_file()

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

    def _firmware_entry_file(self, metadata: dict[str, str | None]) -> str:
        firmware_entry = self._coerce_nullable_string(metadata.get("firmware_entry_file"))
        return firmware_entry or "firmware/main.ino"

    def _resolve_firmware_requirement_source(
        self,
        workspace_dir: Path,
        source: str | None,
    ) -> tuple[str | None, bool, str | None]:
        normalized_source = source.strip() if isinstance(source, str) else None
        if not normalized_source:
            return None, False, None

        workspace_path = workspace_dir.resolve()
        source_candidate = Path(normalized_source)
        source_path = (
            source_candidate.resolve()
            if source_candidate.is_absolute()
            else (workspace_path / source_candidate).resolve()
        )

        try:
            source_path.relative_to(workspace_path)
        except ValueError:
            return (
                str(source_path),
                False,
                f"firmware source '{normalized_source}' resolves outside board workspace.",
            )

        return str(source_path), source_path.exists(), None

    def _board_fqbn(self, metadata: dict[str, str | None]) -> str:
        configured = self._coerce_nullable_string(metadata.get("fqbn"))
        return configured or self.DEFAULT_FQBN

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
        existing_metadata = self._load_board_metadata(workspace_dir)
        board_metadata = {
            "board_id": existing_metadata.get("board_id") or board_id,
            "display_name": existing_metadata.get("display_name") or f"ESP32 {Path(port.device).name}",
            "port": port.device,
            "description": port.description or existing_metadata.get("description"),
            "hardware_id": port.hardware_id or existing_metadata.get("hardware_id"),
            "serial_number": port.serial_number or existing_metadata.get("serial_number"),
            "firmware_entry_file": existing_metadata.get("firmware_entry_file") or "firmware/main.ino",
            "fqbn": existing_metadata.get("fqbn") or self.DEFAULT_FQBN,
        }
        self._write_text_atomic(
            board_metadata_path,
            json.dumps(board_metadata, indent=2) + "\n",
        )

        firmware_path = firmware_dir / "main.ino"
        if not firmware_path.exists():
            self._write_text_atomic(firmware_path, self._default_syringe_firmware())

        notes_path = workspace_dir / "NOTES.md"
        if not notes_path.exists():
            self._write_text_atomic(notes_path, self._default_workspace_notes(port))

        blueprint_path = blueprint_dir / "dispense.json"
        existing_blueprints = list(blueprint_dir.glob("*.json"))
        if not existing_blueprints and not blueprint_path.exists():
            self._write_text_atomic(
                blueprint_path,
                json.dumps(self._default_dispense_blueprint(port.device), indent=2) + "\n",
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

    def _write_text_atomic(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                if path.read_text(encoding="utf-8") == content:
                    return
            except UnicodeDecodeError:
                pass

        path.write_text(content, encoding="utf-8")

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

    def _slugify_identifier(self, value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
        return normalized or "custom_block"

    def _unique_function_id(self, candidate: str, existing_ids: set[str]) -> str:
        if candidate not in existing_ids:
            return candidate

        suffix = 2
        while f"{candidate}_{suffix}" in existing_ids:
            suffix += 1

        return f"{candidate}_{suffix}"

    def _apply_default_overrides(
        self,
        definitions: list[dict[str, object]],
        defaults: dict[str, str | float | bool | None],
    ) -> list[dict[str, object]]:
        updated_definitions: list[dict[str, object]] = []
        for definition in definitions:
            next_definition = dict(definition)
            key = next_definition.get("key")
            if isinstance(key, str) and key in defaults:
                next_definition["default"] = defaults[key]
            updated_definitions.append(next_definition)

        return updated_definitions

    def _copy_base_function_file(
        self,
        base_function_id: str | None,
        filename: str,
        destination_path: Path,
    ) -> bool:
        if not base_function_id:
            return False

        source_path = self._app_functions_dir / base_function_id / filename
        if not source_path.exists():
            return False

        shutil.copy2(source_path, destination_path)
        return True

    def _load_blueprints(self, workspace_dir: Path) -> tuple[list[Esp32FunctionBlueprint], list[str]]:
        blueprint_dir = workspace_dir / "workflow-functions"
        if not blueprint_dir.exists():
            return [], []

        blueprints: list[Esp32FunctionBlueprint] = []
        errors: list[str] = []

        for blueprint_path in sorted(blueprint_dir.glob("*.json")):
            try:
                blueprint = Esp32FunctionBlueprint.model_validate_json(
                    blueprint_path.read_text(encoding="utf-8-sig")
                )
            except Exception as exc:
                errors.append(f"{blueprint_path.name}: {exc}")
                continue

            blueprint.source_path = str(blueprint_path)
            blueprints.append(blueprint)

        return blueprints, errors

    def _default_firmware_requirement_for_blueprint(
        self,
        manifest_id: str,
        firmware_entry_file: str,
        protocol: str,
        hardware_device_ids: list[str],
    ) -> dict[str, object]:
        return {
            "routine_id": manifest_id,
            "controller_role": "builder_board",
            "source": firmware_entry_file,
            "protocol": protocol,
            "entry_point": manifest_id,
            "required_device_ids": hardware_device_ids,
            "description": "Generated default firmware routine requirement for this ESP32 workflow function.",
        }

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

    def resolve_board_port(self, board_id: str) -> str | None:
        """Current port for a board, identified by USB serial number when
        known. Returns None when the board has no workspace or cannot be
        found, so callers can fall back to their own default."""
        workspace_dir = self._resolve_workspace_dir(board_id)
        if not workspace_dir.exists():
            return None
        try:
            return self._resolve_flash_port(board_id, self._load_board_metadata(workspace_dir))
        except Esp32BuilderError:
            return None

    def _resolve_flash_port(self, board_id: str, metadata: dict) -> str:
        """Find the port to flash, preferring the board's USB serial number.

        Linux hands out /dev/ttyUSB* in plug order, so a board that is
        unplugged and reconnected (or simply powered up in a different order)
        can move between ttyUSB0 and ttyUSB1. Flashing the recorded port then
        either fails outright or - far worse - writes this board's firmware
        into whatever else happens to be sitting on that port now. The USB
        serial number identifies the physical chip, so trust it over the port
        whenever we have one.
        """
        recorded_port = self._coerce_nullable_string(metadata.get("port"))
        expected_serial = self._coerce_nullable_string(metadata.get("serial_number"))

        if expected_serial:
            for candidate in self._list_serial_ports():
                if candidate.serial_number == expected_serial:
                    return candidate.device
            raise Esp32BuilderError(
                f"ESP32 '{board_id}' (USB serial {expected_serial}) is not connected. "
                "Plug the board in - it is identified by its serial number, so it can be on any USB port."
            )

        if not recorded_port:
            raise Esp32BuilderError("This board does not have a serial port associated with it yet.")

        # No serial number recorded: fall back to the port, but only if the
        # device actually exists, so the failure names the real problem.
        if not any(candidate.device == recorded_port for candidate in self._list_serial_ports()):
            connected = ", ".join(candidate.device for candidate in self._list_serial_ports()) or "none"
            raise Esp32BuilderError(
                f"ESP32 '{board_id}' is mapped to {recorded_port}, but no such port is connected "
                f"(currently connected: {connected}). Reconnect the board, or record its USB serial "
                "number on the board so it can be found on any port."
            )
        return recorded_port

    def _list_serial_ports(self) -> list[_SerialPortInfo]:
        return list_serial_ports()

    def _ensure_cli_config_file(self) -> None:
        if self._arduino_cli_config_file.exists():
            return

        self._arduino_cli_config_file.write_text(
            "\n".join([
                "board_manager:",
                f"  additional_urls:",
                f"    - {self.ESP32_PACKAGE_INDEX_URL}",
                "directories:",
                f"  data: {self._arduino_cli_data_dir}",
                f"  downloads: {self._arduino_cli_downloads_dir}",
                f"  user: {self._arduino_cli_user_dir}",
                "library:",
                "  enable_unsafe_install: false",
                "",
            ]),
            encoding="utf-8",
        )

    def _cli_path(self) -> str | None:
        configured = self._coerce_nullable_string(os.getenv("ARDUINO_CLI_PATH"))
        candidates = [
            configured,
            str(self._repo_root / "tools" / "arduino-cli" / "arduino-cli"),
            shutil.which("arduino-cli"),
        ]

        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate

        return None

    def _toolchain_status(self) -> Esp32ToolchainStatus:
        return Esp32ToolchainStatus(
            arduino_cli_available=self._cli_path() is not None,
            arduino_cli_path=self._cli_path(),
            config_file=str(self._arduino_cli_config_file),
            package_index_url=self.ESP32_PACKAGE_INDEX_URL,
            fqbn_default=self.DEFAULT_FQBN,
            auto_reset_note=self.AUTO_RESET_NOTE,
        )

    def _cli_prefix(self) -> list[str]:
        cli_path = self._cli_path()
        if not cli_path:
            raise Esp32BuilderError(
                "arduino-cli is not installed on this Pi yet. Install it first before compiling or uploading ESP32 firmware."
            )

        return [
            cli_path,
            "--config-file",
            str(self._arduino_cli_config_file),
            "--additional-urls",
            self.ESP32_PACKAGE_INDEX_URL,
        ]

    def _prepare_sketch_dir(
        self,
        board_id: str,
        workspace_dir: Path,
        metadata: dict[str, str | None],
    ) -> tuple[Path, str]:
        firmware_entry_rel = self._firmware_entry_file(metadata)
        firmware_entry_path = workspace_dir / firmware_entry_rel
        if not firmware_entry_path.exists():
            raise Esp32BuilderError(f"Firmware entry file not found: {firmware_entry_path}")

        sketch_name = re.sub(r"[^A-Za-z0-9_]+", "_", board_id) or "esp32_board"
        temp_root = Path(tempfile.mkdtemp(prefix=f"esp32-{sketch_name}-", dir="/tmp"))
        sketch_dir = temp_root / sketch_name
        sketch_dir.mkdir(parents=True, exist_ok=True)

        firmware_dir = firmware_entry_path.parent
        for source_file in firmware_dir.iterdir():
            if not source_file.is_file():
                continue

            destination_name = source_file.name
            if source_file.resolve() == firmware_entry_path.resolve():
                destination_name = f"{sketch_name}.ino"

            shutil.copy2(source_file, sketch_dir / destination_name)

        return sketch_dir, str(firmware_entry_path)

    def _run_firmware_action(
        self,
        board_id: str,
        action: str,
        fqbn: str,
        port: str | None,
        sketch_entry_file: str,
        command: list[str],
        auto_reset_attempted: bool,
    ) -> Esp32FirmwareActionResponse:
        env = os.environ.copy()
        env["XDG_CACHE_HOME"] = str(self._arduino_cli_cache_dir)

        # Refuse to even start if an E-Stop already fired for this run.
        with self._flash_processes_guard:
            if self._flash_stop_requested:
                return self._cancelled_firmware_response(
                    board_id, action, fqbn, port, sketch_entry_file, command, auto_reset_attempted
                )

        try:
            # start_new_session puts arduino-cli (and the esptool child it
            # spawns) in their own process group so an E-Stop can kill the whole
            # tree, not just the parent.
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                start_new_session=True,
            )
        except Exception as exc:
            raise Esp32BuilderError(f"Could not run firmware {action}: {exc}") from exc

        with self._flash_processes_guard:
            self._active_flash_processes.add(process)
            # An E-Stop could have arrived between the check above and registering.
            stop_already_requested = self._flash_stop_requested
        if stop_already_requested:
            self._terminate_flash_process(process)

        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._terminate_flash_process(process)
            stdout, stderr = process.communicate()
        finally:
            with self._flash_processes_guard:
                self._active_flash_processes.discard(process)
                stop_requested = self._flash_stop_requested

        if stop_requested:
            return self._cancelled_firmware_response(
                board_id, action, fqbn, port, sketch_entry_file, command, auto_reset_attempted
            )

        combined_log = "\n".join(
            part for part in [(stdout or "").strip(), (stderr or "").strip()] if part
        ).strip()
        if timed_out:
            combined_log = (f"Firmware {action} timed out after 600s and was terminated.\n{combined_log}").strip()
        if not combined_log:
            combined_log = f"No output was produced while running {action}."

        return Esp32FirmwareActionResponse(
            board_id=board_id,
            action=action,
            ok=process.returncode == 0,
            fqbn=fqbn,
            port=port,
            sketch_entry_file=sketch_entry_file,
            command=command,
            log=combined_log,
            auto_reset_attempted=auto_reset_attempted,
            auto_reset_note=self.AUTO_RESET_NOTE,
        )

    def _cancelled_firmware_response(
        self,
        board_id: str,
        action: str,
        fqbn: str,
        port: str | None,
        sketch_entry_file: str,
        command: list[str],
        auto_reset_attempted: bool,
    ) -> Esp32FirmwareActionResponse:
        return Esp32FirmwareActionResponse(
            board_id=board_id,
            action=action,
            ok=False,
            fqbn=fqbn,
            port=port,
            sketch_entry_file=sketch_entry_file,
            command=command,
            log=f"Firmware {action} was cancelled by E-Stop before it could finish.",
            auto_reset_attempted=auto_reset_attempted,
            auto_reset_note=self.AUTO_RESET_NOTE,
        )

    def _default_workspace_notes(self, port: _SerialPortInfo) -> str:
        return (
            f"# ESP32 Workspace Notes\n\n"
            f"- Port: `{port.device}`\n"
            f"- Display: `{port.description or 'ESP32 board'}`\n"
            f"- This folder stores the local source files and block blueprint metadata that the Pi UI edits.\n"
            f"- Compile and upload these sources from the Pi after the ESP32 hardware map is correct.\n"
        )

    def _instructions_markdown(self) -> str:
        return """# ESP32 Workspace Structure

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
        "key": "next",
        "label": "Next",
        "type": "flow"
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
- Use `manifest.outputs` only for control-flow branches. Normal robot actions should expose a single `next` flow output; the Workflow Editor can add an `error` path from block settings. Data returned by the handler, such as status strings or controller replies, should stay in the handler result and should not become output handles.
- Put firmware wiring and board-specific tuning in `advanced_builder_inputs`.
- Declare every motor, servo, and sensor the function uses in `manifest.hardware_devices`. The Hardware Map will create/update those devices, and advanced functions should resolve wiring from those shared devices instead of duplicating hidden pin state.
- Keep source code changes in `firmware/main.ino`.

## Workflow block types

- Basic blocks are built into the editor or generated from the Hardware Map for simple stepper, servo, and sensor actions.
- Advanced functions are generated from these ESP32 workflow-function blueprints and run through the backend function endpoint.
- Compound functions are created in the Workflow Editor by selecting directly connected canvas blocks and collapsing them from the right-click menu.
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
        head_pin_defaults = {
            "A": {"step": 33, "dir": 32},
            "B": {"step": 25, "dir": 4},
            "C": {"step": 26, "dir": 5},
            "D": {"step": 27, "dir": 18},
            "E": {"step": 14, "dir": 19},
            "F": {"step": 12, "dir": 21},
            "G": {"step": 13, "dir": 22},
        }

        advanced_inputs: list[dict[str, object]] = [
            {
                "key": "intake_speed",
                "label": "Intake Speed",
                "type": "number",
                "description": "Overrides the shared dispense speed for the first part of the move.",
                "required": False,
                "default": 100,
                "advanced": True,
            },
            {
                "key": "outtake_speed",
                "label": "Outtake Speed",
                "type": "number",
                "description": "Overrides the shared dispense speed for the return move in the opposite direction.",
                "required": False,
                "default": 100,
                "advanced": True,
            },
        ]
        advanced_builder_inputs: list[dict[str, object]] = [
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
                "description": "Default microstep configuration passed to the driver timing calculations.",
                "required": False,
                "default": 1,
            },
            {
                "key": "step_pulse_width_micros",
                "label": "Step Pulse Width (us)",
                "type": "number",
                "description": "Width of each HIGH pulse sent to the step pin.",
                "required": False,
                "default": 8,
            },
            {
                "key": "settle_delay_ms",
                "label": "Settle Delay (ms)",
                "type": "number",
                "description": "Delay between the forward and return syringe moves.",
                "required": False,
                "default": 20,
            },
            {
                "key": "intake_speed",
                "label": "Default Intake Speed",
                "type": "number",
                "description": "Default forward speed stored in firmware presets.",
                "required": False,
                "default": 100,
            },
            {
                "key": "outtake_speed",
                "label": "Default Outtake Speed",
                "type": "number",
                "description": "Default return speed stored in firmware presets.",
                "required": False,
                "default": 100,
            },
        ]
        hardware_devices: list[dict[str, object]] = []

        for head, pins in head_pin_defaults.items():
            head_key = head.lower()
            advanced_inputs.extend([
                {
                    "key": f"head_{head_key}_step_pin",
                    "label": f"Head {head} Step Pin",
                    "type": "number",
                    "description": f"GPIO step pin for syringe head {head} when saving a reusable hardware preset.",
                    "required": False,
                    "default": pins["step"],
                    "advanced": True,
                },
                {
                    "key": f"head_{head_key}_dir_pin",
                    "label": f"Head {head} Dir Pin",
                    "type": "number",
                    "description": f"GPIO direction pin for syringe head {head} when saving a reusable hardware preset.",
                    "required": False,
                    "default": pins["dir"],
                    "advanced": True,
                },
            ])
            advanced_builder_inputs.extend([
                {
                    "key": f"head_{head_key}_step_pin",
                    "label": f"Head {head} Step Pin",
                    "type": "number",
                    "description": f"GPIO step pin for syringe head {head}.",
                    "required": False,
                    "default": pins["step"],
                },
                {
                    "key": f"head_{head_key}_dir_pin",
                    "label": f"Head {head} Dir Pin",
                    "type": "number",
                    "description": f"GPIO direction pin for syringe head {head}.",
                    "required": False,
                    "default": pins["dir"],
                },
            ])
            hardware_devices.append({
                "id": f"syringe-head-{head_key}",
                "name": f"Syringe Head {head}",
                "kind": "stepper_motor",
                "board_id": "ttyUSB0",
                "basic_block_id": f"basic-stepper-syringe-head-{head_key}",
                "pins": [
                    {
                        "id": f"head-{head_key}-dir",
                        "signal": "direction",
                        "function_input_key": f"head_{head_key}_dir_pin",
                    },
                    {
                        "id": f"head-{head_key}-step",
                        "signal": "step",
                        "function_input_key": f"head_{head_key}_step_pin",
                    },
                    {"id": f"head-{head_key}-enable", "signal": "enable", "gpio": "-"},
                    {"id": f"head-{head_key}-ms1", "signal": "micro_step_1", "gpio": "-"},
                    {"id": f"head-{head_key}-ms2", "signal": "micro_step_2", "gpio": "-"},
                    {"id": f"head-{head_key}-ms3", "signal": "micro_step_3", "gpio": "-"},
                ],
            })

        return {
            "schema_version": 1,
            "manifest": {
                "schema_version": 1,
                "id": "dispense",
                "display_name": "7 Syringe Dispenser",
                "category": "Robot Actions",
                "description": "Drive the 7-head syringe ESP32 with calibration-aware dispense amounts.",
                "version": "0.3.0",
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
                        "description": "Shared fallback speed used when dedicated intake and outtake speeds are not set.",
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
                "advanced_inputs": advanced_inputs,
                "hardware_devices": hardware_devices,
                "firmware_requirements": [
                    {
                        "routine_id": "dispense",
                        "controller_role": "builder_board",
                        "source": "firmware/main.ino",
                        "protocol": "serial-text",
                        "entry_point": "dispense",
                        "required_device_ids": [
                            device["id"]
                            for device in hardware_devices
                        ],
                        "description": "Firmware routine that drives the 7-head syringe dispenser.",
                    }
                ],
                "outputs": [
                    {
                        "key": "next",
                        "label": "Next",
                        "type": "flow",
                        "description": "Continue when the dispense request completes.",
                    },
                ],
            },
            "advanced_builder_inputs": advanced_builder_inputs,
            "firmware_entry_file": "firmware/main.ino",
            "protocol": "serial-text",
            "notes": "Normal inputs stay visible on the block. Expand advanced inputs for separate intake and outtake speeds, saved hardware pin presets, and reusable custom block templates.",
        }

    def _default_syringe_firmware(self) -> str:
        return """#include <Arduino.h>

const int NUM_SYRINGES = 7;
const int spr = 200;
int RPM = 100;
int IntakeRPM = 100;
int OuttakeRPM = 100;
int Microsteps = 1;
int StepPulseWidthMicros = 8;
int SettleDelayMs = 20;

int stepPins[NUM_SYRINGES] = {33, 25, 26, 27, 14, 12, 13};
int dirPins[NUM_SYRINGES]  = {32, 4, 5, 18, 19, 21, 22};

int dirSign[NUM_SYRINGES] = {-1, -1, -1, -1, -1, -1, -1};

void applyRPM(int nextRPM) {
  if (nextRPM <= 0) {
    return;
  }

  RPM = nextRPM;
  IntakeRPM = nextRPM;
  OuttakeRPM = nextRPM;

  Serial.print("OK SPEED ");
  Serial.println(RPM);
}

void applyIntakeRPM(int nextRPM) {
  if (nextRPM <= 0) {
    return;
  }

  IntakeRPM = nextRPM;
  Serial.print("OK INTAKE SPEED ");
  Serial.println(IntakeRPM);
}

void applyOuttakeRPM(int nextRPM) {
  if (nextRPM <= 0) {
    return;
  }

  OuttakeRPM = nextRPM;
  Serial.print("OK OUTTAKE SPEED ");
  Serial.println(OuttakeRPM);
}

unsigned long stepIntervalMicrosForRPM(int rpm) {
  float stepsPerSecond = (rpm * spr * Microsteps) / 60.0f;
  if (stepsPerSecond <= 0.0f) {
    stepsPerSecond = 1.0f;
  }

  unsigned long interval = (unsigned long)(1000000.0f / stepsPerSecond);
  unsigned long minimumInterval = (unsigned long)(StepPulseWidthMicros * 2);
  if (interval < minimumInterval) {
    return minimumInterval;
  }

  return interval;
}

void moveStepperBySteps(int index, long signedSteps, int rpm) {
  long totalSteps = labs(signedSteps);
  if (totalSteps == 0) {
    return;
  }

  bool forward = signedSteps >= 0;
  digitalWrite(dirPins[index], forward ? HIGH : LOW);
  delayMicroseconds(20);

  unsigned long intervalMicros = stepIntervalMicrosForRPM(rpm);
  unsigned long lowTimeMicros = intervalMicros > (unsigned long)StepPulseWidthMicros
    ? intervalMicros - (unsigned long)StepPulseWidthMicros
    : (unsigned long)StepPulseWidthMicros;

  for (long step = 0; step < totalSteps; step++) {
    digitalWrite(stepPins[index], HIGH);
    delayMicroseconds(StepPulseWidthMicros);
    digitalWrite(stepPins[index], LOW);
    delayMicroseconds(lowTimeMicros);
  }
}

void dispenseSteps(long s0, long s1, long s2, long s3, long s4, long s5, long s6) {
  long steps[NUM_SYRINGES] = {s0, s1, s2, s3, s4, s5, s6};

  Serial.print("ACTIVE INTAKE RPM ");
  Serial.println(IntakeRPM);
  Serial.print("ACTIVE OUTTAKE RPM ");
  Serial.println(OuttakeRPM);

  for (int i = 0; i < NUM_SYRINGES; i++) {
    if (steps[i] != 0) {
      long signedSteps = dirSign[i] * steps[i];
      moveStepperBySteps(i, signedSteps, IntakeRPM);

      if (SettleDelayMs > 0) {
        delay(SettleDelayMs);
      }

      moveStepperBySteps(i, -signedSteps, OuttakeRPM);

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

  if (cmd.startsWith("INTAKE_SPEED ")) {
    int parsed = sscanf(cmd.c_str(), "INTAKE_SPEED %ld", &nextRPM);
    if (parsed == 1) {
      applyIntakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("INTAKE_SPEED,")) {
    int parsed = sscanf(cmd.c_str(), "INTAKE_SPEED,%ld", &nextRPM);
    if (parsed == 1) {
      applyIntakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SET_INTAKE_SPEED,")) {
    int parsed = sscanf(cmd.c_str(), "SET_INTAKE_SPEED,%ld", &nextRPM);
    if (parsed == 1) {
      applyIntakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SET INTAKE SPEED ")) {
    int parsed = sscanf(cmd.c_str(), "SET INTAKE SPEED %ld", &nextRPM);
    if (parsed == 1) {
      applyIntakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("OUTTAKE_SPEED ")) {
    int parsed = sscanf(cmd.c_str(), "OUTTAKE_SPEED %ld", &nextRPM);
    if (parsed == 1) {
      applyOuttakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("OUTTAKE_SPEED,")) {
    int parsed = sscanf(cmd.c_str(), "OUTTAKE_SPEED,%ld", &nextRPM);
    if (parsed == 1) {
      applyOuttakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SET_OUTTAKE_SPEED,")) {
    int parsed = sscanf(cmd.c_str(), "SET_OUTTAKE_SPEED,%ld", &nextRPM);
    if (parsed == 1) {
      applyOuttakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SET OUTTAKE SPEED ")) {
    int parsed = sscanf(cmd.c_str(), "SET OUTTAKE SPEED %ld", &nextRPM);
    if (parsed == 1) {
      applyOuttakeRPM((int)nextRPM);
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
    digitalWrite(stepPins[i], LOW);
    digitalWrite(dirPins[i], LOW);
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
