export type MachineState = "idle" | "running" | "paused" | "alarm";
export type AlarmSeverity = "info" | "warning" | "critical";

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

export interface CameraStatus {
  available: boolean;
  configured_device: string;
  active_device: string | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  error: string | null;
  stream_url: string | null;
}

export interface GantryState {
  x: number;
  y: number;
  z: number;
}

export interface GantryStateUpdate {
  x?: number;
  y?: number;
  z?: number;
}

export interface SensorState {
  name: string;
  value: number | string;
  unit?: string;
}

export interface AlarmState {
  code: string;
  message: string;
  severity: AlarmSeverity;
  active: boolean;
}

export interface RobotState {
  machine_state: MachineState;
  current_workflow: string | null;
  current_step: number | null;
  gantry: GantryState;
  sensor_values: SensorState[];
  alarms: AlarmState[];
}

export interface RobotStateUpdate {
  machine_state?: MachineState;
  current_workflow?: string | null;
  current_step?: number | null;
  gantry?: GantryStateUpdate;
  sensor_values?: SensorState[];
  alarms?: AlarmState[];
}
