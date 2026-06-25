import type { FunctionManifest, WorkflowFirmwareRequirement, WorkflowInputDefinition } from "./workflow";

export interface Esp32BuilderFile {
  relative_path: string;
  absolute_path: string;
  language: string;
  editable: boolean;
  size_bytes: number;
  content: string;
}

export interface Esp32FunctionBlueprint {
  schema_version: number;
  manifest: FunctionManifest;
  advanced_builder_inputs: WorkflowInputDefinition[];
  firmware_entry_file: string;
  protocol: string;
  notes?: string | null;
  source_path?: string | null;
  base_function_id?: string | null;
}

export interface Esp32BoardSummary {
  board_id: string;
  display_name: string;
  port?: string | null;
  connected: boolean;
  description?: string | null;
  hardware_id?: string | null;
  serial_number?: string | null;
  workspace_path: string;
  generated_function_ids: string[];
  errors: string[];
}

export interface Esp32BoardDetail extends Esp32BoardSummary {
  files: Esp32BuilderFile[];
  blueprints: Esp32FunctionBlueprint[];
  instructions_path?: string | null;
  firmware_entry_file?: string | null;
  fqbn?: string | null;
  toolchain?: Esp32ToolchainStatus | null;
}

export interface Esp32BoardListResponse {
  boards: Esp32BoardSummary[];
}

export interface Esp32ToolchainStatus {
  arduino_cli_available: boolean;
  arduino_cli_path?: string | null;
  config_file?: string | null;
  package_index_url: string;
  fqbn_default: string;
  auto_reset_note: string;
}

export interface Esp32FirmwareActionResponse {
  board_id: string;
  action: string;
  ok: boolean;
  fqbn: string;
  port?: string | null;
  sketch_entry_file: string;
  command: string[];
  log: string;
  auto_reset_attempted: boolean;
  auto_reset_note: string;
}

export interface Esp32WorkflowFirmwarePlanRoutine {
  routine_id: string;
  controller_role: string;
  source?: string | null;
  protocol?: string | null;
  entry_point?: string | null;
  required_device_ids: string[];
  description?: string | null;
  source_path?: string | null;
  source_exists: boolean;
  block_ids: string[];
}

export interface Esp32WorkflowFirmwareBoardPlan {
  board_id: string;
  workspace_path?: string | null;
  firmware_entry_file?: string | null;
  routines: Esp32WorkflowFirmwarePlanRoutine[];
  missing_sources: string[];
  warnings: string[];
  errors: string[];
}

export interface Esp32WorkflowFirmwarePlanRequestItem {
  block_id: string;
  block_name?: string | null;
  board_id: string;
  requirements: WorkflowFirmwareRequirement[];
}

export interface Esp32WorkflowFirmwarePlanResponse {
  ok: boolean;
  boards: Esp32WorkflowFirmwareBoardPlan[];
  warnings: string[];
  errors: string[];
}

export interface Esp32FileSaveResponse {
  board_id: string;
  relative_path: string;
  saved_at: string;
}

export interface Esp32CustomBlockSaveResponse {
  board_id: string;
  function_id: string;
  display_name: string;
  blueprint_path: string;
  saved_at: string;
}

export interface Esp32CustomBlockDeleteResponse {
  board_id: string;
  function_id: string;
  display_name: string;
  blueprint_path: string;
  deleted_at: string;
}
