from fastapi import APIRouter, HTTPException

from app.models.function_manifest import (
    FunctionCancelRequest,
    FunctionCancelResponse,
    FunctionDiscoveryResponse,
    FunctionTestRequest,
    FunctionTestResponse,
)
from app.services.function_discovery import function_discovery_service

router = APIRouter(prefix="/api/functions", tags=["functions"])


@router.get("", response_model=FunctionDiscoveryResponse)
def get_functions() -> FunctionDiscoveryResponse:
    return function_discovery_service.discover()


@router.post("/{function_id}/test", response_model=FunctionTestResponse)
def test_function(function_id: str, request: FunctionTestRequest) -> FunctionTestResponse:
    try:
        return function_discovery_service.test_function(function_id, request.inputs, request.input_data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{function_id}/cancel", response_model=FunctionCancelResponse)
def cancel_function(function_id: str, request: FunctionCancelRequest) -> FunctionCancelResponse:
    try:
        return function_discovery_service.cancel_function(function_id, request.inputs)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
