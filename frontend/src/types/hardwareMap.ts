export type HardwareDeviceKind = "stepper_motor" | "servo" | "sensor";
export type HardwareSensorKind = "position_limit_switch" | "aht20_temperature_humidity";

export interface HardwareBoardMapping {
  id: string;
  label: string;
  usb_port: string;
  enabled?: boolean;
  notes?: string | null;
  dynamic?: boolean;
  expected_serial_number?: string | null;
  expected_hardware_id?: string | null;
  expected_device_label?: string | null;
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

export type ConnectorPinMode = "unused" | "i2c" | "uart" | "gpio";
export type ConnectorVerification = "none" | "loopback" | "usb_serial" | "fingerprint";

export interface HardwareConnectorPin {
  name: string;
  gpio: string;
  peripheral?: "i2c" | "uart" | null;
  alt_function?: string | null;
}

// A connector whose far side changes with the docked tool. Only groups attach
// to it; each group is one tool.
export interface HardwareConnectorMapping {
  id: string;
  label: string;
  pins: HardwareConnectorPin[];
  usb_port?: string | null;
  // Which of the Pi's physical USB ports (HardwareMap.usb_ports) the
  // connector's USB is wired to.
  usb_port_number?: number | null;
  enabled?: boolean;
  notes?: string | null;
}

export interface HardwareUsbPort {
  number: number;
  label: string;
  device_path?: string | null;
}

export interface HardwareGroupMapping {
  id: string;
  name: string;
  member_ids: string[];
  enabled?: boolean;
  notes?: string | null;
  connector_id?: string | null;
  pin_modes?: Record<string, ConnectorPinMode>;
  usb_board_id?: string | null;
  verification?: ConnectorVerification;
  toolhead_index?: number | null;
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
  connectors?: HardwareConnectorMapping[];
  usb_ports?: HardwareUsbPort[];
  function_assignments?: FunctionHardwareAssignment[];
  node_positions?: HardwareNodePosition[];
  updated_at?: string | null;
}

export interface HardwareMapSaveResponse {
  path: string;
  saved_at: string;
  hardware_map: HardwareMap;
}
