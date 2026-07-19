from fastapi import APIRouter, HTTPException

from app.models.workflows import (
    WorkflowDeleteResponse,
    WorkflowFileResponse,
    WorkflowListResponse,
    WorkflowRenameRequest,
    WorkflowRenameResponse,
    WorkflowSaveRequest,
    WorkflowSaveResponse,
)
from app.services.workspace_defaults import workspace_defaults_service
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


@router.get("/{filename}", response_model=WorkflowFileResponse)
def load_workflow_file(filename: str) -> WorkflowFileResponse:
    try:
        return workflow_storage_service.load_workflow(filename)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/default", response_model=WorkflowSaveResponse)
def save_default_workflow(request: WorkflowSaveRequest) -> WorkflowSaveResponse:
    try:
        if request.filename or request.path:
            response = workflow_storage_service.save_workflow(
                filename=request.filename or workflow_storage_service._default_filename(),
                workflow=request.workflow,
                directory=request.path,
            )
        else:
            response = workflow_storage_service.save_default_workflow(request.workflow)
    except WorkflowStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Values edited on any tool block become the shared defaults as soon as the
    # workflow is saved, so a newly placed block starts from them.
    workspace_defaults_service.adopt_toolhead_defaults_from_workflow(request.workflow)
    return response


@router.post("/{filename}/rename", response_model=WorkflowRenameResponse)
def rename_workflow_file(filename: str, request: WorkflowRenameRequest) -> WorkflowRenameResponse:
    try:
        return workflow_storage_service.rename_workflow(filename, request.filename)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{filename}", response_model=WorkflowDeleteResponse)
def delete_workflow_file(filename: str) -> WorkflowDeleteResponse:
    try:
        return workflow_storage_service.delete_workflow(filename)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
