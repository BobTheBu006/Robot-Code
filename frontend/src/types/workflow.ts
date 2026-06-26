export type WorkflowInputType = "string" | "number" | "boolean" | "select" | "file/path";
export type WorkflowParameterValue = string | number | boolean;
export type WorkflowBlockKind = "basic" | "advanced" | "compound" | "built-in" | "robot-action" | "broken";
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
  hidden?: boolean;
  resolvedFrom?: "hardware_map";
  options: WorkflowInputOption[];
}

export interface WorkflowOutputDefinition {
  key: string;
  label: string;
  type?: string;
  description?: string | null;
}

export type WorkflowHardwareDeviceKind = "stepper_motor" | "servo" | "sensor";
export type WorkflowHardwareSensorKind = "position_limit_switch" | "aht20_temperature_humidity";

export interface WorkflowHardwarePinReference {
  id: string;
  signal: string;
  gpio?: string | number | null;
  function_input_key?: string | null;
  notes?: string | null;
}

export interface WorkflowHardwareDeviceReference {
  id: string;
  name: string;
  kind: WorkflowHardwareDeviceKind;
  board_id?: string | null;
  sensor_kind?: WorkflowHardwareSensorKind | null;
  rotation_min_deg?: number | null;
  rotation_max_deg?: number | null;
  calibration_ml_per_200_steps?: number | null;
  pins: WorkflowHardwarePinReference[];
  basic_block_id?: string | null;
  notes?: string | null;
}

export type WorkflowFirmwareControllerRole = "builder_board" | "device_board" | "raspberry_pi" | "any_controller";

export interface WorkflowFirmwareRequirement {
  routine_id: string;
  controller_role: WorkflowFirmwareControllerRole;
  source?: string | null;
  protocol?: string | null;
  entry_point?: string | null;
  required_device_ids: string[];
  description?: string | null;
}

export interface WorkflowCompoundOutputDefinition extends WorkflowOutputDefinition {
  sourceNodeId: string;
  sourceHandle?: string | null;
}

export interface FunctionManifest {
  schema_version: number;
  id: string;
  display_name: string;
  category: string;
  description: string;
  version: string;
  inputs: WorkflowInputDefinition[];
  advanced_inputs?: WorkflowInputDefinition[];
  hardware_devices?: WorkflowHardwareDeviceReference[];
  firmware_requirements?: WorkflowFirmwareRequirement[];
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
    schema_version?: number;
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

export interface WorkflowCompoundDefinition {
  entryNodeId: string;
  nodes: WorkflowCanvasNode[];
  edges: WorkflowCanvasEdge[];
  outputs: WorkflowCompoundOutputDefinition[];
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
  hardwareDeviceId?: string | null;
  hardwareDeviceKind?: "stepper_motor" | "servo" | "sensor" | null;
  hardwareBoardId?: string | null;
  hardwareCalibrationMlPer200Steps?: number | null;
  hardwareDevices?: WorkflowHardwareDeviceReference[];
  firmwareRequirements?: WorkflowFirmwareRequirement[];
  referencedBasicBlockIds?: string[];
  compound?: WorkflowCompoundDefinition | null;
  builderBoardId?: string | null;
  builderSourcePath?: string | null;
  builderWorkspacePath?: string | null;
  builderFirmwareEntryFile?: string | null;
  builderBaseFunctionId?: string | null;
  disabledReason?: string | null;
  missingReference?: {
    originalId: string;
    originalKind: WorkflowBlockKind;
    reason: string;
    suggestedFix: string;
  } | null;
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
  onCancel?: (() => void) | undefined;
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

export interface FunctionCancelResponse {
  function_id: string;
  ok: boolean;
  message: string;
  result?: Record<string, unknown> | null;
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
