import type { CameraStatus, HealthResponse, RobotState, RobotStateUpdate } from "../types/robot";
import type {
  FunctionDiscoveryResponse,
  FunctionTestResponse,
  SavedWorkflowFile,
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
  WorkflowParameterValue,
  WorkflowSaveResponse,
} from "../types/workflow";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const hasBody = options?.body !== undefined;

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...(hasBody ? { "Content-Type": "application/json" } : {}),
      ...(options?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const error = new Error(`Request failed: ${response.status}`) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }

  return response.json() as Promise<T>;
}

export function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export function fetchCameraStatus(): Promise<CameraStatus> {
  return request<CameraStatus>("/api/camera/status");
}

export function setCameraPower(enabled: boolean): Promise<CameraStatus> {
  return request<CameraStatus>("/api/camera/power", {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
}

export function fetchFunctions(): Promise<FunctionDiscoveryResponse> {
  return request<FunctionDiscoveryResponse>("/api/functions");
}

export function fetchSavedWorkflow(): Promise<SavedWorkflowFile> {
  return request<SavedWorkflowFile>("/api/workflows/default");
}

export function saveWorkflowToFile(
  nodes: WorkflowCanvasNode[],
  edges: WorkflowCanvasEdge[],
): Promise<WorkflowSaveResponse> {
  return request<WorkflowSaveResponse>("/api/workflows/default", {
    method: "PUT",
    body: JSON.stringify({
      workflow: {
        version: 1,
        nodes,
        edges,
      },
    }),
  });
}

export function testFunction(
  functionId: string,
  inputs: Record<string, WorkflowParameterValue>,
  inputData?: Record<string, unknown> | null,
): Promise<FunctionTestResponse> {
  return request<FunctionTestResponse>(`/api/functions/${functionId}/test`, {
    method: "POST",
    body: JSON.stringify({ inputs, input_data: inputData ?? null }),
  });
}

export function fetchRobotState(): Promise<RobotState> {
  return request<RobotState>("/api/robot/state");
}

export function updateMockRobotState(update: RobotStateUpdate): Promise<RobotState> {
  return request<RobotState>("/api/robot/state/mock-update", {
    method: "POST",
    body: JSON.stringify(update),
  });
}

export function getCameraStreamUrl(): string {
  return `${API_BASE_URL}/api/camera/stream`;
}
