export type WorkflowInputType = "string" | "number" | "boolean" | "select" | "file/path";
export type WorkflowParameterValue = string | number | boolean;
export type WorkflowBlockKind = "built-in" | "robot-action";
export type WorkflowFailureMode = "stop_flow" | "separate_path";
export type WorkflowExecutionStatus = "idle" | "running" | "success" | "error";

export interface WorkflowInputOption {
  label: string;
  value: string;
}

export interface WorkflowInputDefinition {
  key: string;
  label: string;
  type: WorkflowInputType;
  description?: string | null;
  required: boolean;
  default?: WorkflowParameterValue | null;
  placeholder?: string | null;
  advanced?: boolean;
  options: WorkflowInputOption[];
}

export interface WorkflowOutputDefinition {
  key: string;
  label: string;
  type?: string;
  description?: string | null;
}

export interface FunctionManifest {
  id: string;
  display_name: string;
  category: string;
  description: string;
  version: string;
  inputs: WorkflowInputDefinition[];
  advanced_inputs?: WorkflowInputDefinition[];
  outputs: Array<{
    key: string;
    label: string;
    type: string;
    description?: string | null;
  }>;
  builder_board_id?: string | null;
  builder_source_path?: string | null;
  builder_workspace_path?: string | null;
  builder_firmware_entry_file?: string | null;
  builder_base_function_id?: string | null;
}

export interface DiscoveredFunctionDefinition {
  manifest: FunctionManifest;
  folder_name: string;
  manifest_path: string;
  handler_path: string;
  requirements_path: string;
}

export interface FunctionDiscoveryError {
  folder_name: string;
  message: string;
}

export interface FunctionDiscoveryResponse {
  functions: DiscoveredFunctionDefinition[];
  errors: FunctionDiscoveryError[];
}

export interface SavedWorkflowFile {
  filename: string;
  path: string;
  workflow: {
    version?: number;
    nodes?: WorkflowCanvasNode[];
    edges?: WorkflowCanvasEdge[];
  };
}

export interface WorkflowSaveResponse {
  filename: string;
  path: string;
  saved_at: string;
}

export interface WorkflowBlockDefinition {
  id: string;
  displayName: string;
  category: string;
  description: string;
  version: string;
  kind: WorkflowBlockKind;
  acceptsInput: boolean;
  accent: string;
  inputs: WorkflowInputDefinition[];
  advancedInputs?: WorkflowInputDefinition[];
  outputs: WorkflowOutputDefinition[];
  builderBoardId?: string | null;
  builderSourcePath?: string | null;
  builderWorkspacePath?: string | null;
  builderFirmwareEntryFile?: string | null;
  builderBaseFunctionId?: string | null;
}

export interface WorkflowNodeSettings {
  failureMode: WorkflowFailureMode;
  retryCount: number;
}

export interface WorkflowNodeData extends Record<string, unknown> {
  block: WorkflowBlockDefinition;
  parameters: Record<string, WorkflowParameterValue>;
  settings: WorkflowNodeSettings;
  isActive: boolean;
  runCount?: number;
  benchmarkDurationMs?: number | null;
  lastDurationMs?: number | null;
  executionStatus?: WorkflowExecutionStatus;
  executionEtaMs?: number | null;
  onDelete?: (() => void) | undefined;
  onRun?: (() => void) | undefined;
  onToggleActive?: (() => void) | undefined;
}

export interface FunctionTestResponse {
  function_id: string;
  ok: boolean;
  inputs: Record<string, WorkflowParameterValue | null>;
  input_data?: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface WorkflowCanvasNode {
  id: string;
  type?: string;
  position: {
    x: number;
    y: number;
  };
  data: WorkflowNodeData;
}

export interface WorkflowCanvasEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  type?: string;
  animated?: boolean;
}
