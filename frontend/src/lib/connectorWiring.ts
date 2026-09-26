import type {
  ConnectorPinMode,
  HardwareConnectorMapping,
  HardwareGroupMapping,
  HardwareMap,
} from "../types/hardwareMap";

// Mirror of connector_pin_modes in backend/app/models/hardware_map.py, so the
// dynamic page can show pin usage and conflicts before saving. The backend
// check is the one that counts; keep the two in step.

const I2C_SIGNALS = new Set(["sda", "scl"]);
const UART_SIGNALS = new Set(["tx", "rx", "txd", "rxd"]);

export interface ConnectorPinUsage {
  mode: ConnectorPinMode;
  devices: string[];
}

export interface ConnectorWiring {
  pins: Record<string, ConnectorPinUsage>;
  problems: string[];
}

export function connectorFor(hardwareMap: HardwareMap, connectorId: string | null | undefined): HardwareConnectorMapping | null {
  return (hardwareMap.connectors ?? []).find((connector) => connector.id === connectorId) ?? null;
}

export function connectorWiring(hardwareMap: HardwareMap, group: HardwareGroupMapping): ConnectorWiring {
  const connector = connectorFor(hardwareMap, group.connector_id);
  const pins: Record<string, ConnectorPinUsage> = {};
  const problems: string[] = [];
  if (!connector) {
    return { pins, problems };
  }

  for (const pin of connector.pins) {
    pins[pin.name] = { mode: "unused", devices: [] };
  }
  const members = new Set(group.member_ids);
  for (const device of hardwareMap.devices) {
    if (device.board_id !== connector.id || !members.has(device.id)) {
      continue;
    }
    for (const devicePin of device.pins) {
      const pin = connector.pins.find((candidate) => candidate.name === devicePin.gpio);
      if (!pin || devicePin.signal === "-") {
        continue;
      }
      const signal = devicePin.signal.trim().toLowerCase();
      const mode: ConnectorPinMode = pin.peripheral === "i2c" && I2C_SIGNALS.has(signal)
        ? "i2c"
        : pin.peripheral === "uart" && UART_SIGNALS.has(signal)
          ? "uart"
          : "gpio";
      const usage = pins[pin.name];
      if (usage.devices.length > 0 && !(mode === "i2c" && usage.mode === "i2c")) {
        problems.push(`${device.name} and ${usage.devices.join(", ")} are both wired to ${pin.name}.`);
      }
      usage.mode = mode;
      usage.devices.push(device.name);
    }
  }

  for (const [pinName, mode] of Object.entries(group.pin_modes ?? {})) {
    if (pins[pinName]) {
      pins[pinName].mode = mode;
    }
  }

  const i2cPins = connector.pins.filter((pin) => pin.peripheral === "i2c").map((pin) => pin.name);
  const usedI2c = i2cPins.filter((name) => pins[name]?.mode === "i2c");
  if (usedI2c.length > 0 && usedI2c.length !== i2cPins.length) {
    problems.push(`I2C needs both ${i2cPins.join(" and ")} wired.`);
  }

  if (group.verification === "loopback") {
    const busy = connector.pins
      .filter((pin) => pin.peripheral === "uart" && pins[pin.name]?.mode !== "unused")
      .map((pin) => pin.name);
    if (busy.length > 0) {
      problems.push(`Loopback verification shorts ${busy.join(" and ")} on the tool, so nothing else can be wired there.`);
    }
  }

  return { pins, problems };
}

export const PIN_MODE_LABELS: Record<ConnectorPinMode, string> = {
  unused: "Unused",
  i2c: "I2C",
  uart: "UART",
  gpio: "GPIO",
};
