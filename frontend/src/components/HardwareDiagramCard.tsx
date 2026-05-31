import { useEffect, useMemo, useState, type CSSProperties } from "react";

import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";

import { fetchEsp32Boards, fetchHardwareMap, saveHardwareMap } from "../lib/api";
import type { Esp32BoardSummary } from "../types/esp32Builder";
import type {
  HardwareBoardMapping,
  HardwareDeviceKind,
  HardwareDeviceMapping,
  HardwareMap,
  HardwarePinMapping,
  HardwareSensorKind,
} from "../types/hardwareMap";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

type RequestStatus = "loading" | "success" | "error";
type SaveState = "idle" | "saving" | "saved" | "error";
type HardwareNodeKind = "raspberry" | "controller" | "device";
type HardwareFlowNode = Node<HardwareNodeData>;

interface HardwareDiagramCardProps {
  onHardwareMapSaved: () => void;
}

interface HardwareNodeData extends Record<string, unknown> {
  kind: HardwareNodeKind;
  title: string;
  detail: string;
  meta: string;
  accent: string;
  status?: string;
}

const RASPBERRY_NODE_ID = "raspberry-pi";
const EMPTY_HARDWARE_MAP: HardwareMap = {
  version: 1,
  boards: [],
  devices: [],
  updated_at: null,
};

const DEVICE_KIND_OPTIONS: Array<{ label: string; value: HardwareDeviceKind }> = [
  { label: "Stepper motor", value: "stepper_motor" },
  { label: "Servo", value: "servo" },
  { label: "Sensor", value: "sensor" },
];
const SENSOR_KIND_OPTIONS: Array<{ label: string; value: HardwareSensorKind }> = [
  { label: "Position / limit switch", value: "position_limit_switch" },
  { label: "AHT20 temperature + humidity", value: "aht20_temperature_humidity" },
];
const STEPPER_SIGNALS = ["direction", "step", "enable", "micro_step_1", "micro_step_2", "micro_step_3"];
const SIGNAL_LABELS: Record<string, string> = {
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

function makeId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeId(value: string, fallback: string): string {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

  return normalized || fallback;
}

function normalizeDeviceKind(kind: string | undefined): HardwareDeviceKind {
  if (kind === "sensor" || kind === "servo" || kind === "stepper_motor") {
    return kind;
  }

  if (kind === "motor") {
    return "stepper_motor";
  }

  return "servo";
}

function normalizeSensorKind(sensorKind: string | null | undefined): HardwareSensorKind {
  return sensorKind === "aht20_temperature_humidity" ? "aht20_temperature_humidity" : "position_limit_switch";
}

function normalizePinSignal(signal: string): string {
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

function pinTemplateForDevice(
  kind: HardwareDeviceKind,
  sensorKind: HardwareSensorKind = "position_limit_switch",
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
    return [
      { signal: "scl", gpio: "-", function_input_key: null },
      { signal: "sda", gpio: "-", function_input_key: null },
    ];
  }

  return [{ signal: "signal", gpio: "-", function_input_key: null }];
}

function pinsForDevice(
  kind: HardwareDeviceKind,
  sensorKind: HardwareSensorKind = "position_limit_switch",
  existingPins: HardwarePinMapping[] = [],
): HardwarePinMapping[] {
  const existingBySignal = new Map(existingPins.map((pin) => [normalizePinSignal(pin.signal), pin]));

  return pinTemplateForDevice(kind, sensorKind).map((template, index) => {
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

function normalizeServoRangeValue(value: number | string | null | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function deviceKindLabel(kind: HardwareDeviceKind): string {
  return DEVICE_KIND_OPTIONS.find((option) => option.value === kind)?.label ?? kind;
}

function sensorKindLabel(sensorKind: HardwareSensorKind | null | undefined): string {
  return SENSOR_KIND_OPTIONS.find((option) => option.value === sensorKind)?.label ?? "Position / limit switch";
}

function deviceAccent(device: HardwareDeviceMapping): string {
  const kind = normalizeDeviceKind(device.kind);
  if (kind === "stepper_motor") {
    return "#a85d13";
  }

  if (kind === "sensor") {
    return "#1b7f5c";
  }

  return "#8e4ec6";
}

function HardwareDiagramNode({ data, selected }: NodeProps<HardwareFlowNode>) {
  return (
    <div
      className={[
        "hardware-flow-node",
        `hardware-flow-node--${data.kind}`,
        selected ? "hardware-flow-node--selected" : "",
      ].filter(Boolean).join(" ")}
      style={{ "--hardware-node-accent": data.accent } as CSSProperties}
    >
      {data.kind !== "raspberry" ? <Handle className="hardware-flow-node__handle" position={Position.Left} type="target" /> : null}
      <div className="hardware-flow-node__type">{data.kind}</div>
      <strong>{data.title}</strong>
      <span>{data.detail}</span>
      <small>{data.meta}</small>
      {data.status ? <em>{data.status}</em> : null}
      {data.kind !== "device" ? <Handle className="hardware-flow-node__handle" position={Position.Right} type="source" /> : null}
    </div>
  );
}

const nodeTypes: NodeTypes = {
  hardwareNode: HardwareDiagramNode,
};

function mergeDetectedBoards(hardwareMap: HardwareMap, detectedBoards: Esp32BoardSummary[]): HardwareMap {
  const existingBoardKeys = new Set(
    hardwareMap.boards.flatMap((board) => [board.id, board.usb_port].filter(Boolean)),
  );

  const missingBoards = detectedBoards
    .filter((board) => !existingBoardKeys.has(board.board_id) && (!board.port || !existingBoardKeys.has(board.port)))
    .map<HardwareBoardMapping>((board) => ({
      id: board.board_id,
      label: board.display_name,
      usb_port: board.port ?? board.board_id,
      notes: board.connected ? "Detected from the Pi." : "Workspace exists, but the board is currently offline.",
    }));

  return {
    ...hardwareMap,
    boards: [...hardwareMap.boards, ...missingBoards],
  };
}

function cleanHardwareMap(hardwareMap: HardwareMap): HardwareMap {
  const boards = hardwareMap.boards
    .map((board) => ({
      ...board,
      id: board.id.trim(),
      label: board.label.trim(),
      usb_port: board.usb_port.trim(),
      notes: board.notes?.trim() || null,
    }))
    .filter((board) => board.id && board.label && board.usb_port);
  const boardIds = new Set(boards.map((board) => board.id));
  const fallbackBoardId = boards[0]?.id ?? "";
  const devices = hardwareMap.devices
    .map((device) => {
      const kind = normalizeDeviceKind(device.kind);
      const sensorKind = kind === "sensor" ? normalizeSensorKind(device.sensor_kind) : null;
      const pins = pinsForDevice(kind, sensorKind ?? "position_limit_switch", device.pins);

        return {
          ...device,
          board_id: boardIds.has(device.board_id.trim()) ? device.board_id.trim() : fallbackBoardId,
          name: device.name.trim(),
          kind,
          sensor_kind: sensorKind,
          rotation_min_deg: kind === "servo" ? normalizeServoRangeValue(device.rotation_min_deg, -5) : null,
          rotation_max_deg: kind === "servo" ? normalizeServoRangeValue(device.rotation_max_deg, 175) : null,
          notes: device.notes?.trim() || null,
          pins,
        };
    })
    .filter((device) => boardIds.has(device.board_id) && device.name);

  return {
    version: 1,
    boards,
    devices,
    updated_at: hardwareMap.updated_at ?? null,
  };
}

function getDetectedBoard(
  board: HardwareBoardMapping,
  detectedBoards: Esp32BoardSummary[],
): Esp32BoardSummary | null {
  return detectedBoards.find((detectedBoard) =>
    detectedBoard.board_id === board.id || detectedBoard.port === board.usb_port,
  ) ?? null;
}

function buildHardwareNodes(
  hardwareMap: HardwareMap,
  detectedBoards: Esp32BoardSummary[],
  currentNodes: HardwareFlowNode[],
): HardwareFlowNode[] {
  const previousPositionById = new Map(currentNodes.map((node) => [node.id, node.position]));
  const devicesByBoard = new Map<string, HardwareDeviceMapping[]>();
  for (const device of hardwareMap.devices) {
    devicesByBoard.set(device.board_id, [...(devicesByBoard.get(device.board_id) ?? []), device]);
  }

  const nodes: HardwareFlowNode[] = [
    {
      id: RASPBERRY_NODE_ID,
      type: "hardwareNode",
      position: previousPositionById.get(RASPBERRY_NODE_ID) ?? { x: 40, y: 180 },
      data: {
        kind: "raspberry",
        title: "Raspberry Pi",
        detail: "USB host",
        meta: `${hardwareMap.boards.length} controller${hardwareMap.boards.length === 1 ? "" : "s"}`,
        accent: "#175c96",
        status: "source",
      },
    },
  ];

  hardwareMap.boards.forEach((board, boardIndex) => {
    const detectedBoard = getDetectedBoard(board, detectedBoards);
    const boardDevices = devicesByBoard.get(board.id) ?? [];
    const boardY = 80 + boardIndex * Math.max(190, Math.max(boardDevices.length, 1) * 110);

    nodes.push({
      id: board.id,
      type: "hardwareNode",
      position: previousPositionById.get(board.id) ?? { x: 350, y: boardY },
      data: {
        kind: "controller",
        title: board.label,
        detail: board.usb_port,
        meta: `${boardDevices.length} device${boardDevices.length === 1 ? "" : "s"}`,
        accent: "#0e7490",
        status: detectedBoard?.connected ? "connected" : detectedBoard ? "offline" : "manual",
      },
    });

    boardDevices.forEach((device, deviceIndex) => {
      nodes.push({
        id: device.id,
        type: "hardwareNode",
        position: previousPositionById.get(device.id) ?? { x: 680, y: boardY + deviceIndex * 110 },
        data: {
          kind: "device",
          title: device.name,
          detail: normalizeDeviceKind(device.kind) === "sensor"
            ? sensorKindLabel(device.sensor_kind)
            : deviceKindLabel(normalizeDeviceKind(device.kind)),
          meta: `${device.pins.length} pin${device.pins.length === 1 ? "" : "s"}`,
          accent: deviceAccent(device),
        },
      });
    });
  });

  return nodes;
}

function buildHardwareEdges(hardwareMap: HardwareMap): Edge[] {
  return [
    ...hardwareMap.boards.map((board) => ({
      id: `edge-${RASPBERRY_NODE_ID}-${board.id}`,
      source: RASPBERRY_NODE_ID,
      target: board.id,
      type: "smoothstep",
      animated: true,
      label: board.usb_port,
    })),
    ...hardwareMap.devices.map((device) => ({
      id: `edge-${device.board_id}-${device.id}`,
      source: device.board_id,
      target: device.id,
      type: "smoothstep",
      label: deviceKindLabel(normalizeDeviceKind(device.kind)),
    })),
  ];
}

function boardFromNodeId(hardwareMap: HardwareMap, nodeId: string | null): HardwareBoardMapping | null {
  if (!nodeId) {
    return null;
  }

  return hardwareMap.boards.find((board) => board.id === nodeId) ?? null;
}

function deviceFromNodeId(hardwareMap: HardwareMap, nodeId: string | null): HardwareDeviceMapping | null {
  if (!nodeId) {
    return null;
  }

  return hardwareMap.devices.find((device) => device.id === nodeId) ?? null;
}

function HardwareDiagramSurface({ onHardwareMapSaved }: HardwareDiagramCardProps) {
  const [status, setStatus] = useState<RequestStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [hardwareMap, setHardwareMap] = useState<HardwareMap>(EMPTY_HARDWARE_MAP);
  const [detectedBoards, setDetectedBoards] = useState<Esp32BoardSummary[]>([]);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(RASPBERRY_NODE_ID);
  const [nodes, setNodes, onNodesChange] = useNodesState<HardwareFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const selectedBoard = boardFromNodeId(hardwareMap, selectedNodeId);
  const selectedDevice = deviceFromNodeId(hardwareMap, selectedNodeId);
  const selectedKind: HardwareNodeKind = selectedNodeId === null || selectedNodeId === RASPBERRY_NODE_ID
    ? "raspberry"
    : selectedBoard
      ? "controller"
      : "device";
  const detectedSelectedBoard = selectedBoard ? getDetectedBoard(selectedBoard, detectedBoards) : null;
  const devicesByBoard = useMemo(() => {
    const groupedDevices = new Map<string, HardwareDeviceMapping[]>();
    for (const device of hardwareMap.devices) {
      groupedDevices.set(device.board_id, [...(groupedDevices.get(device.board_id) ?? []), device]);
    }
    return groupedDevices;
  }, [hardwareMap.devices]);
  const controllerPortOptions = useMemo(() => {
    const options = detectedBoards
      .map((board) => ({
        label: `${board.port ?? board.board_id}${board.description ? ` - ${board.description}` : ""}`,
        value: board.port ?? board.board_id,
      }))
      .filter((option) => option.value);
    const existingValues = new Set(options.map((option) => option.value));

    for (const board of hardwareMap.boards) {
      if (board.usb_port && !existingValues.has(board.usb_port)) {
        options.push({
          label: `${board.usb_port} - manual`,
          value: board.usb_port,
        });
        existingValues.add(board.usb_port);
      }
    }

    return options;
  }, [detectedBoards, hardwareMap.boards]);

  async function loadHardwareMap() {
    setStatus("loading");
    setError(null);

    const [hardwareMapResult, detectedBoardsResult] = await Promise.allSettled([
      fetchHardwareMap(),
      fetchEsp32Boards(),
    ]);

    const nextDetectedBoards = detectedBoardsResult.status === "fulfilled" ? detectedBoardsResult.value.boards : [];
    setDetectedBoards(nextDetectedBoards);

    if (hardwareMapResult.status === "fulfilled") {
      setHardwareMap(cleanHardwareMap(mergeDetectedBoards(hardwareMapResult.value, nextDetectedBoards)));
      setStatus("success");
      setSaveState("idle");
      setSaveMessage(null);
      return;
    }

    setStatus("error");
    setError(hardwareMapResult.reason instanceof Error ? hardwareMapResult.reason.message : "Could not load the hardware map.");
  }

  useEffect(() => {
    void loadHardwareMap();
  }, []);

  useEffect(() => {
    setNodes((currentNodes) => buildHardwareNodes(hardwareMap, detectedBoards, currentNodes));
    setEdges(buildHardwareEdges(hardwareMap));
  }, [hardwareMap, detectedBoards, setEdges, setNodes]);

  useEffect(() => {
    if (!selectedNodeId) {
      return;
    }

    const selectedNodeStillExists = selectedNodeId === RASPBERRY_NODE_ID
      || hardwareMap.boards.some((board) => board.id === selectedNodeId)
      || hardwareMap.devices.some((device) => device.id === selectedNodeId);

    if (!selectedNodeStillExists) {
      setSelectedNodeId(RASPBERRY_NODE_ID);
    }
  }, [hardwareMap, selectedNodeId]);

  function updateBoard(boardId: string, updates: Partial<HardwareBoardMapping>) {
    setHardwareMap((currentMap) => {
      const nextId = updates.id ?? boardId;
      return {
        ...currentMap,
        boards: currentMap.boards.map((board) =>
          board.id === boardId ? { ...board, ...updates } : board,
        ),
        devices: nextId !== boardId
          ? currentMap.devices.map((device) =>
              device.board_id === boardId ? { ...device, board_id: nextId } : device,
            )
          : currentMap.devices,
      };
    });
    if (updates.id) {
      setSelectedNodeId(updates.id);
    }
    setSaveState("idle");
  }

  function addBoard() {
    const nextId = makeId("controller");
    setHardwareMap((currentMap) => ({
      ...currentMap,
      boards: [
        ...currentMap.boards,
        {
          id: nextId,
          label: "New Controller",
          usb_port: "/dev/ttyUSB0",
          notes: null,
        },
      ],
    }));
    setSelectedNodeId(nextId);
    setSaveState("idle");
  }

  function removeBoard(boardId: string) {
    setHardwareMap((currentMap) => ({
      ...currentMap,
      boards: currentMap.boards.filter((board) => board.id !== boardId),
      devices: currentMap.devices.filter((device) => device.board_id !== boardId),
    }));
    setSelectedNodeId(RASPBERRY_NODE_ID);
    setSaveState("idle");
  }

  function addDevice(boardId = hardwareMap.boards[0]?.id) {
    if (!boardId) {
      addBoard();
      return;
    }

    const nextId = makeId("device");
    setHardwareMap((currentMap) => ({
      ...currentMap,
      devices: [
        ...currentMap.devices,
        {
          id: nextId,
          board_id: boardId,
          name: "New IoT Device",
          kind: "stepper_motor",
          sensor_kind: null,
          rotation_min_deg: null,
          rotation_max_deg: null,
          pins: pinsForDevice("stepper_motor"),
          notes: null,
        },
      ],
    }));
    setSelectedNodeId(nextId);
    setSaveState("idle");
  }

  function updateDevice(deviceId: string, updates: Partial<HardwareDeviceMapping>) {
    setHardwareMap((currentMap) => ({
      ...currentMap,
      devices: currentMap.devices.map((device) =>
        device.id === deviceId ? { ...device, ...updates } : device,
      ),
    }));
    setSaveState("idle");
  }

  function removeDevice(deviceId: string) {
    setHardwareMap((currentMap) => ({
      ...currentMap,
      devices: currentMap.devices.filter((device) => device.id !== deviceId),
    }));
    setSelectedNodeId(RASPBERRY_NODE_ID);
    setSaveState("idle");
  }

  function addPin(deviceId: string) {
    const device = deviceFromNodeId(hardwareMap, deviceId);
    if (device) {
      updateDevice(device.id, {
        pins: pinsForDevice(normalizeDeviceKind(device.kind), normalizeSensorKind(device.sensor_kind), device.pins),
      });
      return;
    }

    const nextPin: HardwarePinMapping = {
      id: makeId("pin"),
      signal: "Signal",
      gpio: "0",
      function_input_key: null,
      notes: null,
    };
    setHardwareMap((currentMap) => ({
      ...currentMap,
      devices: currentMap.devices.map((device) =>
        device.id === deviceId
          ? { ...device, pins: [...device.pins, nextPin] }
          : device,
      ),
    }));
    setSaveState("idle");
  }

  function updatePin(deviceId: string, pinId: string, updates: Partial<HardwarePinMapping>) {
    setHardwareMap((currentMap) => ({
      ...currentMap,
      devices: currentMap.devices.map((device) =>
        device.id === deviceId
          ? {
              ...device,
              pins: device.pins.map((pin) =>
                pin.id === pinId ? { ...pin, ...updates } : pin,
              ),
            }
          : device,
      ),
    }));
    setSaveState("idle");
  }

  function removePin(deviceId: string, pinId: string) {
    setHardwareMap((currentMap) => ({
      ...currentMap,
      devices: currentMap.devices.map((device) =>
        device.id === deviceId
          ? { ...device, pins: device.pins.filter((pin) => pin.id !== pinId) }
          : device,
      ),
    }));
    setSaveState("idle");
  }

  function handleConnect(connection: Connection) {
    if (!connection.source || !connection.target) {
      return;
    }

    const targetDevice = deviceFromNodeId(hardwareMap, connection.target);
    const sourceBoard = boardFromNodeId(hardwareMap, connection.source);
    if (!targetDevice || !sourceBoard) {
      return;
    }

    updateDevice(targetDevice.id, { board_id: sourceBoard.id });
    setSelectedNodeId(targetDevice.id);
  }

  async function handleSave() {
    const cleanedMap = cleanHardwareMap(hardwareMap);
    if (cleanedMap.boards.length === 0) {
      setSaveState("error");
      setSaveMessage("Add at least one controller before saving the hardware map.");
      return;
    }

    setSaveState("saving");
    setSaveMessage(null);
    try {
      const response = await saveHardwareMap(cleanedMap);
      setHardwareMap(response.hardware_map);
      setSaveState("saved");
      setSaveMessage(`Saved ${response.path}`);
      onHardwareMapSaved();
    } catch (saveError) {
      setSaveState("error");
      setSaveMessage(saveError instanceof Error ? saveError.message : "Could not save the hardware map.");
    }
  }

  function renderSettings() {
    if (selectedKind === "raspberry") {
      return (
        <div className="hardware-settings__body">
          <div className="hardware-settings__stat">
            <span>Controllers</span>
            <strong>{hardwareMap.boards.length}</strong>
          </div>
          <div className="hardware-settings__stat">
            <span>IoT devices</span>
            <strong>{hardwareMap.devices.length}</strong>
          </div>
          <button className="workflow-editor__action workflow-editor__action--primary" onClick={addBoard} type="button">
            Add controller
          </button>
        </div>
      );
    }

    if (selectedBoard) {
      const boardDevices = devicesByBoard.get(selectedBoard.id) ?? [];

      return (
        <div className="hardware-settings__body">
          <label className="hardware-settings__field">
            <span>Name</span>
            <input
              onChange={(event) => updateBoard(selectedBoard.id, { label: event.target.value })}
              value={selectedBoard.label}
            />
          </label>
          <label className="hardware-settings__field">
            <span>USB port</span>
            <select
              onChange={(event) => updateBoard(selectedBoard.id, { usb_port: event.target.value })}
              value={selectedBoard.usb_port}
            >
              {controllerPortOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="hardware-settings__field">
            <span>Controller id</span>
            <input
              defaultValue={selectedBoard.id}
              key={`${selectedBoard.id}-settings-id`}
              onBlur={(event) => updateBoard(selectedBoard.id, { id: normalizeId(event.target.value, selectedBoard.id) })}
            />
          </label>
          <label className="hardware-settings__field">
            <span>Notes</span>
            <textarea
              onChange={(event) => updateBoard(selectedBoard.id, { notes: event.target.value })}
              value={selectedBoard.notes ?? ""}
            />
          </label>
          <div className="hardware-settings__connection-row">
            <span>{detectedSelectedBoard?.connected ? "Connected" : detectedSelectedBoard ? "Offline" : "Manual"}</span>
            <strong>{boardDevices.length} device{boardDevices.length === 1 ? "" : "s"}</strong>
          </div>
          <div className="hardware-settings__actions">
            <button className="workflow-editor__action" onClick={() => addDevice(selectedBoard.id)} type="button">
              Add IoT device
            </button>
            <button className="workflow-editor__action" onClick={() => removeBoard(selectedBoard.id)} type="button">
              Remove
            </button>
          </div>
        </div>
      );
    }

    if (!selectedDevice) {
      return <p className="muted-text">Select a block to edit its settings.</p>;
    }

    return (
      <div className="hardware-settings__body">
        <label className="hardware-settings__field">
          <span>Name</span>
          <input
            onChange={(event) => updateDevice(selectedDevice.id, { name: event.target.value })}
            value={selectedDevice.name}
          />
        </label>
        <div className="hardware-settings__field-grid">
          <label className="hardware-settings__field">
            <span>Type</span>
            <select
              onChange={(event) => {
                const nextKind = event.target.value as HardwareDeviceKind;
                const nextSensorKind = nextKind === "sensor" ? normalizeSensorKind(selectedDevice.sensor_kind) : null;
                updateDevice(selectedDevice.id, {
                  kind: nextKind,
                  sensor_kind: nextSensorKind,
                  rotation_min_deg: nextKind === "servo" ? selectedDevice.rotation_min_deg ?? -5 : null,
                  rotation_max_deg: nextKind === "servo" ? selectedDevice.rotation_max_deg ?? 175 : null,
                  pins: pinsForDevice(nextKind, nextSensorKind ?? "position_limit_switch", selectedDevice.pins),
                });
              }}
              value={normalizeDeviceKind(selectedDevice.kind)}
            >
              {DEVICE_KIND_OPTIONS.map((kindOption) => (
                <option key={kindOption.value} value={kindOption.value}>
                  {kindOption.label}
                </option>
              ))}
            </select>
          </label>
          <label className="hardware-settings__field">
            <span>Controller</span>
            <select
              onChange={(event) => updateDevice(selectedDevice.id, { board_id: event.target.value })}
              value={selectedDevice.board_id}
            >
              {hardwareMap.boards.map((board) => (
                <option key={board.id} value={board.id}>
                  {board.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {normalizeDeviceKind(selectedDevice.kind) === "sensor" ? (
          <label className="hardware-settings__field">
            <span>Sensor subtype</span>
            <select
              onChange={(event) => {
                const nextSensorKind = event.target.value as HardwareSensorKind;
                updateDevice(selectedDevice.id, {
                  sensor_kind: nextSensorKind,
                  pins: pinsForDevice("sensor", nextSensorKind, selectedDevice.pins),
                });
              }}
              value={normalizeSensorKind(selectedDevice.sensor_kind)}
            >
              {SENSOR_KIND_OPTIONS.map((sensorOption) => (
                <option key={sensorOption.value} value={sensorOption.value}>
                  {sensorOption.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {normalizeDeviceKind(selectedDevice.kind) === "servo" ? (
          <div className="hardware-settings__field-grid">
            <label className="hardware-settings__field">
              <span>Rotation min</span>
              <input
                onChange={(event) =>
                  updateDevice(selectedDevice.id, {
                    rotation_min_deg: Number(event.target.value),
                  })}
                type="number"
                value={selectedDevice.rotation_min_deg ?? -5}
              />
            </label>
            <label className="hardware-settings__field">
              <span>Rotation max</span>
              <input
                onChange={(event) =>
                  updateDevice(selectedDevice.id, {
                    rotation_max_deg: Number(event.target.value),
                  })}
                type="number"
                value={selectedDevice.rotation_max_deg ?? 175}
              />
            </label>
          </div>
        ) : null}
        <label className="hardware-settings__field">
          <span>Notes</span>
          <textarea
            onChange={(event) => updateDevice(selectedDevice.id, { notes: event.target.value })}
            value={selectedDevice.notes ?? ""}
          />
        </label>

        <div className="hardware-settings__pin-header">
          <div>
            <strong>Pins</strong>
            <p>Signal is the hardware role, GPIO is the ESP32 pin number or '-' when not connected, and workflow input links that GPIO to matching function block dropdowns.</p>
          </div>
          <button className="hardware-map__small-button" onClick={() => addPin(selectedDevice.id)} type="button">
            Reset pins
          </button>
        </div>
        <div className="hardware-settings__pin-list">
          {selectedDevice.pins.length === 0 ? <p className="muted-text">No pins configured.</p> : null}
          {selectedDevice.pins.length > 0 ? (
            <div className="hardware-settings__pin-labels">
              <span>Pin role</span>
              <span>GPIO</span>
              <span>Workflow input</span>
              <span>Action</span>
            </div>
          ) : null}
          {selectedDevice.pins.map((pin) => (
            <div className="hardware-settings__pin" key={pin.id}>
              <div className="hardware-settings__pin-signal">
                {SIGNAL_LABELS[pin.signal] ?? pin.signal}
              </div>
              <input
                aria-label="GPIO"
                onChange={(event) => updatePin(selectedDevice.id, pin.id, { gpio: event.target.value })}
                placeholder="-"
                value={pin.gpio}
              />
              <input
                aria-label="Function input key"
                onChange={(event) => updatePin(selectedDevice.id, pin.id, { function_input_key: event.target.value })}
                placeholder="x_step_pin"
                value={pin.function_input_key ?? ""}
              />
              <button className="hardware-map__small-button" onClick={() => updatePin(selectedDevice.id, pin.id, { gpio: "-", function_input_key: null })} type="button">
                Clear
              </button>
            </div>
          ))}
        </div>

        <button className="workflow-editor__action" onClick={() => removeDevice(selectedDevice.id)} type="button">
          Remove device
        </button>
      </div>
    );
  }

  return (
    <Panel
      title="Hardware Map"
      subtitle="Build the electronics map as connected blocks. Select a controller or IoT device to edit ports and pins."
      headerAction={(
        <div className="hardware-map__header-actions">
          <button className="workflow-editor__action" onClick={() => void loadHardwareMap()} type="button">
            Refresh
          </button>
          <button className="workflow-editor__action" onClick={addBoard} type="button">
            Add controller
          </button>
          <button className="workflow-editor__action" onClick={() => addDevice()} type="button">
            Add IoT device
          </button>
          <button
            className="workflow-editor__action workflow-editor__action--primary"
            disabled={saveState === "saving"}
            onClick={() => void handleSave()}
            type="button"
          >
            {saveState === "saving" ? "Saving..." : "Save map"}
          </button>
        </div>
      )}
    >
      <div className="hardware-map">
        <div className="hardware-map__summary">
          <div>
            <strong>{hardwareMap.boards.length} controller blocks</strong>
            <span>{hardwareMap.devices.length} IoT device blocks</span>
          </div>
          <StatusBadge
            label={status === "success" ? "Map loaded" : status === "loading" ? "Loading" : "Map error"}
            tone={status === "success" ? "online" : status === "loading" ? "neutral" : "offline"}
          />
        </div>

        {status === "error" ? <p className="error-text">{error}</p> : null}
        {saveMessage ? (
          <p className={saveState === "error" ? "error-text" : "hardware-map__save-message"}>
            {saveMessage}
          </p>
        ) : null}

        <div className="hardware-map__flow-layout">
          <div className="hardware-map__canvas-shell">
            <ReactFlow
              edges={edges}
              fitView
              nodeTypes={nodeTypes}
              nodes={nodes}
              onConnect={handleConnect}
              onEdgesChange={onEdgesChange}
              onNodeClick={(event, node) => {
                event.stopPropagation();
                setSelectedNodeId(node.id);
              }}
              onNodesChange={onNodesChange}
              onPaneClick={() => setSelectedNodeId(RASPBERRY_NODE_ID)}
            >
              <MiniMap pannable zoomable />
              <Controls />
              <Background gap={24} size={1} />
            </ReactFlow>
          </div>

          <aside className="hardware-settings">
            <div className="hardware-settings__header">
              <span>{selectedKind}</span>
              <strong>
                {selectedBoard?.label ?? selectedDevice?.name ?? (selectedNodeId === RASPBERRY_NODE_ID ? "Raspberry Pi" : "Settings")}
              </strong>
            </div>
            {renderSettings()}
          </aside>
        </div>
      </div>
    </Panel>
  );
}

export function HardwareDiagramCard(props: HardwareDiagramCardProps) {
  return (
    <ReactFlowProvider>
      <HardwareDiagramSurface {...props} />
    </ReactFlowProvider>
  );
}
