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
}

export interface Esp32BoardListResponse {
  boards: Esp32BoardSummary[];
}

export interface Esp32FileSaveResponse {
  board_id: string;
  relative_path: string;
  saved_at: string;
}

