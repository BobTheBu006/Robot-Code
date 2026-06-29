export type HardwareDeviceKind = "stepper_motor" | "servo" | "sensor";
export type HardwareSensorKind = "position_limit_switch" | "aht20_temperature_humidity";

export interface HardwareBoardMapping {
  id: string;
  label: string;
  usb_port: string;
  enabled?: boolean;
  notes?: string | null;
}

export interface HardwarePinMapping {
  id: string;
  signal: string;
  gpio: string;
  function_input_key?: string | null;
  notes?: string | null;
}

export interface HardwareDeviceMapping {
  id: string;
  board_id: string;
  name: string;
  kind: HardwareDeviceKind;
  enabled?: boolean;
  sensor_kind?: HardwareSensorKind | null;
  rotation_min_deg?: number | null;
  rotation_max_deg?: number | null;
  calibration_ml_per_200_steps?: number | null;
  pins: HardwarePinMapping[];
  notes?: string | null;
}

export interface HardwareGroupMapping {
  id: string;
  name: string;
  member_ids: string[];
  enabled?: boolean;
  notes?: string | null;
}

export interface FunctionHardwareAssignment {
  function_id: string;
  device_id: string;
  hardware_device_id: string;
}

export interface HardwareNodePosition {
  node_id: string;
  x: number;
  y: number;
}

export interface HardwareMap {
  version: number;
  boards: HardwareBoardMapping[];
  devices: HardwareDeviceMapping[];
  groups?: HardwareGroupMapping[];
  function_assignments?: FunctionHardwareAssignment[];
  node_positions?: HardwareNodePosition[];
  updated_at?: string | null;
}

export interface HardwareMapSaveResponse {
  path: string;
  saved_at: string;
  hardware_map: HardwareMap;
}
