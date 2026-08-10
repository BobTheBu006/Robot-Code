import type { CameraStatus, HealthResponse, RobotState, RobotStateUpdate } from "../types/robot";
import type { HardwareMap, HardwareMapSaveResponse } from "../types/hardwareMap";
import type {
  Esp32BoardDetail,
  Esp32BoardListResponse,
  Esp32CustomBlockDeleteResponse,
  Esp32CustomBlockSaveResponse,
  Esp32FirmwareActionResponse,
  Esp32FileSaveResponse,
  Esp32WorkflowFirmwarePlanRequestItem,
  Esp32WorkflowFirmwarePlanResponse,
} from "../types/esp32Builder";
import type {
  FunctionCancelResponse,
  FunctionDiscoveryResponse,
  FunctionTestResponse,
  SavedWorkflowFile,
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
  WorkflowDeleteResponse,
  WorkflowListResponse,
  WorkflowRenameResponse,
  WorkflowParameterValue,
  WorkflowSaveResponse,
} from "../types/workflow";

const WORKFLOW_SCHEMA_VERSION = 1;
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export interface EmergencyStopResponse {
  ok: boolean;
  message: string;
  results: Array<{
    ok: boolean;
    tool: string;
    tool_port: string | null;
    message: string;
  }>;
}

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
    let message = `Request failed: ${response.status}`;
    try {
      const responseText = await response.text();
      if (responseText) {
        try {
          const parsed = JSON.parse(responseText) as { detail?: string };
          message = parsed.detail ?? responseText;
        } catch {
          message = responseText;
        }
      }
    } catch {
      // fall back to status-only message
    }

    const error = new Error(message) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    const responseText = await response.text();
    throw new Error(
      `Expected JSON from ${path}, but received ${contentType || "unknown content type"}. `
      + `Check that the FastAPI backend is running and that VITE_API_BASE_URL is not pointing at the frontend. `
      + responseText.slice(0, 80),
    );
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

export function fetchEsp32Boards(): Promise<Esp32BoardListResponse> {
  return request<Esp32BoardListResponse>("/api/esp32-builder/boards");
}

export function fetchHardwareMap(): Promise<HardwareMap> {
  return request<HardwareMap>("/api/hardware-map");
}

export function saveHardwareMap(hardwareMap: HardwareMap): Promise<HardwareMapSaveResponse> {
  return request<HardwareMapSaveResponse>("/api/hardware-map", {
    method: "PUT",
    body: JSON.stringify(hardwareMap),
  });
}

export function fetchEsp32Board(boardId: string): Promise<Esp32BoardDetail> {
  return request<Esp32BoardDetail>(`/api/esp32-builder/boards/${encodeURIComponent(boardId)}`);
}

export function saveEsp32BoardFile(
  boardId: string,
  relativePath: string,
  content: string,
): Promise<Esp32FileSaveResponse> {
  return request<Esp32FileSaveResponse>(`/api/esp32-builder/boards/${encodeURIComponent(boardId)}/files`, {
    method: "PUT",
    body: JSON.stringify({
      relative_path: relativePath,
      content,
    }),
  });
}

export function buildEsp32BoardFirmware(boardId: string): Promise<Esp32FirmwareActionResponse> {
  return request<Esp32FirmwareActionResponse>(`/api/esp32-builder/boards/${encodeURIComponent(boardId)}/build`, {
    method: "POST",
  });
}

export function flashEsp32BoardFirmware(
  boardId: string,
  signal?: AbortSignal,
  // A run passes true: the board is asked who it is, and one already running
  // the expected firmware is left alone instead of being reflashed. The
  // builder's Flash button leaves this false, because clicking Flash means
  // flash it.
  skipIfCurrent = false,
): Promise<Esp32FirmwareActionResponse> {
  const query = skipIfCurrent ? "?skip_if_current=true" : "";
  return request<Esp32FirmwareActionResponse>(
    `/api/esp32-builder/boards/${encodeURIComponent(boardId)}/flash${query}`,
    {
      method: "POST",
      signal,
    },
  );
}

export function planWorkflowFirmware(
  items: Esp32WorkflowFirmwarePlanRequestItem[],
): Promise<Esp32WorkflowFirmwarePlanResponse> {
  return request<Esp32WorkflowFirmwarePlanResponse>("/api/esp32-builder/workflow-firmware/plan", {
    method: "POST",
    body: JSON.stringify({ items }),
  });
}

export function saveEsp32CustomBlock(
  boardId: string,
  sourceFunctionId: string,
  displayName: string,
  description: string,
  defaults: Record<string, WorkflowParameterValue>,
): Promise<Esp32CustomBlockSaveResponse> {
  return request<Esp32CustomBlockSaveResponse>(`/api/esp32-builder/boards/${encodeURIComponent(boardId)}/blocks`, {
    method: "POST",
    body: JSON.stringify({
      source_function_id: sourceFunctionId,
      display_name: displayName,
      description,
      defaults,
    }),
  });
}

export function deleteEsp32CustomBlock(
  boardId: string,
  functionId: string,
): Promise<Esp32CustomBlockDeleteResponse> {
  return request<Esp32CustomBlockDeleteResponse>(
    `/api/esp32-builder/boards/${encodeURIComponent(boardId)}/blocks/${encodeURIComponent(functionId)}`,
    {
      method: "DELETE",
    },
  );
}

export function fetchSavedWorkflow(): Promise<SavedWorkflowFile> {
  return request<SavedWorkflowFile>("/api/workflows/default");
}

export function fetchWorkflowFile(filename: string): Promise<SavedWorkflowFile> {
  return request<SavedWorkflowFile>(`/api/workflows/${encodeURIComponent(filename)}`);
}

export function fetchWorkflowList(): Promise<WorkflowListResponse> {
  return request<WorkflowListResponse>("/api/workflows");
}

export function renameWorkflowFile(filename: string, nextFilename: string): Promise<WorkflowRenameResponse> {
  return request<WorkflowRenameResponse>(`/api/workflows/${encodeURIComponent(filename)}/rename`, {
    method: "POST",
    body: JSON.stringify({ filename: nextFilename }),
  });
}

export function deleteWorkflowFile(filename: string): Promise<WorkflowDeleteResponse> {
  return request<WorkflowDeleteResponse>(`/api/workflows/${encodeURIComponent(filename)}`, {
    method: "DELETE",
  });
}

export function saveWorkflowToFile(
  nodes: WorkflowCanvasNode[],
  edges: WorkflowCanvasEdge[],
  path?: string,
  filename?: string,
): Promise<WorkflowSaveResponse> {
  return request<WorkflowSaveResponse>("/api/workflows/default", {
    method: "PUT",
    body: JSON.stringify({
      path: path ?? null,
      filename: filename ?? null,
      workflow: {
        schema_version: WORKFLOW_SCHEMA_VERSION,
        version: WORKFLOW_SCHEMA_VERSION,
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
  signal?: AbortSignal,
): Promise<FunctionTestResponse> {
  return request<FunctionTestResponse>(`/api/functions/${functionId}/test`, {
    method: "POST",
    signal,
    body: JSON.stringify({ inputs, input_data: inputData ?? null }),
  });
}

export function cancelFunction(
  functionId: string,
  inputs: Record<string, WorkflowParameterValue>,
): Promise<FunctionCancelResponse> {
  return request<FunctionCancelResponse>(`/api/functions/${functionId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ inputs }),
  });
}

export function emergencyStop(): Promise<EmergencyStopResponse> {
  return request<EmergencyStopResponse>("/api/emergency-stop", {
    method: "POST",
  });
}

// Clears a latched emergency stop so new work is allowed to move again.
export function rearmEmergencyStop(): Promise<{ ok: boolean; message: string }> {
  return request<{ ok: boolean; message: string }>("/api/emergency-stop/rearm", {
    method: "POST",
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

export interface AccessDoorState {
  is_open: boolean | null;
  pin: number;
  detected: boolean;
  override_active: boolean;
  blocks_run: boolean;
  reason: string;
}

export function fetchAccessDoor(): Promise<AccessDoorState> {
  return request<AccessDoorState>("/api/safety/access-door");
}

export function setAccessDoorOverride(enabled: boolean): Promise<AccessDoorState> {
  return request<AccessDoorState>("/api/safety/access-door/override", {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
}

// A run session is what makes the door interlock real: the backend refuses to
// start one while the door blocks a run, and watches the door for the run's
// duration so opening it mid-run stops the machine.
export function startRunSession(): Promise<{ ok: boolean; watching: boolean }> {
  return request<{ ok: boolean; watching: boolean }>("/api/safety/run-session/start", {
    method: "POST",
  });
}

export function endRunSession(): Promise<{ ok: boolean; watching: boolean }> {
  return request<{ ok: boolean; watching: boolean }>("/api/safety/run-session/end", {
    method: "POST",
  });
}

// ---------------------------------------------------------------------------
// Workflow engine
//
// The engine decides what runs next; the browser executes it. Control flow -
// which branch an If takes, how many times a loop repeats, which blocks wait
// for which - is worked out on the backend, where it is covered by tests,
// rather than by walking the edge array here.

export interface PlanProblem {
  level: "error" | "warning";
  message: string;
  node_id: string | null;
}

export interface WorkflowPlanResponse {
  ok: boolean;
  node_count: number;
  edge_count: number;
  start_node_ids: string[];
  join_node_ids: string[];
  loop_back_edge_ids: string[];
  unreachable_node_ids: string[];
  problems: PlanProblem[];
}

export interface EngineDueNode {
  node_id: string;
  block_id: string;
  display_name: string;
  input: Record<string, unknown>;
  iteration: number;
}

export interface EngineRunReport {
  ok: boolean;
  executed: string[];
  results: Record<string, unknown>;
  events: { kind: string; node_id: string | null; detail: string }[];
  error: string | null;
  stopped_at: string | null;
}

export interface EngineRunEvent {
  kind: string;
  node_id: string | null;
  detail: string;
}

export interface EngineRunStep {
  ok: boolean;
  run_id?: string | null;
  due: EngineDueNode[];
  // What the engine settled by itself since the last step: loop decisions and
  // deactivated blocks, which are never handed over for execution.
  events?: EngineRunEvent[];
  finished: boolean;
  report?: EngineRunReport;
  problems?: PlanProblem[];
  error?: string | null;
}

export interface WorkflowGraphPayload {
  nodes: unknown[];
  edges: unknown[];
}

export function planWorkflowGraph(graph: WorkflowGraphPayload): Promise<WorkflowPlanResponse> {
  return request<WorkflowPlanResponse>("/api/engine/plan", {
    method: "POST",
    body: JSON.stringify(graph),
  });
}

export function startEngineRun(graph: WorkflowGraphPayload): Promise<EngineRunStep> {
  return request<EngineRunStep>("/api/engine/runs", {
    method: "POST",
    body: JSON.stringify(graph),
  });
}

export function submitEngineNodeResult(
  runId: string,
  payload: { node_id: string; ok: boolean; result: Record<string, unknown> | null; error: string | null },
): Promise<EngineRunStep> {
  return request<EngineRunStep>(`/api/engine/runs/${encodeURIComponent(runId)}/results`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function endEngineRun(runId: string, reason: string): Promise<EngineRunStep> {
  return request<EngineRunStep>(`/api/engine/runs/${encodeURIComponent(runId)}/end`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}
