import type {
  HardwareDeviceKind,
  HardwarePinMapping,
  HardwareSensorKind,
} from "../types/hardwareMap";

// Device kinds and their pin templates, shared by the fixed wiring diagram and
// the dynamic connector page so both describe hardware the same way.

export const RASPBERRY_NODE_ID = "raspberry-pi";

export const DEVICE_KIND_OPTIONS: Array<{ label: string; value: HardwareDeviceKind }> = [
  { label: "Stepper motor", value: "stepper_motor" },
  { label: "Servo", value: "servo" },
  { label: "Sensor", value: "sensor" },
];
export const SENSOR_KIND_OPTIONS: Array<{ label: string; value: HardwareSensorKind }> = [
  { label: "Position / limit switch", value: "position_limit_switch" },
  { label: "AHT20 temperature + humidity", value: "aht20_temperature_humidity" },
];
export const STEPPER_SIGNALS = ["direction", "step", "enable", "micro_step_1", "micro_step_2", "micro_step_3"];
export const SIGNAL_LABELS: Record<string, string> = {
  "-": "-",
  direction: "Direction",
  step: "Step",
  enable: "Enable",
  micro_step_1: "Micro step 1",
  micro_step_2: "Micro step 2",
  micro_step_3: "Micro step 3",
  signal: "Signal",
  scl: "SCL",
  sda: "SDA",
};

export function isRaspberryBoardId(boardId: string | null | undefined): boolean {
  return boardId === RASPBERRY_NODE_ID;
}

export function makeId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

export function normalizeId(value: string, fallback: string): string {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

  return normalized || fallback;
}

export function normalizeDeviceKind(kind: string | undefined): HardwareDeviceKind {
  if (kind === "sensor" || kind === "servo" || kind === "stepper_motor") {
    return kind;
  }

  if (kind === "motor") {
    return "stepper_motor";
  }

  return "servo";
}

export function normalizeSensorKind(sensorKind: string | null | undefined): HardwareSensorKind {
  return sensorKind === "aht20_temperature_humidity" ? "aht20_temperature_humidity" : "position_limit_switch";
}

export function normalizePinSignal(signal: string): string {
  const normalized = signal.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const aliases: Record<string, string> = {
    dir: "direction",
    direction: "direction",
    step: "step",
    enable: "enable",
    en: "enable",
    ms1: "micro_step_1",
    microstep1: "micro_step_1",
    micro_step_1: "micro_step_1",
    ms2: "micro_step_2",
    microstep2: "micro_step_2",
    micro_step_2: "micro_step_2",
    ms3: "micro_step_3",
    microstep3: "micro_step_3",
    micro_step_3: "micro_step_3",
    scl: "scl",
    sda: "sda",
    signal: "signal",
  };

  return aliases[normalized] ?? normalized;
}

export function pinTemplateForDevice(
  kind: HardwareDeviceKind,
  sensorKind: HardwareSensorKind = "position_limit_switch",
  boardId: string | null = null,
): Array<Pick<HardwarePinMapping, "signal" | "gpio" | "function_input_key">> {
  if (kind === "stepper_motor") {
    return STEPPER_SIGNALS.map((signal) => ({
      signal,
      gpio: "-",
      function_input_key: null,
    }));
  }

  if (kind === "servo") {
    return [{ signal: "signal", gpio: "-", function_input_key: null }];
  }

  if (sensorKind === "aht20_temperature_humidity") {
    if (isRaspberryBoardId(boardId)) {
      return [
        { signal: "scl", gpio: "3", function_input_key: null },
        { signal: "sda", gpio: "2", function_input_key: null },
      ];
    }

    return [
      { signal: "scl", gpio: "-", function_input_key: null },
      { signal: "sda", gpio: "-", function_input_key: null },
    ];
  }

  return [{ signal: "signal", gpio: "-", function_input_key: null }];
}

export function pinsForDevice(
  kind: HardwareDeviceKind,
  sensorKind: HardwareSensorKind = "position_limit_switch",
  existingPins: HardwarePinMapping[] = [],
  boardId: string | null = null,
): HardwarePinMapping[] {
  const existingBySignal = new Map(existingPins.map((pin) => [normalizePinSignal(pin.signal), pin]));

  return pinTemplateForDevice(kind, sensorKind, boardId).map((template, index) => {
    const existing = existingBySignal.get(template.signal);
    return {
      id: existing?.id ?? makeId(`pin-${index + 1}`),
      signal: template.signal,
      gpio: existing?.gpio?.trim() || template.gpio,
      function_input_key: existing?.function_input_key?.trim() || template.function_input_key,
      notes: existing?.notes?.trim() || null,
    };
  });
}
