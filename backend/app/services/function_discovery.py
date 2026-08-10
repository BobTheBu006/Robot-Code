import importlib.util
import json
from pathlib import Path
from types import ModuleType

from pydantic import ValidationError

from app.models.function_manifest import (
    DiscoveredFunctionDefinition,
    FunctionCancelResponse,
    FunctionDiscoveryError,
    FunctionDiscoveryResponse,
    FunctionManifest,
    FunctionTestResponse,
)
from app.services.esp32_builder import esp32_builder_service
from app.services.hardware_map import hardware_map_service


class FunctionDiscoveryService:
    def __init__(self, functions_dir: Path) -> None:
        self._functions_dir = functions_dir
        # handler path -> (source mtime, imported module)
        self._handler_modules: dict[str, tuple[int, ModuleType]] = {}

    def sync_generated_functions(self) -> None:
        """Regenerate function manifests from the ESP32 builder blueprints.

        Split out of `discover` because it writes to disk (manifests, and
        through them `hardware-map.json`). The frontend polls discovery after
        every successful block run, so leaving the write inside it meant a
        read-only-looking GET rewrote machine configuration on a timer.
        """
        esp32_builder_service.sync_generated_functions()

    def discover(self) -> FunctionDiscoveryResponse:
        discovered_functions: list[DiscoveredFunctionDefinition] = []
        errors: list[FunctionDiscoveryError] = []

        if not self._functions_dir.exists():
            return FunctionDiscoveryResponse(functions=[], errors=[])

        for entry in sorted(self._functions_dir.iterdir(), key=lambda path: path.name):
            if not entry.is_dir():
                continue

            manifest_path = entry / "manifest.json"
            handler_path = entry / "handler.py"
            requirements_path = entry / "requirements.txt"

            missing_files = [
                required_file.name
                for required_file in (manifest_path, handler_path, requirements_path)
                if not required_file.exists()
            ]
            if missing_files:
                errors.append(
                    FunctionDiscoveryError(
                        folder_name=entry.name,
                        message=f"Missing required files: {', '.join(missing_files)}",
                    )
                )
                continue

            try:
                with manifest_path.open("r", encoding="utf-8") as manifest_file:
                    raw_manifest = json.load(manifest_file)
                manifest = FunctionManifest.model_validate(raw_manifest)
            except FileNotFoundError:
                errors.append(
                    FunctionDiscoveryError(
                        folder_name=entry.name,
                        message="manifest.json could not be read.",
                    )
                )
                continue
            except json.JSONDecodeError as exc:
                errors.append(
                    FunctionDiscoveryError(
                        folder_name=entry.name,
                        message=f"manifest.json is invalid JSON: {exc.msg}",
                    )
                )
                continue
            except ValidationError as exc:
                errors.append(
                    FunctionDiscoveryError(
                        folder_name=entry.name,
                        message=f"manifest.json failed validation: {exc.errors()[0]['msg']}",
                    )
                )
                continue

            if manifest.id != entry.name:
                errors.append(
                    FunctionDiscoveryError(
                        folder_name=entry.name,
                        message="Manifest id must match the function folder name.",
                    )
                )
                continue

            discovered_functions.append(
                DiscoveredFunctionDefinition(
                    manifest=manifest,
                    folder_name=entry.name,
                    manifest_path=str(manifest_path),
                    handler_path=str(handler_path),
                    requirements_path=str(requirements_path),
                )
            )

        sorted_functions = sorted(discovered_functions, key=lambda item: item.manifest.display_name.lower())
        hardware_map_service.sync_manifest_devices([item.manifest for item in sorted_functions])

        return FunctionDiscoveryResponse(
            functions=sorted_functions,
            errors=errors,
        )

    def get_function(self, function_id: str) -> DiscoveredFunctionDefinition:
        discovery = self.discover()
        for discovered_function in discovery.functions:
            if discovered_function.manifest.id == function_id:
                return discovered_function

        raise ValueError(f"Unknown function '{function_id}'.")

    def _load_handler_module(self, discovered_function: DiscoveredFunctionDefinition) -> ModuleType:
        """Import a handler once and reuse it.

        Re-importing per call gave every request a *fresh* module object, so
        `cancel` operated on a different instance than the run it was meant to
        abort - any module-level state the handler held (an open serial
        session, a stop flag) was invisible to it. The cache is keyed on the
        handler path and its mtime, so editing a handler still picks up the
        new code without a backend restart.
        """
        handler_path = Path(discovered_function.handler_path)
        try:
            mtime = handler_path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        cache_key = str(handler_path)

        cached = self._handler_modules.get(cache_key)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        module_name = f"robot_function_{discovered_function.manifest.id}"
        spec = importlib.util.spec_from_file_location(module_name, handler_path)

        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load handler from {handler_path}.")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._handler_modules[cache_key] = (mtime, module)
        return module

    def test_function(
        self,
        function_id: str,
        inputs: dict[str, str | float | bool | None],
        input_data: dict[str, object] | None = None,
    ) -> FunctionTestResponse:
        discovered_function = self.get_function(function_id)

        try:
            handler_module = self._load_handler_module(discovered_function)
        except Exception as exc:  # pragma: no cover - defensive boundary around dynamic imports
            raise RuntimeError(
                f"Could not load handler for function '{function_id}': {exc}"
            ) from exc

        execute = getattr(handler_module, "execute", None)

        if not callable(execute):
            raise RuntimeError(
                f"Function '{function_id}' does not expose a callable execute(context, inputs)."
            )

        resolved_inputs = hardware_map_service.apply_function_defaults(discovered_function.manifest, inputs)
        hardware_map = hardware_map_service.load_map()
        context = {
            "mode": "test",
            "function_id": function_id,
            "manifest": discovered_function.manifest.model_dump(),
            "input_data": input_data,
            "hardware_map": hardware_map.model_dump(mode="json"),
        }

        try:
            result = execute(context, resolved_inputs)
        except Exception as exc:  # pragma: no cover - defensive boundary around plugin code
            raise RuntimeError(
                f"Function '{function_id}' test execution failed: {exc}"
            ) from exc

        if result is not None and not isinstance(result, dict):
            raise RuntimeError(
                f"Function '{function_id}' returned {type(result).__name__}; expected dict or None."
            )

        # A handler reports failure in-band by returning {"ok": false} (and
        # usually a message/error). Hardcoding ok=True here made every such
        # failure read as success to the caller, so a workflow kept running
        # past a block that had actually failed.
        payload = result or {}
        handler_ok = payload.get("ok", True)
        ok = bool(handler_ok) if isinstance(handler_ok, bool) else True
        error = None
        if not ok:
            reported = payload.get("error") or payload.get("message")
            error = str(reported) if reported else f"Function '{function_id}' reported failure."

        return FunctionTestResponse(
            function_id=function_id,
            ok=ok,
            inputs=resolved_inputs,
            input_data=input_data,
            result=payload,
            error=error,
        )

    def cancel_function(
        self,
        function_id: str,
        inputs: dict[str, str | float | bool | None],
    ) -> FunctionCancelResponse:
        discovered_function = self.get_function(function_id)

        try:
            handler_module = self._load_handler_module(discovered_function)
        except Exception as exc:  # pragma: no cover - defensive boundary around dynamic imports
            raise RuntimeError(
                f"Could not load handler for function '{function_id}': {exc}"
            ) from exc

        cancel = getattr(handler_module, "cancel", None)
        if not callable(cancel):
            raise RuntimeError(
                f"Function '{function_id}' does not support cancellation yet."
            )

        resolved_inputs = hardware_map_service.apply_function_defaults(discovered_function.manifest, inputs)
        hardware_map = hardware_map_service.load_map()
        context = {
            "mode": "cancel",
            "function_id": function_id,
            "manifest": discovered_function.manifest.model_dump(),
            "hardware_map": hardware_map.model_dump(mode="json"),
        }

        try:
            result = cancel(context, resolved_inputs)
        except Exception as exc:  # pragma: no cover - defensive boundary around plugin code
            raise RuntimeError(
                f"Function '{function_id}' cancellation failed: {exc}"
            ) from exc

        if result is not None and not isinstance(result, dict):
            raise RuntimeError(
                f"Function '{function_id}' cancel returned {type(result).__name__}; expected dict or None."
            )

        result_payload = result or {}
        return FunctionCancelResponse(
            function_id=function_id,
            ok=bool(result_payload.get("ok", True)),
            message=str(result_payload.get("message", "Cancellation requested.")),
            result=result_payload,
        )


function_discovery_service = FunctionDiscoveryService(
    functions_dir=Path(__file__).resolve().parent.parent / "functions"
)
