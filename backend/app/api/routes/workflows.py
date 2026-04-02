from fastapi import APIRouter, HTTPException

from app.models.workflows import (
    WorkflowFileResponse,
    WorkflowListResponse,
    WorkflowSaveRequest,
    WorkflowSaveResponse,
)
from app.services.workflow_storage import (
    WorkflowNotFoundError,
    WorkflowStorageError,
    workflow_storage_service,
)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get("", response_model=WorkflowListResponse)
def list_workflows() -> WorkflowListResponse:
    return workflow_storage_service.list_workflows()


@router.get("/default", response_model=WorkflowFileResponse)
def load_default_workflow() -> WorkflowFileResponse:
    try:
        return workflow_storage_service.load_default_workflow()
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/default", response_model=WorkflowSaveResponse)
def save_default_workflow(request: WorkflowSaveRequest) -> WorkflowSaveResponse:
    try:
        if request.filename or request.path:
            return workflow_storage_service.save_workflow(
                filename=request.filename or workflow_storage_service._default_filename(),
                workflow=request.workflow,
                directory=request.path,
            )

        return workflow_storage_service.save_default_workflow(request.workflow)
    except WorkflowStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
