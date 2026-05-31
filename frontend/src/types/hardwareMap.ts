export type HardwareDeviceKind = "stepper_motor" | "servo" | "sensor";
export type HardwareSensorKind = "position_limit_switch" | "aht20_temperature_humidity";

export interface HardwareBoardMapping {
  id: string;
  label: string;
  usb_port: string;
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
  sensor_kind?: HardwareSensorKind | null;
  rotation_min_deg?: number | null;
  rotation_max_deg?: number | null;
  pins: HardwarePinMapping[];
  notes?: string | null;
}

export interface HardwareMap {
  version: number;
  boards: HardwareBoardMapping[];
  devices: HardwareDeviceMapping[];
  updated_at?: string | null;
}

export interface HardwareMapSaveResponse {
  path: string;
  saved_at: string;
  hardware_map: HardwareMap;
}
