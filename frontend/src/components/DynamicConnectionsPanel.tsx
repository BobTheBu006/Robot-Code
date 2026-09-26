import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { fetchConnectorStatus, type ConnectorStatus } from "../lib/api";
import { PIN_MODE_LABELS, connectorWiring } from "../lib/connectorWiring";
import {
  DEVICE_KIND_OPTIONS,
  SENSOR_KIND_OPTIONS,
  SIGNAL_LABELS,
  makeId,
  normalizeSensorKind,
  pinsForDevice,
} from "../lib/hardwareDevices";
import type {
  ConnectorVerification,
  HardwareConnectorMapping,
  HardwareDeviceKind,
  HardwareDeviceMapping,
  HardwareGroupMapping,
  HardwareMap,
  HardwarePinMapping,
  HardwareSensorKind,
} from "../types/hardwareMap";

// The rack has six slots; each holds at most one tool.
const RACK_SLOTS = [1, 2, 3, 4, 5, 6];

const VERIFICATION_OPTIONS: Array<{ value: ConnectorVerification; label: string; needsUsb?: boolean }> = [
  { value: "none", label: "Nothing (not verified)" },
  { value: "loopback", label: "TXD-RXD loopback" },
  { value: "fingerprint", label: "ESP32 fingerprint over USB", needsUsb: true },
  { value: "usb_serial", label: "USB serial number", needsUsb: true },
];

const NOT_WIRED = "-";

interface DynamicConnectionsPanelProps {
  hardwareMap: HardwareMap;
  setHardwareMap: Dispatch<SetStateAction<HardwareMap>>;
}

// Wire a new device's pins to connector pins of the same name where they are
// free, so an I2C sensor lands on SDA/SCL without any clicking.
function autoWire(pins: HardwarePinMapping[], connector: HardwareConnectorMapping): HardwarePinMapping[] {
  return pins.map((pin) => {
    if (pin.gpio !== NOT_WIRED) {
      return pin;
    }
    const match = connector.pins.find((candidate) => candidate.name.toLowerCase() === pin.signal.toLowerCase());
    return match ? { ...pin, gpio: match.name } : pin;
  });
}

export function DynamicConnectionsPanel({ hardwareMap, setHardwareMap }: DynamicConnectionsPanelProps) {
  const [statuses, setStatuses] = useState<ConnectorStatus[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const next = await fetchConnectorStatus();
        if (!cancelled) {
          setStatuses(next);
        }
      } catch {
        // Informational only.
      }
    }
    void refresh();
    const poll = window.setInterval(() => void refresh(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(poll);
    };
  }, []);

  const connectors = hardwareMap.connectors ?? [];
  const usbPorts = hardwareMap.usb_ports ?? [1, 2, 3, 4].map((number) => ({ number, label: `USB ${number}` }));

  // ---- edits ------------------------------------------------------------

  function updateConnector(connectorId: string, updates: Partial<HardwareConnectorMapping>) {
    setHardwareMap((current) => ({
      ...current,
      connectors: (current.connectors ?? []).map((connector) =>
        connector.id === connectorId ? { ...connector, ...updates } : connector,
      ),
    }));
  }

  function updateTool(groupId: string, updates: Partial<HardwareGroupMapping>) {
    setHardwareMap((current) => ({
      ...current,
      groups: (current.groups ?? []).map((group) => (group.id === groupId ? { ...group, ...updates } : group)),
    }));
  }

  function addTool(connectorId: string, slot: number | null) {
    const group: HardwareGroupMapping = {
      id: makeId("tool"),
      name: slot ? `Slot ${slot} tool` : "Hand-connected tool",
      member_ids: [],
      enabled: true,
      notes: null,
      connector_id: connectorId,
      pin_modes: {},
      usb_board_id: null,
      verification: "none",
      toolhead_index: slot,
    };
    setHardwareMap((current) => ({ ...current, groups: [...(current.groups ?? []), group] }));
  }

  function setToolUsbBoard(group: HardwareGroupMapping, boardId: string) {
    const usbBoardId = boardId || null;
    const usbVerification = group.verification === "fingerprint" || group.verification === "usb_serial";
    updateTool(group.id, {
      usb_board_id: usbBoardId,
      // A USB check needs something on the USB to check.
      verification: !usbBoardId && usbVerification ? "none" : group.verification,
    });
  }

  function removeTool(group: HardwareGroupMapping) {
    const label = group.name || "this tool";
    if (!window.confirm(`Remove ${label}? Hardware wired to the connector for it is removed too.`)) {
      return;
    }
    setHardwareMap((current) => {
      const removedDeviceIds = new Set(
        current.devices
          .filter((device) => device.board_id === group.connector_id && group.member_ids.includes(device.id))
          .map((device) => device.id),
      );
      return {
        ...current,
        groups: (current.groups ?? []).filter((candidate) => candidate.id !== group.id),
        devices: current.devices.filter((device) => !removedDeviceIds.has(device.id)),
        function_assignments: (current.function_assignments ?? []).filter(
          (assignment) => !removedDeviceIds.has(assignment.hardware_device_id),
        ),
      };
    });
  }

  function addDevice(group: HardwareGroupMapping, connector: HardwareConnectorMapping) {
    const kind: HardwareDeviceKind = "sensor";
    const sensorKind: HardwareSensorKind = "position_limit_switch";
    const device: HardwareDeviceMapping = {
      id: makeId("device"),
      board_id: connector.id,
      name: "New device",
      kind,
      enabled: true,
      sensor_kind: sensorKind,
      pins: autoWire(pinsForDevice(kind, sensorKind, [], connector.id), connector),
      notes: null,
    };
    setHardwareMap((current) => ({
      ...current,
      devices: [...current.devices, device],
      groups: (current.groups ?? []).map((candidate) =>
        candidate.id === group.id ? { ...candidate, member_ids: [...candidate.member_ids, device.id] } : candidate,
      ),
    }));
  }

  function updateDevice(deviceId: string, updates: Partial<HardwareDeviceMapping>) {
    setHardwareMap((current) => ({
      ...current,
      devices: current.devices.map((device) => (device.id === deviceId ? { ...device, ...updates } : device)),
    }));
  }

  function changeDeviceKind(
    device: HardwareDeviceMapping,
    connector: HardwareConnectorMapping,
    kind: HardwareDeviceKind,
    sensorKind: HardwareSensorKind,
  ) {
    const pins = autoWire(pinsForDevice(kind, sensorKind, device.pins, connector.id), connector);
    updateDevice(device.id, { kind, sensor_kind: kind === "sensor" ? sensorKind : null, pins });
  }

  function wirePin(device: HardwareDeviceMapping, pinId: string, connectorPin: string) {
    updateDevice(device.id, {
      pins: device.pins.map((pin) => (pin.id === pinId ? { ...pin, gpio: connectorPin } : pin)),
    });
  }

  function removeDevice(group: HardwareGroupMapping, deviceId: string) {
    setHardwareMap((current) => ({
      ...current,
      devices: current.devices.filter((device) => device.id !== deviceId),
      groups: (current.groups ?? []).map((candidate) =>
        candidate.id === group.id
          ? { ...candidate, member_ids: candidate.member_ids.filter((memberId) => memberId !== deviceId) }
          : candidate,
      ),
      function_assignments: (current.function_assignments ?? []).filter(
        (assignment) => assignment.hardware_device_id !== deviceId,
      ),
    }));
  }

  // ---- rendering --------------------------------------------------------

  function renderTool(group: HardwareGroupMapping, connector: HardwareConnectorMapping, status: ConnectorStatus | undefined) {
    const wiring = connectorWiring(hardwareMap, group);
    const devices = hardwareMap.devices.filter(
      (device) => device.board_id === connector.id && group.member_ids.includes(device.id),
    );
    const usbBoard = hardwareMap.boards.find((board) => board.id === group.usb_board_id) ?? null;
    const usbDevices = usbBoard ? hardwareMap.devices.filter((device) => device.board_id === usbBoard.id) : [];
    const takenSlots = new Set(
      (hardwareMap.groups ?? [])
        .filter((other) => other.id !== group.id && other.connector_id === connector.id && other.toolhead_index != null)
        .map((other) => other.toolhead_index as number),
    );
    const isActive = status?.active_group_id === group.id;

    return (
      <div className="dynamic-tool">
        <div className="dynamic-tool__header">
          <input
            aria-label="Tool name"
            className="dynamic-tool__name"
            onChange={(event) => updateTool(group.id, { name: event.target.value })}
            value={group.name}
          />
          {isActive ? (
            <span className={`dynamic-badge dynamic-badge--${status?.verified ? "verified" : "unverified"}`}>
              {status?.verified ? "Connected ✓" : "Connected (unverified)"}
            </span>
          ) : null}
        </div>

        <div className="dynamic-tool__pins">
          {connector.pins.map((pin) => {
            const usage = wiring.pins[pin.name];
            return (
              <div
                className={`dynamic-pin dynamic-pin--${usage?.mode ?? "unused"}`}
                key={pin.name}
                title={usage?.devices.length ? usage.devices.join(", ") : "Nothing wired"}
              >
                <strong>{pin.name}</strong>
                <span>{PIN_MODE_LABELS[usage?.mode ?? "unused"]}</span>
              </div>
            );
          })}
          <div className={`dynamic-pin dynamic-pin--${usbBoard ? "usb" : "unused"}`} title={usbBoard?.label ?? "Nothing on USB"}>
            <strong>USB</strong>
            <span>{usbBoard ? "Controller" : "Unused"}</span>
          </div>
        </div>

        {wiring.problems.length > 0 ? (
          <ul className="dynamic-tool__problems">
            {wiring.problems.map((problem) => <li key={problem}>{problem}</li>)}
          </ul>
        ) : null}

        <div className="dynamic-tool__devices">
          {devices.length === 0 ? <p className="dynamic-tool__empty-note">No hardware wired to the pogo pins.</p> : null}
          {devices.map((device) => {
            const kind = device.kind;
            const sensorKind = normalizeSensorKind(device.sensor_kind);
            return (
              <div className="dynamic-device" key={device.id}>
                <div className="dynamic-device__row">
                  <input
                    aria-label="Device name"
                    onChange={(event) => updateDevice(device.id, { name: event.target.value })}
                    value={device.name}
                  />
                  <button
                    aria-label={`Remove ${device.name}`}
                    className="hardware-map__small-button"
                    onClick={() => removeDevice(group, device.id)}
                    type="button"
                  >
                    Remove
                  </button>
                </div>
                <div className="dynamic-device__row">
                  <select
                    aria-label="Device kind"
                    onChange={(event) => changeDeviceKind(device, connector, event.target.value as HardwareDeviceKind, sensorKind)}
                    value={kind}
                  >
                    {DEVICE_KIND_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                  {kind === "sensor" ? (
                    <select
                      aria-label="Sensor kind"
                      onChange={(event) => changeDeviceKind(device, connector, kind, event.target.value as HardwareSensorKind)}
                      value={sensorKind}
                    >
                      {SENSOR_KIND_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  ) : null}
                </div>
                <div className="dynamic-device__wires">
                  {device.pins.map((pin) => (
                    <label className="dynamic-device__wire" key={pin.id}>
                      <span>{SIGNAL_LABELS[pin.signal] ?? pin.signal}</span>
                      <select onChange={(event) => wirePin(device, pin.id, event.target.value)} value={pin.gpio}>
                        <option value={NOT_WIRED}>Not wired</option>
                        {connector.pins.map((connectorPin) => (
                          <option key={connectorPin.name} value={connectorPin.name}>
                            {connectorPin.name} (GPIO {connectorPin.gpio})
                          </option>
                        ))}
                      </select>
                    </label>
                  ))}
                </div>
              </div>
            );
          })}
          <button className="hardware-map__small-button" onClick={() => addDevice(group, connector)} type="button">
            + Wire hardware to the pins
          </button>
        </div>

        <label className="hardware-settings__field">
          <span>USB controller</span>
          <select onChange={(event) => setToolUsbBoard(group, event.target.value)} value={group.usb_board_id ?? ""}>
            <option value="">Nothing on USB</option>
            {hardwareMap.boards.map((board) => (
              <option key={board.id} value={board.id}>{board.label}</option>
            ))}
          </select>
          {usbBoard ? (
            <small className="dynamic-tool__usb-note">
              {usbDevices.length} device{usbDevices.length === 1 ? "" : "s"} on {usbBoard.label}; their pins are
              edited under Fixed connections.
            </small>
          ) : null}
        </label>

        <label className="hardware-settings__field">
          <span>Verify with</span>
          <select
            onChange={(event) => updateTool(group.id, { verification: event.target.value as ConnectorVerification })}
            value={group.verification ?? "none"}
          >
            {VERIFICATION_OPTIONS.map((option) => (
              <option disabled={option.needsUsb && !group.usb_board_id} key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <div className="dynamic-tool__footer">
          <label className="hardware-settings__field">
            <span>Rack slot</span>
            <select
              onChange={(event) => updateTool(group.id, {
                toolhead_index: event.target.value ? Number(event.target.value) : null,
              })}
              value={group.toolhead_index ?? ""}
            >
              <option value="">Not in the rack</option>
              {RACK_SLOTS.map((slot) => (
                <option disabled={takenSlots.has(slot)} key={slot} value={slot}>
                  Slot {slot}{takenSlots.has(slot) ? " (taken)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="hardware-settings__check">
            <input
              checked={group.enabled !== false}
              onChange={(event) => updateTool(group.id, { enabled: event.target.checked })}
              type="checkbox"
            />
            <span>Enabled</span>
          </label>
          <button className="hardware-map__small-button dynamic-tool__remove" onClick={() => removeTool(group)} type="button">
            Remove tool
          </button>
        </div>
      </div>
    );
  }

  if (connectors.length === 0) {
    return (
      <div className="dynamic-connections">
        <p className="dynamic-tool__empty-note">No dynamic connector is defined in the Hardware Map.</p>
      </div>
    );
  }

  return (
    <div className="dynamic-connections hardware-settings">
      {connectors.map((connector) => {
        const status = statuses.find((candidate) => candidate.connector_id === connector.id);
        const tools = (hardwareMap.groups ?? []).filter((group) => group.connector_id === connector.id);
        const unslotted = tools.filter((group) => group.toolhead_index == null);

        return (
          <section className="dynamic-connections__connector" key={connector.id}>
            <div className="dynamic-connector">
              <div className="dynamic-connector__title">
                <h2>{connector.label}</h2>
                <span className="dynamic-connector__status" title={status?.message}>
                  {status?.active_group_name ? `On the head: ${status.active_group_name}` : "Nothing connected"}
                </span>
              </div>
              <div className="dynamic-connector__pins">
                {connector.pins.map((pin) => (
                  <div className="dynamic-connector__pin" key={pin.name}>
                    <strong>{pin.name}</strong>
                    <span>GPIO {pin.gpio}{pin.peripheral ? ` · ${pin.peripheral.toUpperCase()}` : ""}</span>
                  </div>
                ))}
              </div>
              <div className="dynamic-connector__settings">
                <label className="hardware-settings__field">
                  <span>Dynamic USB port</span>
                  <select
                    onChange={(event) => updateConnector(connector.id, {
                      usb_port_number: event.target.value ? Number(event.target.value) : null,
                    })}
                    value={connector.usb_port_number ?? ""}
                  >
                    <option value="">Not set</option>
                    {usbPorts.map((port) => (
                      <option key={port.number} value={port.number}>{port.label}</option>
                    ))}
                  </select>
                </label>
                <label className="hardware-settings__check">
                  <input
                    checked={connector.enabled !== false}
                    onChange={(event) => updateConnector(connector.id, { enabled: event.target.checked })}
                    type="checkbox"
                  />
                  <span>Connector enabled</span>
                </label>
              </div>
            </div>

            <div className="dynamic-connections__slots">
              {RACK_SLOTS.map((slot) => {
                const tool = tools.find((group) => group.toolhead_index === slot);
                return (
                  <article
                    className={tool ? "dynamic-slot" : "dynamic-slot dynamic-slot--empty"}
                    key={slot}
                  >
                    <header className="dynamic-slot__header">Slot {slot}</header>
                    {tool ? renderTool(tool, connector, status) : (
                      <div className="dynamic-slot__empty">
                        <p>No tool in this slot.</p>
                        <button className="workflow-editor__action" onClick={() => addTool(connector.id, slot)} type="button">
                          Add tool
                        </button>
                        {unslotted.length > 0 ? (
                          <select
                            aria-label="Move a tool here"
                            onChange={(event) => {
                              if (event.target.value) {
                                updateTool(event.target.value, { toolhead_index: slot });
                              }
                            }}
                            value=""
                          >
                            <option value="">Move a tool here…</option>
                            {unslotted.map((group) => (
                              <option key={group.id} value={group.id}>{group.name}</option>
                            ))}
                          </select>
                        ) : null}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>

            <div className="dynamic-connections__unslotted">
              <header className="dynamic-slot__header">Not in the rack (Connect Tool block only)</header>
              <div className="dynamic-connections__slots">
                {unslotted.map((group) => (
                  <article className="dynamic-slot" key={group.id}>
                    {renderTool(group, connector, status)}
                  </article>
                ))}
                <article className="dynamic-slot dynamic-slot--empty">
                  <div className="dynamic-slot__empty">
                    <button className="workflow-editor__action" onClick={() => addTool(connector.id, null)} type="button">
                      Add hand-connected tool
                    </button>
                  </div>
                </article>
              </div>
            </div>
          </section>
        );
      })}
    </div>
  );
}
