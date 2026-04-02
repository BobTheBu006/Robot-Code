import type { WorkflowInputDefinition } from "./workflow";

export interface Esp32BuilderFile {
  relative_path: string;
  absolute_path: string;
  language: string;
  editable: boolean;
  size_bytes: number;
  content: string;
}

export interface Esp32FunctionBlueprint {
  manifest: {
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
  };
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
