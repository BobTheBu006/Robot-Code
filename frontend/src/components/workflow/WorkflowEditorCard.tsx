import type { DragEvent, PointerEvent as ReactPointerEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  addEdge,
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  SelectionMode,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeTypes,
  type Node,
  type NodeTypes,
} from "@xyflow/react";

import {
  cancelFunction,
  deleteEsp32CustomBlock,
  emergencyStop,
  fetchEsp32Boards,
  fetchFunctions,
  fetchHardwareMap,
  fetchSavedWorkflow,
  flashEsp32BoardFirmware,
  planWorkflowFirmware,
  saveEsp32CustomBlock,
  saveWorkflowToFile,
  testFunction,
} from "../../lib/api";
import {
  blockUsesUpstreamInput,
  WORKFLOW_BLOCK_MIME,
  createBuiltInBlocks,
  createDefaultParameters,
  createDefaultNodeSettings,
  createBrokenWorkflowBlock,
  createStarterWorkflow,
  createWorkflowNode,
  formatDurationShort,
  getAllBlockInputs,
  getWorkflowNodeOutputs,
  resolveWorkflowParameters,
  normalizeFailureMode,
  normalizeRetryCount,
  mapDiscoveredFunctionToBlock,
  runBuiltInBlockTest,
} from "../../lib/workflow";
import type {
  DiscoveredFunctionDefinition,
  FunctionTestResponse,
  FunctionDiscoveryError,
  WorkflowBlockDefinition,
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
  WorkflowExecutionStatus,
  WorkflowFailureMode,
  WorkflowFirmwareRequirement,
  WorkflowInputDefinition,
  WorkflowNodeData,
  WorkflowParameterValue,
  WorkflowOutputDefinition,
} from "../../types/workflow";
import type { Esp32CustomBlockSaveResponse, Esp32WorkflowFirmwarePlanRequestItem } from "../../types/esp32Builder";
import type { Esp32BoardSummary } from "../../types/esp32Builder";
import type { HardwareDeviceMapping, HardwareMap } from "../../types/hardwareMap";
import { WorkflowEdge } from "./WorkflowEdge";
import { WorkflowInspector } from "./WorkflowInspector";
import { WorkflowNode } from "./WorkflowNode";
import { WorkflowPalette } from "./WorkflowPalette";

type WorkflowFlowNode = Node<WorkflowNodeData>;
type NodeTestState = {
  status: WorkflowExecutionStatus;
  result: FunctionTestResponse | null;
  error: string | null;
};
type WorkflowRunState = {
  isRunning: boolean;
  phase: "idle" | "flashing" | "running";
  orderedNodeIds: string[];
  currentNodeId: string | null;
  completedNodeIds: string[];
  flashingBoardId: string | null;
};
type WorkflowContextMenuState = {
  x: number;
  y: number;
  nodeId: string;
} | null;
type WorkflowDrawerMode = "blocks" | null;
type QuickAddSource =
  | { kind: "port"; nodeId: string; outputKey: string }
  | { kind: "edge"; edgeId: string }
  | null;
type CompoundOutputBuild = WorkflowOutputDefinition & {
  sourceNodeId: string;
  sourceHandle?: string | null;
};
const RASPBERRY_BOARD_ID = "raspberry-pi";

function scheduleFitView(fitView: (options?: { padding?: number; duration?: number }) => void) {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => fitView({ padding: 0.2, duration: 300 }));
  });
}

function serializeWorkflowForDirtyCheck(nodes: WorkflowFlowNode[], edges: Edge[]): string {
  // Only compare fields the user can actually edit. `node.data.block` is
  // excluded because it gets re-resolved asynchronously (hardware device
  // links, disabled reasons) once function discovery / hardware map data
  // finishes loading, which would otherwise look like an edit that never happened.
  return JSON.stringify({
    nodes: nodes.map((node) => ({
      id: node.id,
      blockId: node.data.block.id,
      x: Math.round(node.position.x),
      y: Math.round(node.position.y),
      parameters: node.data.parameters,
      settings: node.data.settings,
      isActive: node.data.isActive !== false,
    })),
    edges: edges.map((edge) => ({
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle ?? null,
      targetHandle: edge.targetHandle ?? null,
    })),
  });
}

function isEditableKeyboardTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  const tagName = target.tagName.toLowerCase();
  return target.isContentEditable || tagName === "input" || tagName === "textarea" || tagName === "select";
}

function isEsp32WorkflowBoardId(boardId: string | null | undefined): boardId is string {
  return Boolean(boardId) && boardId !== RASPBERRY_BOARD_ID;
}

function isClientExecutedBlock(block: WorkflowBlockDefinition): boolean {
  return block.kind === "basic" || block.kind === "built-in" || block.kind === "compound" || block.kind === "broken";
}

function isAdvancedBlock(block: WorkflowBlockDefinition): boolean {
  return block.kind === "advanced" || block.kind === "robot-action";
}

function cleanNodeForCompound(node: WorkflowFlowNode, minX: number, minY: number): WorkflowFlowNode {
  const persistentData = { ...node.data };
  delete persistentData.executionStatus;
  delete persistentData.executionEtaMs;
  delete persistentData.onDelete;
  delete persistentData.onRun;
  delete persistentData.onCancel;
  delete persistentData.onToggleActive;

  return {
    ...node,
    selected: false,
    position: {
      x: node.position.x - minX,
      y: node.position.y - minY,
    },
    data: persistentData,
  };
}

function cleanEdgeForCompound(edge: Edge): WorkflowCanvasEdge {
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle,
    targetHandle: edge.targetHandle,
    type: edge.type,
    animated: edge.animated,
  };
}

function createExpandedCompoundNodes(
  compoundNode: WorkflowFlowNode,
  innerNodes: WorkflowFlowNode[],
): { nodes: WorkflowFlowNode[]; nodeIdMap: Map<string, string> } {
  const instanceKey = `${compoundNode.id}-${Date.now().toString(36)}`;
  const nodeIdMap = new Map<string, string>();
  const nodes = innerNodes.map((innerNode, index) => {
    const nextNodeId = `${innerNode.id}__expanded_${instanceKey}_${index}`;
    nodeIdMap.set(innerNode.id, nextNodeId);

    return {
      ...innerNode,
      id: nextNodeId,
      selected: true,
      position: {
        x: compoundNode.position.x + innerNode.position.x,
        y: compoundNode.position.y + innerNode.position.y,
      },
      data: {
        ...innerNode.data,
        executionStatus: "idle" as WorkflowExecutionStatus,
        executionEtaMs: null,
      },
    };
  });

  return { nodes, nodeIdMap };
}

function cloneNodesForPaste(
  sourceNodes: WorkflowFlowNode[],
  sourceEdges: Edge[],
  offset: number,
): { nodes: WorkflowFlowNode[]; edges: Edge[] } {
  const key = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  const nodeIdMap = new Map<string, string>();
  const nodes = sourceNodes.map((node, index) => {
    const nextId = `${node.data.block.id}-copy-${key}-${index}`;
    nodeIdMap.set(node.id, nextId);
    return {
      ...node,
      id: nextId,
      selected: true,
      dragging: false,
      position: {
        x: node.position.x + offset,
        y: node.position.y + offset,
      },
      data: {
        ...node.data,
        parameters: { ...node.data.parameters },
        settings: { ...node.data.settings },
        executionStatus: "idle" as WorkflowExecutionStatus,
        executionEtaMs: null,
      },
    };
  });
  const edges = sourceEdges
    .filter((edge) => nodeIdMap.has(edge.source) && nodeIdMap.has(edge.target))
    .map((edge, index) => ({
      ...edge,
      id: `edge-copy-${key}-${index}`,
      source: nodeIdMap.get(edge.source) as string,
      target: nodeIdMap.get(edge.target) as string,
      selected: false,
    }));
  return { nodes, edges };
}

function createExpandedEdgeId(prefix: string, compoundNodeId: string, edgeId: string, index: number): string {
  return `${prefix}-${compoundNodeId}-${edgeId}-${index}-${Date.now().toString(36)}`;
}

function buildCompoundOutputKey(node: WorkflowFlowNode, outputKey: string, usedKeys: Set<string>): string {
  const normalizedNodeId = node.id
    .replace(/^[^a-zA-Z]+/, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
  const normalizedOutput = outputKey.replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase() || "next";
  const preferredKey = usedKeys.size === 0 ? normalizedOutput : `${normalizedNodeId || "node"}_${normalizedOutput}`;
  let key = preferredKey;
  let suffix = 2;

  while (usedKeys.has(key)) {
    key = `${preferredKey}_${suffix}`;
    suffix += 1;
  }

  return key;
}

function buildCompoundOutputsFromGraph(
  compoundNodes: WorkflowFlowNode[],
  compoundEdges: Edge[],
): CompoundOutputBuild[] {
  const usedKeys = new Set<string>();
  const internalSourceHandles = new Set(
    compoundEdges.map((edge) => `${edge.source}:${edge.sourceHandle ?? "next"}`),
  );
  const outputs: CompoundOutputBuild[] = [];

  for (const node of compoundNodes) {
    const unconnectedOutputs = getWorkflowNodeOutputs(node.data)
      .filter((output) => output.key !== "error")
      .filter((output) => !internalSourceHandles.has(`${node.id}:${output.key}`));

    for (const output of unconnectedOutputs) {
      const key = buildCompoundOutputKey(node, output.key, usedKeys);
      usedKeys.add(key);
      outputs.push({
        key,
        label: outputs.length === 0 ? output.label : `${node.data.block.displayName} ${output.label}`,
        type: "flow",
        description: output.description ?? `Output from ${node.data.block.displayName}.`,
        sourceNodeId: node.id,
        sourceHandle: output.key,
      });
    }
  }

  if (outputs.length > 0) {
    return outputs;
  }

  const fallbackNode = compoundNodes[compoundNodes.length - 1];
  return [{
    key: "next",
    label: "Next",
    type: "flow",
    description: "Continue when the compound function completes.",
    sourceNodeId: fallbackNode?.id ?? "",
    sourceHandle: "next",
  }];
}

function findCompoundEntryNodeId(
  compoundNodes: WorkflowFlowNode[],
  compoundEdges: Edge[],
  preferredEntryNodeId?: string,
): string {
  if (preferredEntryNodeId && compoundNodes.some((node) => node.id === preferredEntryNodeId)) {
    return preferredEntryNodeId;
  }

  const targetNodeIds = new Set(compoundEdges.map((edge) => edge.target));
  return compoundNodes.find((node) => !targetNodeIds.has(node.id))?.id ?? compoundNodes[0]?.id ?? "";
}

function extractCompoundBlocksFromNodes(workflowNodes: WorkflowFlowNode[]): WorkflowBlockDefinition[] {
  const compoundBlocksById = new Map<string, WorkflowBlockDefinition>();

  for (const node of workflowNodes) {
    if (node.data.block.kind === "compound") {
      compoundBlocksById.set(node.data.block.id, node.data.block);
    }
  }

  return [...compoundBlocksById.values()];
}

function normalizeWorkflowNodes(nodesToNormalize: WorkflowFlowNode[]): WorkflowFlowNode[] {
  return nodesToNormalize.map((node) => ({
    ...node,
    data: {
      ...node.data,
      isActive: node.data.isActive !== false,
      settings: {
        ...createDefaultNodeSettings(),
        ...(node.data.settings ?? {}),
        failureMode: normalizeFailureMode(node.data.settings?.failureMode),
        retryCount: normalizeRetryCount(node.data.settings?.retryCount),
      },
      runCount: typeof node.data.runCount === "number" ? node.data.runCount : 0,
      benchmarkDurationMs:
        typeof node.data.benchmarkDurationMs === "number" ? node.data.benchmarkDurationMs : null,
      lastDurationMs:
        typeof node.data.lastDurationMs === "number" ? node.data.lastDurationMs : null,
    },
  }));
}

function mergeParametersForBlock(
  block: WorkflowBlockDefinition,
  currentParameters: Record<string, WorkflowParameterValue>,
): Record<string, WorkflowParameterValue> {
  const inputs = getAllBlockInputs(block);
  const nextParameters = {
    ...createDefaultParameters(inputs),
    ...currentParameters,
  };

  for (const input of inputs) {
    if (input.type !== "select" || input.options.length === 0) {
      continue;
    }

    const currentValue = String(nextParameters[input.key] ?? "");
    if (!input.options.some((option) => option.value === currentValue)) {
      nextParameters[input.key] = input.default ?? input.options[0]?.value ?? "";
    }
  }

  return nextParameters;
}

function getBoardIdForBlock(block: WorkflowBlockDefinition, hardwareMap: HardwareMap | null): string | null {
  const hardwareDeviceIds = new Set((block.hardwareDevices ?? []).map((device) => device.id));
  if (block.hardwareDeviceId) {
    hardwareDeviceIds.add(block.hardwareDeviceId);
  }

  const mappedBoardIds = new Set<string>();
  for (const deviceId of hardwareDeviceIds) {
    const mappedDevice = hardwareMap?.devices.find((device) => device.id === deviceId);
    if (mappedDevice?.board_id) {
      mappedBoardIds.add(mappedDevice.board_id);
      continue;
    }

    const blockDevice = block.hardwareDevices?.find((device) => device.id === deviceId);
    if (blockDevice?.board_id) {
      mappedBoardIds.add(blockDevice.board_id);
    }
  }

  if (mappedBoardIds.size === 1) {
    return Array.from(mappedBoardIds)[0];
  }

  if (mappedBoardIds.size > 1) {
    return null;
  }

  return block.hardwareBoardId ?? block.builderBoardId ?? null;
}

function isHardwareEnabled(item: { enabled?: boolean } | null | undefined): boolean {
  return item?.enabled !== false;
}

function getHardwareDependencyDeviceIds(block: WorkflowBlockDefinition): string[] {
  const deviceIds = new Set((block.hardwareDevices ?? []).map((device) => device.id));
  if (block.hardwareDeviceId) {
    deviceIds.add(block.hardwareDeviceId);
  }

  for (const innerNode of block.compound?.nodes ?? []) {
    getHardwareDependencyDeviceIds(innerNode.data.block).forEach((deviceId) => deviceIds.add(deviceId));
  }

  return Array.from(deviceIds);
}

function getDisabledGroupForDevice(
  hardwareMap: HardwareMap,
  device: HardwareDeviceMapping,
) {
  return (hardwareMap.groups ?? []).find((group) =>
    !isHardwareEnabled(group)
    && (group.member_ids.includes(device.id) || (!!device.board_id && group.member_ids.includes(device.board_id))),
  ) ?? null;
}

function isHardwareDeviceEnabled(hardwareMap: HardwareMap, device: HardwareDeviceMapping): boolean {
  if (!isHardwareEnabled(device) || getDisabledGroupForDevice(hardwareMap, device)) {
    return false;
  }

  if (device.board_id && device.board_id !== RASPBERRY_BOARD_ID) {
    const board = hardwareMap.boards.find((candidate) => candidate.id === device.board_id);
    return isHardwareEnabled(board);
  }

  return true;
}

function getDisabledHardwareReason(block: WorkflowBlockDefinition, hardwareMap: HardwareMap | null): string | null {
  if (!hardwareMap) {
    return null;
  }

  const dependencyDeviceIds = getHardwareDependencyDeviceIds(block);
  for (const deviceId of dependencyDeviceIds) {
    const device = hardwareMap.devices.find((candidate) => candidate.id === deviceId);
    if (!device) {
      continue;
    }

    if (!isHardwareEnabled(device)) {
      return `${device.name} is disabled in the Hardware Map.`;
    }

    const disabledGroup = getDisabledGroupForDevice(hardwareMap, device);
    if (disabledGroup) {
      return `${device.name} is inside disabled hardware group ${disabledGroup.name}.`;
    }

    if (device.board_id && device.board_id !== RASPBERRY_BOARD_ID) {
      const board = hardwareMap.boards.find((candidate) => candidate.id === device.board_id);
      if (board && !isHardwareEnabled(board)) {
        return `${device.name} is connected to disabled controller ${board.label}.`;
      }
    }
  }

  const boardId = dependencyDeviceIds.length === 0 ? block.hardwareBoardId ?? block.builderBoardId ?? null : null;
  if (boardId && boardId !== RASPBERRY_BOARD_ID) {
    const board = hardwareMap.boards.find((candidate) => candidate.id === boardId);
    if (board && !isHardwareEnabled(board)) {
      return `${board.label} is disabled in the Hardware Map.`;
    }
  }

  return null;
}

function getHardwareMapPortForBlock(block: WorkflowBlockDefinition, hardwareMap: HardwareMap | null): string | null {
  const boardId = getBoardIdForBlock(block, hardwareMap);
  if (!boardId || boardId === RASPBERRY_BOARD_ID) {
    return null;
  }

  return hardwareMap?.boards.find((board) => board.id === boardId)?.usb_port ?? null;
}

function getHardwareMapPinParameters(hardwareMap: HardwareMap | null): Record<string, WorkflowParameterValue> {
  const pinParameters: Record<string, WorkflowParameterValue> = {};

  for (const device of hardwareMap?.devices ?? []) {
    if (hardwareMap && !isHardwareDeviceEnabled(hardwareMap, device)) {
      continue;
    }

    for (const pin of device.pins) {
      if (!pin.function_input_key || pin.gpio === "-" || pin.signal === "-") {
        continue;
      }

      pinParameters[pin.function_input_key] = pin.gpio;
    }
  }

  return pinParameters;
}

function resolveHardwareMapParameters(
  block: WorkflowBlockDefinition,
  parameters: Record<string, WorkflowParameterValue>,
  hardwareMap: HardwareMap | null,
): Record<string, WorkflowParameterValue> {
  const inputs = getAllBlockInputs(block);
  const shouldResolveToolPort = inputs.some((input) => input.key === "tool_port");
  const pinInputKeys = inputs
    .filter((input) => input.key.includes("pin"))
    .map((input) => input.key);
  const pinParameters = getHardwareMapPinParameters(hardwareMap);
  const resolvedParameters = { ...parameters };

  if (shouldResolveToolPort) {
    const toolPort = getHardwareMapPortForBlock(block, hardwareMap);
    if (toolPort) {
      resolvedParameters.tool_port = toolPort;
    }
  }

  for (const inputKey of pinInputKeys) {
    if (pinParameters[inputKey] !== undefined) {
      resolvedParameters[inputKey] = pinParameters[inputKey];
    }
  }

  return resolvedParameters;
}

const nodeTypes: NodeTypes = {
  workflowBlock: WorkflowNode,
};

const edgeTypes: EdgeTypes = {
  workflowEdge: WorkflowEdge,
};

function useControlKeyPressed(): boolean {
  const [isPressed, setIsPressed] = useState(false);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Control") {
        setIsPressed(true);
      }
    };
    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.key === "Control") {
        setIsPressed(false);
      }
    };
    const handleBlur = () => setIsPressed(false);

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    window.addEventListener("blur", handleBlur);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
      window.removeEventListener("blur", handleBlur);
    };
  }, []);

  return isPressed;
}

function shouldIgnoreControlDragPan(target: EventTarget | null): boolean {
  return target instanceof HTMLElement
    && Boolean(target.closest(".react-flow__controls, .react-flow__minimap, input, textarea, select, button, a"));
}

function useControlDragPan() {
  const reactFlow = useReactFlow();

  return useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (!event.ctrlKey || event.button !== 0 || shouldIgnoreControlDragPan(event.target)) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();

    const startX = event.clientX;
    const startY = event.clientY;
    const startViewport = reactFlow.getViewport();

    const handlePointerMove = (moveEvent: PointerEvent) => {
      moveEvent.preventDefault();
      reactFlow.setViewport(
        {
          x: startViewport.x + moveEvent.clientX - startX,
          y: startViewport.y + moveEvent.clientY - startY,
          zoom: startViewport.zoom,
        },
        { duration: 0 },
      );
    };

    const handlePointerUp = () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };

    window.addEventListener("pointermove", handlePointerMove, { passive: false });
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);
  }, [reactFlow]);
}

interface CompoundFunctionEditorProps {
  node: WorkflowFlowNode;
  testStateByNodeId: Record<string, NodeTestState>;
  onClose: () => void;
  onSave: (nodeId: string, innerNodes: WorkflowFlowNode[], innerEdges: Edge[]) => void;
  onRunNode: (node: WorkflowFlowNode) => void;
  onCancelNode: (node: WorkflowFlowNode) => void;
  onSaveCustomBlock: (node: WorkflowFlowNode, displayName: string) => Promise<Esp32CustomBlockSaveResponse>;
}

function CompoundFunctionEditor({
  node,
  testStateByNodeId,
  onClose,
  onSave,
  onRunNode,
  onCancelNode,
  onSaveCustomBlock,
}: CompoundFunctionEditorProps) {
  const controlKeyPressed = useControlKeyPressed();
  const handleControlDragPan = useControlDragPan();
  const compound = node.data.block.compound;
  const initialNodes = useMemo(
    () => normalizeWorkflowNodes((compound?.nodes ?? []) as WorkflowFlowNode[]),
    [compound],
  );
  const initialEdges = useMemo(
    () => (compound?.edges ?? []) as Edge[],
    [compound],
  );
  const [editorNodes, setEditorNodes, onEditorNodesChange] = useNodesState<WorkflowFlowNode>(initialNodes);
  const [editorEdges, setEditorEdges, onEditorEdgesChange] = useEdgesState<Edge>(initialEdges);
  const [openedInnerNodeId, setOpenedInnerNodeId] = useState<string | null>(null);
  const openedInnerNode = editorNodes.find((innerNode) => innerNode.id === openedInnerNodeId) ?? null;
  const openedInnerNodeTestState = openedInnerNodeId
    ? testStateByNodeId[openedInnerNodeId] ?? { status: "idle" as const, result: null, error: null }
    : { status: "idle" as const, result: null, error: null };
  const previousInnerNode = openedInnerNode
    ? editorNodes.find((innerNode) => innerNode.id === editorEdges.find((edge) => edge.target === openedInnerNode.id)?.source) ?? null
    : null;
  const previousInnerNodeTestState = previousInnerNode
    ? testStateByNodeId[previousInnerNode.id] ?? { status: "idle" as const, result: null, error: null }
    : { status: "idle" as const, result: null, error: null };
  const projectedOutputs = buildCompoundOutputsFromGraph(editorNodes, editorEdges);

  function handleEditorConnect(connection: Connection) {
    setEditorEdges((currentEdges) =>
      addEdge(
        {
          ...connection,
          type: "workflowEdge",
        },
        currentEdges,
      ),
    );
  }

  function handleDeleteInnerNode(nodeId: string) {
    setEditorNodes((currentNodes) => currentNodes.filter((innerNode) => innerNode.id !== nodeId));
    setEditorEdges((currentEdges) =>
      currentEdges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId),
    );
  }

  function handleToggleInnerNodeActive(nodeId: string) {
    setEditorNodes((currentNodes) =>
      currentNodes.map((innerNode) =>
        innerNode.id === nodeId
          ? {
              ...innerNode,
              data: {
                ...innerNode.data,
                isActive: innerNode.data.isActive === false,
              },
            }
          : innerNode,
      ),
    );
  }

  function handleUpdateInnerParameter(
    nodeId: string,
    input: WorkflowInputDefinition,
    value: WorkflowParameterValue,
  ) {
    setEditorNodes((currentNodes) =>
      currentNodes.map((innerNode) =>
        innerNode.id === nodeId
          ? {
              ...innerNode,
              data: {
                ...innerNode.data,
                parameters: {
                  ...innerNode.data.parameters,
                  [input.key]: value,
                },
              },
            }
          : innerNode,
      ),
    );
  }

  function handleUpdateInnerSettings(
    nodeId: string,
    updates: Partial<{ failureMode: WorkflowFailureMode; retryCount: number }>,
  ) {
    setEditorNodes((currentNodes) =>
      currentNodes.map((innerNode) => {
        if (innerNode.id !== nodeId) {
          return innerNode;
        }

        return {
          ...innerNode,
          data: {
            ...innerNode.data,
            settings: {
              ...innerNode.data.settings,
              failureMode: updates.failureMode
                ? normalizeFailureMode(updates.failureMode)
                : innerNode.data.settings.failureMode,
              retryCount: updates.retryCount !== undefined
                ? normalizeRetryCount(updates.retryCount)
                : innerNode.data.settings.retryCount,
            },
          },
        };
      }),
    );

    if (updates.failureMode === "stop_flow") {
      setEditorEdges((currentEdges) =>
        currentEdges.filter((edge) => !(edge.source === nodeId && edge.sourceHandle === "error")),
      );
    }
  }

  const renderedEditorNodes = editorNodes.map((innerNode) => ({
    ...innerNode,
    data: {
      ...innerNode.data,
      executionStatus: testStateByNodeId[innerNode.id]?.status ?? ("idle" as WorkflowExecutionStatus),
      executionEtaMs: null,
      onDelete: () => handleDeleteInnerNode(innerNode.id),
      onToggleActive: () => handleToggleInnerNodeActive(innerNode.id),
      onRun: () => onRunNode(innerNode),
      onCancel: () => onCancelNode(innerNode),
    },
  }));
  const renderedEditorEdges = editorEdges.map((edge) => ({
    ...edge,
    data: {
      ...(edge.data ?? {}),
      onDelete: (edgeId: string) =>
        setEditorEdges((currentEdges) => currentEdges.filter((currentEdge) => currentEdge.id !== edgeId)),
    },
  }));

  if (!compound) {
    return null;
  }

  return (
    <div className="workflow-compound-editor">
      <div className="workflow-compound-editor__shell">
        <header className="workflow-compound-editor__header">
          <div>
            <span>Compound editor</span>
            <strong>{node.data.block.displayName}</strong>
          </div>
          <div className="workflow-compound-editor__actions">
            <button className="workflow-editor__action" onClick={onClose} type="button">
              Close
            </button>
            <button
              className="workflow-editor__action workflow-editor__action--primary"
              onClick={() => onSave(node.id, editorNodes, editorEdges)}
              type="button"
            >
              Save compound
            </button>
          </div>
        </header>

        <div className="workflow-compound-editor__layout">
          <div className="workflow-compound-editor__canvas">
            <ReactFlow
              edges={renderedEditorEdges}
              edgeTypes={edgeTypes}
              fitView
              nodeTypes={nodeTypes}
              nodes={renderedEditorNodes}
              onConnect={handleEditorConnect}
              onEdgesChange={onEditorEdgesChange}
              onNodeClick={(event, innerNode) => {
                event.stopPropagation();
                setOpenedInnerNodeId(null);
              }}
              onNodeDoubleClick={(event, innerNode) => {
                event.stopPropagation();
                setOpenedInnerNodeId(innerNode.id);
              }}
              onNodesChange={onEditorNodesChange}
              onPointerDownCapture={handleControlDragPan}
              onPaneClick={() => {
                setOpenedInnerNodeId(null);
              }}
              nodesDraggable={!controlKeyPressed}
              panActivationKeyCode="Control"
              panOnDrag={false}
              selectionMode={SelectionMode.Partial}
              selectionOnDrag
            >
              <MiniMap pannable zoomable />
              <Controls />
              <Background gap={24} size={1} />
            </ReactFlow>

            {openedInnerNode ? (
              <WorkflowInspector
                allNodeTestEntries={editorNodes.map((innerNode) => ({
                  nodeId: innerNode.id,
                  nodeName: innerNode.data.block.displayName,
                  status: testStateByNodeId[innerNode.id]?.status ?? "idle",
                  result: testStateByNodeId[innerNode.id]?.result ?? null,
                  error: testStateByNodeId[innerNode.id]?.error ?? null,
                }))}
                edges={editorEdges}
                nodes={editorNodes}
                onClose={() => setOpenedInnerNodeId(null)}
                onNavigateToNode={(nodeId) => {
                  setOpenedInnerNodeId(nodeId);
                }}
                onCancel={() => onCancelNode(openedInnerNode)}
                onEditCompound={() => {}}
                onRunTest={() => onRunNode(openedInnerNode)}
                onRunNode={(nodeId) => {
                  const innerNode = editorNodes.find((candidate) => candidate.id === nodeId);
                  if (innerNode) {
                    onRunNode(innerNode);
                  }
                }}
                onSaveCustomBlock={(displayName) => onSaveCustomBlock(openedInnerNode, displayName)}
                onUpdateParameter={handleUpdateInnerParameter}
                onUpdateSettings={handleUpdateInnerSettings}
                previousNodeTestError={previousInnerNodeTestState.error}
                previousNodeTestResult={previousInnerNodeTestState.result}
                previousNodeTestStatus={previousInnerNodeTestState.status}
                selectedNode={openedInnerNode}
                testError={openedInnerNodeTestState.error}
                testResult={openedInnerNodeTestState.result}
                testStatus={openedInnerNodeTestState.status}
              />
            ) : null}
          </div>

          <aside className="workflow-compound-editor__panel">
            <section>
              <h4>Compound outputs</h4>
              <p>Unconnected internal outputs become external compound outputs. Error paths are ignored.</p>
              <div className="workflow-compound-editor__output-list">
                {projectedOutputs.map((output) => (
                  <span key={output.key}>{output.label}</span>
                ))}
              </div>
            </section>

            <p className="workflow-compound-editor__empty">Double-click a block to open and edit it, exactly like on the main canvas.</p>
          </aside>
        </div>
      </div>
    </div>
  );
}

interface WorkflowEditorSurfaceProps {
  hardwareMapRevision: number;
  headerSlot: HTMLElement | null;
  isActive: boolean;
}

function WorkflowEditorSurface({ hardwareMapRevision, headerSlot, isActive }: WorkflowEditorSurfaceProps) {
  const controlKeyPressed = useControlKeyPressed();
  const handleControlDragPan = useControlDragPan();
  const starterWorkflow = useMemo(() => createStarterWorkflow(), []);
  const builtInBlocks = useMemo(() => createBuiltInBlocks(), []);
  const [nodes, setNodes, onNodesChange] = useNodesState<WorkflowFlowNode>(starterWorkflow.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(starterWorkflow.edges);
  const [discoveredFunctions, setDiscoveredFunctions] = useState<DiscoveredFunctionDefinition[]>([]);
  const [esp32Boards, setEsp32Boards] = useState<Esp32BoardSummary[]>([]);
  const [hardwareMap, setHardwareMap] = useState<HardwareMap | null>(null);
  const [discoveryErrors, setDiscoveryErrors] = useState<FunctionDiscoveryError[]>([]);
  const [functionsStatus, setFunctionsStatus] = useState<"loading" | "success" | "error">("loading");
  const [functionsError, setFunctionsError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [openedNodeId, setOpenedNodeId] = useState<string | null>(null);
  const [activeEdgeId, setActiveEdgeId] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<WorkflowContextMenuState>(null);
  const [compoundCounter, setCompoundCounter] = useState(1);
  const [compoundBlocks, setCompoundBlocks] = useState<WorkflowBlockDefinition[]>([]);
  const [editingCompoundNodeId, setEditingCompoundNodeId] = useState<string | null>(null);
  const [testStateByNodeId, setTestStateByNodeId] = useState<Record<string, NodeTestState>>({});
  const testStateByNodeIdRef = useRef<Record<string, NodeTestState>>({});
  const testAbortControllersRef = useRef<Record<string, AbortController>>({});
  const flashAbortControllerRef = useRef<AbortController | null>(null);
  const clipboardRef = useRef<{ nodes: WorkflowFlowNode[]; edges: Edge[] } | null>(null);
  const lastValidSpeedByNodeIdRef = useRef<Record<string, number>>({});
  const [saveAsPath] = useState("");
  const [saveAsName] = useState("active-workflow");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const saveResetTimeoutRef = useRef<number | null>(null);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const savedWorkflowSnapshotRef = useRef<string | null>(null);
  const [skipEsp32Flashing, setSkipEsp32Flashing] = useState(false);
  const [workflowDrawer, setWorkflowDrawer] = useState<WorkflowDrawerMode>(null);
  const [quickAddSource, setQuickAddSource] = useState<QuickAddSource>(null);
  const [workflowRunState, setWorkflowRunState] = useState<WorkflowRunState>({
    isRunning: false,
    phase: "idle",
    orderedNodeIds: [],
    currentNodeId: null,
    completedNodeIds: [],
    flashingBoardId: null,
  });
  const workflowResultsRef = useRef<Map<string, FunctionTestResponse>>(new Map());
  const reactFlow = useReactFlow<WorkflowFlowNode, Edge>();
  const nodeLookup = new Map(nodes.map((node) => [node.id, node]));

  function updateTestState(
    updater: (currentState: Record<string, NodeTestState>) => Record<string, NodeTestState>,
  ) {
    setTestStateByNodeId((currentState) => {
      const nextState = updater(currentState);
      testStateByNodeIdRef.current = nextState;
      return nextState;
    });
  }

  function buildBlockResultLookup(
    overrides: Record<string, Record<string, unknown> | null | undefined> = {},
  ): Record<string, Record<string, unknown> | null | undefined> {
    return {
      ...Object.fromEntries(
        Object.entries(testStateByNodeIdRef.current).map(([nodeId, state]) => [
          nodeId,
          state.result?.result ?? null,
        ]),
      ),
      ...overrides,
    };
  }

  function estimateNodeDuration(node: WorkflowFlowNode): number {
    if (typeof node.data.benchmarkDurationMs === "number" && node.data.benchmarkDurationMs > 0) {
      return node.data.benchmarkDurationMs;
    }

    if (node.data.block.id === "delay") {
      const durationMs = Number(node.data.parameters.duration_ms ?? 0);
      return Number.isFinite(durationMs) && durationMs > 0 ? durationMs : 1000;
    }

    return 1000;
  }

  function getNodeExecutionEta(nodeId: string): number | null {
    const node = nodeLookup.get(nodeId);
    if (!node) {
      return null;
    }

    return estimateNodeDuration(node);
  }

  const renderedNodes = nodes.map((node) => {
    const disabledReason = getDisabledHardwareReason(node.data.block, hardwareMap);
    return {
      ...node,
      data: {
        ...node.data,
        block: {
          ...node.data.block,
          disabledReason,
        },
        executionStatus: testStateByNodeId[node.id]?.status ?? "idle",
        executionEtaMs: getNodeExecutionEta(node.id),
        onDelete: () => handleDeleteNode(node.id),
        onRun: () => void handleRunTestForNode(node.id),
        onCancel: () => void handleCancelNodeExecution(node.id),
        onToggleActive: () => handleToggleNodeActive(node.id),
        onQuickAdd: (outputKey: string) => handleQuickAddFromPort(node.id, outputKey),
      },
    };
  });
  const renderedEdges = edges.map((edge) => ({
    ...edge,
    data: {
      ...(edge.data ?? {}),
      isActive: edge.id === activeEdgeId,
      onDelete: handleDeleteEdge,
      onInsert: handleQuickAddFromEdge,
    },
  }));

  async function loadFunctions(cancellationToken?: { cancelled: boolean }) {
    try {
      const response = await fetchFunctions();
      if (cancellationToken?.cancelled) {
        return;
      }

      setDiscoveredFunctions(response.functions);
      setDiscoveryErrors(response.errors);
      setFunctionsStatus("success");
      setFunctionsError(null);
    } catch (error) {
      if (cancellationToken?.cancelled) {
        return;
      }

      setFunctionsStatus("error");
      setFunctionsError(error instanceof Error ? error.message : "Could not load robot functions.");
    }
  }

  async function loadBoards(cancellationToken?: { cancelled: boolean }) {
    try {
      const response = await fetchEsp32Boards();
      if (cancellationToken?.cancelled) {
        return;
      }

      setEsp32Boards(response.boards);
    } catch (error) {
      if (cancellationToken?.cancelled) {
        return;
      }

      setFunctionsError(error instanceof Error ? error.message : "Could not load connected ESP32 boards.");
    }
  }

  async function loadHardwareMap(cancellationToken?: { cancelled: boolean }) {
    try {
      const response = await fetchHardwareMap();
      if (cancellationToken?.cancelled) {
        return;
      }

      setHardwareMap(response);
    } catch (error) {
      if (cancellationToken?.cancelled) {
        return;
      }

      setFunctionsError(error instanceof Error ? error.message : "Could not load hardware map.");
    }
  }

  useEffect(() => {
    const cancellationToken = { cancelled: false };
    void loadFunctions(cancellationToken);
    void loadBoards(cancellationToken);
    void loadHardwareMap(cancellationToken);

    return () => {
      cancellationToken.cancelled = true;
    };
  }, []);

  useEffect(() => {
    const cancellationToken = { cancelled: false };
    void loadHardwareMap(cancellationToken);

    return () => {
      cancellationToken.cancelled = true;
    };
  }, [hardwareMapRevision]);

  useEffect(() => {
    const handleEmergencyStop = () => {
      flashAbortControllerRef.current?.abort();
      flashAbortControllerRef.current = null;
      Object.values(testAbortControllersRef.current).forEach((controller) => controller.abort());
      testAbortControllersRef.current = {};
      setWorkflowRunState((currentState) => ({
        ...currentState,
        isRunning: false,
        phase: "idle",
        currentNodeId: null,
        flashingBoardId: null,
      }));
      setTestStateByNodeId((currentState) =>
        Object.fromEntries(
          Object.entries(currentState).map(([nodeId, state]) => [
            nodeId,
            state.status === "running"
              ? {
                  status: "error",
                  result: state.result,
                  error: "Stopped by E-Stop.",
                }
              : state,
          ]),
        ),
      );
    };
    const handleEmergencyResume = () => {
      void resumeStoppedWorkflowRun();
    };

    window.addEventListener("robot-emergency-stop", handleEmergencyStop);
    window.addEventListener("robot-emergency-resume", handleEmergencyResume);
    return () => {
      window.removeEventListener("robot-emergency-stop", handleEmergencyStop);
      window.removeEventListener("robot-emergency-resume", handleEmergencyResume);
    };
  });

  useEffect(() => {
    testStateByNodeIdRef.current = testStateByNodeId;
  }, [testStateByNodeId]);

  useEffect(() => {
    let cancelled = false;

    async function loadSavedWorkflowFile() {
      try {
        const savedWorkflow = await fetchSavedWorkflow();
        if (cancelled) {
          return;
        }

        const parsedNodes = normalizeWorkflowNodes((savedWorkflow.workflow.nodes ?? []) as WorkflowFlowNode[]);
        const parsedEdges = (savedWorkflow.workflow.edges ?? []) as Edge[];
        setNodes(parsedNodes);
        setEdges(parsedEdges);
        setCompoundBlocks(extractCompoundBlocksFromNodes(parsedNodes));
        scheduleFitView(reactFlow.fitView);
        savedWorkflowSnapshotRef.current = serializeWorkflowForDirtyCheck(parsedNodes, parsedEdges);
        setHasUnsavedChanges(false);
      } catch (error) {
        if (cancelled) {
          return;
        }

        const status = (error as Error & { status?: number }).status;
        if (status === 404) {
          // No workflow has ever been saved yet: treat the starter workflow as the clean baseline.
          savedWorkflowSnapshotRef.current = serializeWorkflowForDirtyCheck(starterWorkflow.nodes, starterWorkflow.edges);
          return;
        }

        setFunctionsError(error instanceof Error ? error.message : "Could not load saved workflow file.");
      }
    }

    void loadSavedWorkflowFile();

    return () => {
      cancelled = true;
    };
  }, [setEdges, setNodes, starterWorkflow]);

  useEffect(() => {
    if (savedWorkflowSnapshotRef.current === null) {
      return;
    }

    const currentSnapshot = serializeWorkflowForDirtyCheck(nodes, edges);
    setHasUnsavedChanges(currentSnapshot !== savedWorkflowSnapshotRef.current);
  }, [nodes, edges]);

  useEffect(() => {
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      if (!hasUnsavedChanges) {
        return;
      }

      event.preventDefault();
      event.returnValue = "";
    }

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasUnsavedChanges]);

  const robotActionBlocks = useMemo(
    () => discoveredFunctions.map((discoveredFunction) =>
      mapDiscoveredFunctionToBlock(discoveredFunction, esp32Boards, hardwareMap),
    ),
    [discoveredFunctions, esp32Boards, hardwareMap],
  );
  const availableBlocks = useMemo(
    () => [...builtInBlocks, ...robotActionBlocks, ...compoundBlocks],
    [builtInBlocks, robotActionBlocks, compoundBlocks],
  );
  const openedNode = nodes.find((node) => node.id === openedNodeId) ?? null;
  const editingCompoundNode = nodes.find((node) => node.id === editingCompoundNodeId) ?? null;
  const openedNodeTestState = openedNodeId
    ? testStateByNodeId[openedNodeId] ?? { status: "idle", result: null, error: null }
    : { status: "idle" as const, result: null, error: null };
  const previousOpenedNode = openedNode
    ? nodes.find((node) => node.id === edges.find((edge) => edge.target === openedNode.id)?.source) ?? null
    : null;
  const previousOpenedNodeTestState = previousOpenedNode
    ? testStateByNodeId[previousOpenedNode.id] ?? { status: "idle", result: null, error: null }
    : { status: "idle" as const, result: null, error: null };
  useEffect(() => {
    if (functionsStatus !== "success" || !hardwareMap) {
      return;
    }

    const blockLookup = new Map(availableBlocks.map((block) => [block.id, block]));
    setNodes((currentNodes) =>
      currentNodes.map((node) => {
        const originalBlockId = node.data.block.missingReference?.originalId ?? node.data.block.id;
        const latestBlock = blockLookup.get(originalBlockId);
        if (!latestBlock) {
          if (node.data.block.kind === "broken" || node.data.block.kind === "compound") {
            return node;
          }

          return {
            ...node,
            data: {
              ...node.data,
              block: createBrokenWorkflowBlock(node.data.block),
            },
          };
        }

        return {
          ...node,
          data: {
            ...node.data,
            block: latestBlock,
            parameters: mergeParametersForBlock(latestBlock, node.data.parameters),
          },
        };
      }),
    );
  }, [availableBlocks, functionsStatus, hardwareMap, setNodes]);

  useEffect(() => {
    if (selectedNodeId && !nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(null);
    }
  }, [nodes, selectedNodeId]);

  useEffect(() => {
    if (openedNodeId && !nodes.some((node) => node.id === openedNodeId)) {
      setOpenedNodeId(null);
    }
  }, [nodes, openedNodeId]);

  function handleConnect(connection: Connection) {
    setEdges((existingEdges) =>
      addEdge(
        {
          ...connection,
          type: "workflowEdge",
        },
        existingEdges,
      ),
    );
  }

  function handleDeleteEdge(edgeId: string) {
    setEdges((existingEdges) => existingEdges.filter((edge) => edge.id !== edgeId));
    setActiveEdgeId((currentEdgeId) => (currentEdgeId === edgeId ? null : currentEdgeId));
  }

  function handleDeleteNode(nodeId: string) {
    testAbortControllersRef.current[nodeId]?.abort();
    delete testAbortControllersRef.current[nodeId];
    setNodes((currentNodes) => currentNodes.filter((node) => node.id !== nodeId));
    setEdges((existingEdges) =>
      existingEdges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId),
    );
    setSelectedNodeId((currentNodeId) => (currentNodeId === nodeId ? null : currentNodeId));
    setOpenedNodeId((currentNodeId) => (currentNodeId === nodeId ? null : currentNodeId));
    setActiveEdgeId(null);
    updateTestState((currentState) => {
      const nextState = { ...currentState };
      delete nextState[nodeId];
      return nextState;
    });
  }

  function handleDeleteSelectedNodes() {
    const selectedIds = new Set(nodes.filter((node) => node.selected).map((node) => node.id));
    if (selectedNodeId) {
      selectedIds.add(selectedNodeId);
    }

    if (selectedIds.size === 0) {
      return false;
    }

    for (const nodeId of selectedIds) {
      testAbortControllersRef.current[nodeId]?.abort();
      delete testAbortControllersRef.current[nodeId];
    }

    setNodes((currentNodes) => currentNodes.filter((node) => !selectedIds.has(node.id)));
    setEdges((existingEdges) =>
      existingEdges.filter((edge) => !selectedIds.has(edge.source) && !selectedIds.has(edge.target)),
    );
    setSelectedNodeId(null);
    setOpenedNodeId((currentNodeId) => (currentNodeId && selectedIds.has(currentNodeId) ? null : currentNodeId));
    setActiveEdgeId(null);
    setContextMenu(null);
    updateTestState((currentState) => {
      const nextState = { ...currentState };
      for (const nodeId of selectedIds) {
        delete nextState[nodeId];
      }
      return nextState;
    });
    return true;
  }

  function handleCopySelectedNodes(extraNodeId?: string): boolean {
    const selectedIds = new Set(nodes.filter((node) => node.selected).map((node) => node.id));
    if (selectedNodeId) {
      selectedIds.add(selectedNodeId);
    }
    if (extraNodeId) {
      selectedIds.add(extraNodeId);
    }

    if (selectedIds.size === 0) {
      return false;
    }

    clipboardRef.current = {
      nodes: nodes.filter((node) => selectedIds.has(node.id)),
      edges: edges.filter((edge) => selectedIds.has(edge.source) && selectedIds.has(edge.target)),
    };
    return true;
  }

  function handlePasteClipboard(): boolean {
    const clipboard = clipboardRef.current;
    if (!clipboard || clipboard.nodes.length === 0) {
      return false;
    }

    const pasted = cloneNodesForPaste(clipboard.nodes, clipboard.edges, 48);

    // Re-register any pasted compound blocks so they resolve in the palette/lookup.
    const pastedCompoundBlocks = extractCompoundBlocksFromNodes(pasted.nodes);
    if (pastedCompoundBlocks.length > 0) {
      setCompoundBlocks((currentBlocks) => {
        const existingIds = new Set(currentBlocks.map((block) => block.id));
        const additions = pastedCompoundBlocks.filter((block) => !existingIds.has(block.id));
        return additions.length > 0 ? [...currentBlocks, ...additions] : currentBlocks;
      });
    }

    setNodes((currentNodes) => [
      ...currentNodes.map((node) => ({ ...node, selected: false })),
      ...pasted.nodes,
    ]);
    setEdges((currentEdges) => [...currentEdges, ...pasted.edges]);
    // Cascade subsequent pastes and keep the copied connections wired together.
    clipboardRef.current = { nodes: pasted.nodes, edges: pasted.edges };
    setSelectedNodeId(pasted.nodes.length === 1 ? pasted.nodes[0].id : null);
    setOpenedNodeId(null);
    setActiveEdgeId(null);
    setContextMenu(null);
    return true;
  }

  function handleDuplicateSelectedNodes(extraNodeId?: string): boolean {
    return handleCopySelectedNodes(extraNodeId) && handlePasteClipboard();
  }

  useEffect(() => {
    function handleWorkflowKeyDown(event: KeyboardEvent) {
      if (isEditableKeyboardTarget(event.target)) {
        return;
      }

      if (event.key === " " && !event.ctrlKey && !event.metaKey && !editingCompoundNodeId) {
        reactFlow.fitView({ padding: 0.2, duration: 300 });
        event.preventDefault();
        return;
      }

      if (event.key === "Delete" || event.key === "Backspace") {
        if (handleDeleteSelectedNodes()) {
          event.preventDefault();
        }
        return;
      }

      if (!event.ctrlKey && !event.metaKey) {
        return;
      }

      const key = event.key.toLowerCase();
      if (key === "c" && handleCopySelectedNodes()) {
        event.preventDefault();
      } else if (key === "v" && handlePasteClipboard()) {
        event.preventDefault();
      } else if (key === "d" && handleDuplicateSelectedNodes()) {
        event.preventDefault();
      }
    }

    window.addEventListener("keydown", handleWorkflowKeyDown);
    return () => window.removeEventListener("keydown", handleWorkflowKeyDown);
  }, [nodes, edges, selectedNodeId, editingCompoundNodeId]);

  function handleToggleNodeActive(nodeId: string) {
    setNodes((currentNodes) =>
      currentNodes.map((node) =>
        node.id === nodeId
          ? {
              ...node,
              data: {
                ...node.data,
                isActive: node.data.isActive === false,
              },
            }
          : node,
      ),
    );
  }

  function handleUpdateNodeSettings(
    nodeId: string,
    updates: Partial<{ failureMode: WorkflowFailureMode; retryCount: number }>,
  ) {
    setNodes((currentNodes) =>
      currentNodes.map((node) => {
        if (node.id !== nodeId) {
          return node;
        }

        const nextFailureMode = updates.failureMode
          ? normalizeFailureMode(updates.failureMode)
          : node.data.settings.failureMode;
        const nextRetryCount = updates.retryCount !== undefined
          ? normalizeRetryCount(updates.retryCount)
          : node.data.settings.retryCount;

        return {
          ...node,
          data: {
            ...node.data,
            settings: {
              ...node.data.settings,
              failureMode: nextFailureMode,
              retryCount: nextRetryCount,
            },
          },
        };
      }),
    );

    if (updates.failureMode === "stop_flow") {
      setEdges((currentEdges) =>
        currentEdges.filter((edge) => !(edge.source === nodeId && edge.sourceHandle === "error")),
      );
    }
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();

    const blockPayload = event.dataTransfer.getData(WORKFLOW_BLOCK_MIME);
    if (!blockPayload) {
      return;
    }

    const block = JSON.parse(blockPayload) as WorkflowBlockDefinition;
    const position = reactFlow.screenToFlowPosition({
      x: event.clientX,
      y: event.clientY,
    });

    const nextNode = createWorkflowNode(block, position);
    setNodes((currentNodes) => [...currentNodes, nextNode]);
    setSelectedNodeId(nextNode.id);
    setOpenedNodeId(null);
    setActiveEdgeId(null);
  }

  function handleQuickAddFromPort(nodeId: string, outputKey: string) {
    setQuickAddSource({ kind: "port", nodeId, outputKey });
    setWorkflowDrawer("blocks");
    setSelectedNodeId(nodeId);
    setOpenedNodeId(null);
    setActiveEdgeId(null);
    setContextMenu(null);
  }

  function handleQuickAddFromEdge(edgeId: string) {
    setQuickAddSource({ kind: "edge", edgeId });
    setWorkflowDrawer("blocks");
    setSelectedNodeId(null);
    setOpenedNodeId(null);
    setActiveEdgeId(edgeId);
    setContextMenu(null);
  }

  function handleQuickAddSelectBlockFromPort(
    source: Extract<QuickAddSource, { kind: "port" }>,
    block: WorkflowBlockDefinition,
  ) {
    const sourceNode = nodeLookup.get(source.nodeId);
    if (!sourceNode) {
      return;
    }

    const outputs = getWorkflowNodeOutputs(sourceNode.data);
    const outputIndex = Math.max(outputs.findIndex((output) => output.key === source.outputKey), 0);
    const nextNode = createWorkflowNode(block, {
      x: sourceNode.position.x + 300,
      y: sourceNode.position.y + outputIndex * 140,
    });

    setNodes((currentNodes) => [...currentNodes, nextNode]);

    if (block.acceptsInput) {
      setEdges((currentEdges) =>
        addEdge(
          {
            source: source.nodeId,
            sourceHandle: source.outputKey,
            target: nextNode.id,
            targetHandle: "input",
            type: "workflowEdge",
          },
          currentEdges,
        ),
      );
    }

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        reactFlow.fitView({
          nodes: [{ id: sourceNode.id }, { id: nextNode.id }],
          padding: 0.4,
          duration: 300,
          maxZoom: 1,
        });
      });
    });

    setSelectedNodeId(nextNode.id);
  }

  function handleQuickAddSelectBlockFromEdge(
    source: Extract<QuickAddSource, { kind: "edge" }>,
    block: WorkflowBlockDefinition,
  ) {
    const edge = edges.find((candidateEdge) => candidateEdge.id === source.edgeId);
    if (!edge) {
      return;
    }

    const sourceNode = nodeLookup.get(edge.source);
    const targetNode = nodeLookup.get(edge.target);
    // Offset below the midpoint (rather than sitting exactly on it) so the new
    // node doesn't land overlapping either of its now-tightened-up neighbors.
    const position = sourceNode && targetNode
      ? { x: (sourceNode.position.x + targetNode.position.x) / 2, y: Math.max(sourceNode.position.y, targetNode.position.y) + 160 }
      : sourceNode
        ? { x: sourceNode.position.x + 300, y: sourceNode.position.y }
        : { x: 0, y: 0 };
    const nextNode = createWorkflowNode(block, position);
    const nextNodeOutputs = getWorkflowNodeOutputs(nextNode.data);

    setNodes((currentNodes) => [...currentNodes, nextNode]);
    setEdges((currentEdges) => {
      let nextEdges = currentEdges.filter((candidateEdge) => candidateEdge.id !== edge.id);

      if (block.acceptsInput) {
        nextEdges = addEdge(
          {
            source: edge.source,
            sourceHandle: edge.sourceHandle ?? null,
            target: nextNode.id,
            targetHandle: "input",
            type: "workflowEdge",
          } satisfies Connection & { type: string },
          nextEdges,
        );
      }

      if (nextNodeOutputs.length > 0) {
        nextEdges = addEdge(
          {
            source: nextNode.id,
            sourceHandle: nextNodeOutputs[0].key,
            target: edge.target,
            targetHandle: edge.targetHandle ?? null,
            type: "workflowEdge",
          } satisfies Connection & { type: string },
          nextEdges,
        );
      }

      return nextEdges;
    });

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        reactFlow.fitView({
          nodes: [{ id: edge.source }, { id: nextNode.id }, { id: edge.target }],
          padding: 0.4,
          duration: 300,
          maxZoom: 1,
        });
      });
    });

    setSelectedNodeId(nextNode.id);
  }

  function handleQuickAddSelectBlock(block: WorkflowBlockDefinition) {
    if (!quickAddSource) {
      return;
    }

    if (quickAddSource.kind === "port") {
      handleQuickAddSelectBlockFromPort(quickAddSource, block);
    } else {
      handleQuickAddSelectBlockFromEdge(quickAddSource, block);
    }

    setOpenedNodeId(null);
    setActiveEdgeId(null);
    setWorkflowDrawer(null);
    setQuickAddSource(null);
  }

  function getCompoundSelection(nodeId: string): WorkflowFlowNode[] {
    const selectedNodes = nodes.filter((node) => node.selected);
    if (selectedNodes.some((node) => node.id === nodeId)) {
      return selectedNodes;
    }

    return nodes.filter((node) => node.id === nodeId);
  }

  function getContextMenuNodeId(fallbackNodeId?: string): string | null {
    const selectedNodes = nodes.filter((node) => node.selected);
    if (fallbackNodeId) {
      return fallbackNodeId;
    }

    return selectedNodes[0]?.id ?? null;
  }

  function openWorkflowContextMenu(
    event: { preventDefault: () => void; stopPropagation: () => void; clientX: number; clientY: number },
    fallbackNodeId?: string,
  ) {
    const nodeId = getContextMenuNodeId(fallbackNodeId);
    if (!nodeId) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      nodeId,
    });
    setSelectedNodeId(nodeId);
    setOpenedNodeId(null);
    setActiveEdgeId(null);
  }

  function validateCompoundSelection(selectedNodes: WorkflowFlowNode[]): {
    ok: true;
    selectedIds: Set<string>;
    internalEdges: Edge[];
    entryNode: WorkflowFlowNode;
    outputs: CompoundOutputBuild[];
  } | {
    ok: false;
    message: string;
  } {
    if (selectedNodes.length < 2) {
      return { ok: false, message: "Select at least two directly connected blocks before creating a compound function." };
    }

    const selectedIds = new Set(selectedNodes.map((node) => node.id));
    const internalEdges = edges.filter((edge) => selectedIds.has(edge.source) && selectedIds.has(edge.target));
    if (internalEdges.length === 0) {
      return { ok: false, message: "The selected blocks must be directly connected by workflow edges." };
    }

    const adjacency = new Map<string, Set<string>>();
    for (const node of selectedNodes) {
      adjacency.set(node.id, new Set());
    }
    for (const edge of internalEdges) {
      adjacency.get(edge.source)?.add(edge.target);
      adjacency.get(edge.target)?.add(edge.source);
    }

    const firstNode = selectedNodes[0];
    const visited = new Set<string>([firstNode.id]);
    const queue = [firstNode.id];
    while (queue.length > 0) {
      const currentNodeId = queue.shift() as string;
      for (const nextNodeId of adjacency.get(currentNodeId) ?? []) {
        if (visited.has(nextNodeId)) {
          continue;
        }
        visited.add(nextNodeId);
        queue.push(nextNodeId);
      }
    }

    if (visited.size !== selectedNodes.length) {
      return { ok: false, message: "Every selected block must be connected to the same selected chain or branch." };
    }

    const entryNodes = selectedNodes.filter((node) => !internalEdges.some((edge) => edge.target === node.id));
    if (entryNodes.length !== 1) {
      return { ok: false, message: "A compound function needs exactly one selected entry block." };
    }

    return {
      ok: true,
      selectedIds,
      internalEdges,
      entryNode: entryNodes[0],
      outputs: buildCompoundOutputsFromGraph(selectedNodes, internalEdges),
    };
  }

  function handleCreateCompoundFunction(nodeId: string) {
    const selectedNodes = getCompoundSelection(nodeId);
    const validation = validateCompoundSelection(selectedNodes);
    if (!validation.ok) {
      setFunctionsError(validation.message);
      setContextMenu(null);
      return;
    }

    const minX = Math.min(...selectedNodes.map((node) => node.position.x));
    const minY = Math.min(...selectedNodes.map((node) => node.position.y));
    const compoundId = `compound-${Date.now().toString(36)}`;
    const outputKeyBySource = new Map(
      validation.outputs.map((output) => [`${output.sourceNodeId}:${output.sourceHandle ?? "next"}`, output.key]),
    );
    const compoundBlock: WorkflowBlockDefinition = {
      id: compoundId,
      displayName: `Compound Function ${compoundCounter}`,
      category: "Compound Functions",
      description: `${selectedNodes.length} directly connected blocks collapsed into one editable function.`,
      version: "1.0.0",
      kind: "compound",
      acceptsInput: validation.entryNode.data.block.acceptsInput,
      accent: "#6d5bd0",
      inputs: [],
      outputs: validation.outputs.map((output) => ({
        key: output.key,
        label: output.label,
        type: output.type,
        description: output.description,
      })),
      compound: {
        entryNodeId: validation.entryNode.id,
        nodes: selectedNodes.map((node) => cleanNodeForCompound(node, minX, minY)),
        edges: validation.internalEdges.map(cleanEdgeForCompound),
        outputs: validation.outputs,
      },
    };
    const compoundNode = createWorkflowNode(compoundBlock, { x: minX, y: minY }, "collapsed");
    compoundNode.id = compoundId;
    compoundNode.selected = true;
    setCompoundBlocks((currentBlocks) => [...currentBlocks, compoundBlock]);

    setNodes((currentNodes) => [
      ...currentNodes.filter((node) => !validation.selectedIds.has(node.id)).map((node) => ({ ...node, selected: false })),
      compoundNode,
    ]);
    setEdges((currentEdges) => [
      ...currentEdges.filter((edge) => !validation.selectedIds.has(edge.source) && !validation.selectedIds.has(edge.target)),
      ...currentEdges
        .filter((edge) => !validation.selectedIds.has(edge.source) && validation.selectedIds.has(edge.target))
        .map((edge) => ({
          ...edge,
          target: compoundId,
          targetHandle: "input",
        })),
      ...currentEdges
        .filter((edge) => validation.selectedIds.has(edge.source) && !validation.selectedIds.has(edge.target))
        .map((edge) => ({
          ...edge,
          source: compoundId,
          sourceHandle: outputKeyBySource.get(`${edge.source}:${edge.sourceHandle ?? "next"}`) ?? validation.outputs[0]?.key ?? "next",
        })),
    ]);
    setCompoundCounter((currentValue) => currentValue + 1);
    setSelectedNodeId(compoundId);
    setOpenedNodeId(null);
    setActiveEdgeId(null);
    setContextMenu(null);
    setFunctionsError(null);
    updateTestState((currentState) => {
      const nextState = { ...currentState };
      for (const selectedNode of selectedNodes) {
        delete nextState[selectedNode.id];
      }
      return nextState;
    });
  }

  function handleEditCompoundFunction(nodeId: string) {
    const compoundNode = nodeLookup.get(nodeId);
    if (!compoundNode?.data.block.compound) {
      setFunctionsError("This block does not contain editable compound function data.");
      return;
    }

    setEditingCompoundNodeId(nodeId);
    setContextMenu(null);
    setOpenedNodeId(null);
    setActiveEdgeId(null);
  }

  function handleUncompoundFunction(nodeId: string) {
    const compoundNode = nodeLookup.get(nodeId);
    const compound = compoundNode?.data.block.compound;
    if (!compoundNode || !compound) {
      setFunctionsError("This block does not contain compound function data to expand.");
      setContextMenu(null);
      return;
    }

    const innerNodes = normalizeWorkflowNodes(compound.nodes as WorkflowFlowNode[]);
    if (innerNodes.length === 0) {
      setFunctionsError("This compound function does not contain any inner blocks.");
      setContextMenu(null);
      return;
    }

    const { nodes: expandedNodes, nodeIdMap } = createExpandedCompoundNodes(compoundNode, innerNodes);
    const entryNodeId = nodeIdMap.get(compound.entryNodeId) ?? expandedNodes[0].id;
    const fallbackOutputNodeId = expandedNodes[expandedNodes.length - 1]?.id ?? entryNodeId;
    const compoundOutputLookup = new Map(compound.outputs.map((output) => [output.key, output]));
    const fallbackOutput = compound.outputs[0] ?? null;
    const expandedInternalEdges = (compound.edges as Edge[]).flatMap((edge, index) => {
      const source = nodeIdMap.get(edge.source);
      const target = nodeIdMap.get(edge.target);
      if (!source || !target) {
        return [];
      }

      return [{
        ...edge,
        id: createExpandedEdgeId("expanded", nodeId, edge.id, index),
        source,
        target,
        type: edge.type ?? "workflowEdge",
      }];
    });

    setNodes((currentNodes) => [
      ...currentNodes.filter((node) => node.id !== nodeId).map((node) => ({ ...node, selected: false })),
      ...expandedNodes,
    ]);
    setEdges((currentEdges) => {
      const retainedEdges = currentEdges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId);
      const incomingEdges = currentEdges
        .filter((edge) => edge.target === nodeId)
        .map((edge, index) => ({
          ...edge,
          id: createExpandedEdgeId("incoming", nodeId, edge.id, index),
          target: entryNodeId,
          targetHandle: edge.targetHandle ?? "input",
        }));
      const outgoingEdges = currentEdges
        .filter((edge) => edge.source === nodeId)
        .map((edge, index) => {
          const compoundOutput = compoundOutputLookup.get(edge.sourceHandle ?? "next") ?? fallbackOutput;
          const source = compoundOutput ? nodeIdMap.get(compoundOutput.sourceNodeId) : fallbackOutputNodeId;

          return {
            ...edge,
            id: createExpandedEdgeId("outgoing", nodeId, edge.id, index),
            source: source ?? fallbackOutputNodeId,
            sourceHandle: compoundOutput?.sourceHandle ?? edge.sourceHandle ?? "next",
          };
        });

      return [...retainedEdges, ...expandedInternalEdges, ...incomingEdges, ...outgoingEdges];
    });
    setSelectedNodeId(entryNodeId);
    setOpenedNodeId(null);
    setActiveEdgeId(null);
    setEditingCompoundNodeId((currentNodeId) => (currentNodeId === nodeId ? null : currentNodeId));
    setContextMenu(null);
    setFunctionsError(null);
    updateTestState((currentState) => {
      const nextState = { ...currentState };
      delete nextState[nodeId];
      return nextState;
    });
  }

  function handleSaveCompoundEdit(
    nodeId: string,
    innerNodes: WorkflowFlowNode[],
    innerEdges: Edge[],
  ) {
    const compoundNode = nodeLookup.get(nodeId);
    if (!compoundNode) {
      setFunctionsError("Could not find the compound function being edited.");
      return;
    }

    const previousOutputs = compoundNode?.data.block.compound?.outputs ?? [];
    const previousOutputLookup = new Map(previousOutputs.map((output) => [output.key, output]));
    const cleanedNodes = innerNodes.map((innerNode) => cleanNodeForCompound(innerNode, 0, 0));
    const cleanedEdges = innerEdges.map(cleanEdgeForCompound);
    const outputs = buildCompoundOutputsFromGraph(cleanedNodes, cleanedEdges);
    const outputKeyBySource = new Map(
      outputs.map((output) => [`${output.sourceNodeId}:${output.sourceHandle ?? "next"}`, output.key]),
    );
    const entryNodeId = findCompoundEntryNodeId(
      cleanedNodes,
      cleanedEdges,
      compoundNode?.data.block.compound?.entryNodeId,
    );
    const entryNode = cleanedNodes.find((innerNode) => innerNode.id === entryNodeId) ?? cleanedNodes[0];
    const nextBlock: WorkflowBlockDefinition = {
      ...compoundNode.data.block,
      acceptsInput: entryNode?.data.block.acceptsInput ?? compoundNode.data.block.acceptsInput,
      description: `${cleanedNodes.length} directly connected blocks collapsed into one editable function.`,
      outputs: outputs.map((output) => ({
        key: output.key,
        label: output.label,
        type: output.type,
        description: output.description,
      })),
      compound: {
        entryNodeId,
        nodes: cleanedNodes,
        edges: cleanedEdges,
        outputs,
      },
    };

    setNodes((currentNodes) =>
      currentNodes.map((node) =>
        node.id === nodeId
          ? {
          ...node,
          data: {
            ...node.data,
            block: nextBlock,
            parameters: mergeParametersForBlock(nextBlock, node.data.parameters),
          },
            }
          : node,
      ),
    );
    setCompoundBlocks((currentBlocks) =>
      currentBlocks.some((block) => block.id === nextBlock.id)
        ? currentBlocks.map((block) => (block.id === nextBlock.id ? nextBlock : block))
        : [...currentBlocks, nextBlock],
    );
    setEdges((currentEdges) =>
      currentEdges.map((edge) => {
        if (edge.source !== nodeId) {
          return edge;
        }

        const previousOutput = previousOutputLookup.get(edge.sourceHandle ?? "next");
        const nextSourceHandle = previousOutput
          ? outputKeyBySource.get(`${previousOutput.sourceNodeId}:${previousOutput.sourceHandle ?? "next"}`)
          : null;

        return {
          ...edge,
          sourceHandle: nextSourceHandle ?? outputs[0]?.key ?? "next",
        };
      }),
    );
    setEditingCompoundNodeId(null);
    setSelectedNodeId(nodeId);
    setFunctionsError(null);
  }

  async function handleSaveWorkflow() {
    if (saveResetTimeoutRef.current) {
      window.clearTimeout(saveResetTimeoutRef.current);
    }
    setSaveState("saving");
    try {
      await saveWorkflowToFile(
        nodes as WorkflowCanvasNode[],
        edges as WorkflowCanvasEdge[],
        saveAsPath,
        saveAsName,
      );
      setSaveState("saved");
      savedWorkflowSnapshotRef.current = serializeWorkflowForDirtyCheck(nodes, edges);
      setHasUnsavedChanges(false);
      saveResetTimeoutRef.current = window.setTimeout(() => setSaveState("idle"), 1600);
    } catch (error) {
      setSaveState("idle");
      setFunctionsError(error instanceof Error ? error.message : "Could not save workflow file.");
    }
  }

  async function handleLoadSavedWorkflow() {
    try {
      const savedWorkflow = await fetchSavedWorkflow();
      const parsedNodes = normalizeWorkflowNodes((savedWorkflow.workflow.nodes ?? []) as WorkflowFlowNode[]);
      const parsedEdges = (savedWorkflow.workflow.edges ?? []) as Edge[];
      savedWorkflowSnapshotRef.current = serializeWorkflowForDirtyCheck(parsedNodes, parsedEdges);
      setHasUnsavedChanges(false);
      setNodes(parsedNodes);
      setEdges(parsedEdges);
      setCompoundBlocks(extractCompoundBlocksFromNodes(parsedNodes));
      setSelectedNodeId(null);
      setOpenedNodeId(null);
      setActiveEdgeId(null);
      setFunctionsError(`Loaded workflow from ${savedWorkflow.path}`);
    } catch (error) {
      setFunctionsError(error instanceof Error ? error.message : "Could not load saved workflow file.");
    }
  }

  function handleResetWorkflow() {
    Object.values(testAbortControllersRef.current).forEach((controller) => controller.abort());
    testAbortControllersRef.current = {};
    const nextStarterWorkflow = createStarterWorkflow();
    setNodes(nextStarterWorkflow.nodes);
    setEdges(nextStarterWorkflow.edges);
    setSelectedNodeId(null);
    setOpenedNodeId(null);
    setActiveEdgeId(null);
  }

  function parseSpeedNumber(value: WorkflowParameterValue | undefined): number | null {
    if (typeof value === "number") {
      return Number.isFinite(value) && value > 0 ? value : null;
    }
    if (typeof value === "string" && !value.includes("{{")) {
      const parsed = Number(value.replace(",", "."));
      return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    }
    return null;
  }

  // Keep acceleration proportional to speed: doubling the speed doubles the
  // acceleration, preserving whatever speed/acceleration ratio the node had.
  function getLinkedAccelerationUpdate(
    nodeId: string,
    input: WorkflowInputDefinition,
    value: WorkflowParameterValue,
  ): Record<string, WorkflowParameterValue> {
    const node = nodeLookup.get(nodeId);
    if (!node || input.key !== "speed_rpm") {
      return {};
    }
    if (!getAllBlockInputs(node.data.block).some((blockInput) => blockInput.key === "acceleration_rpm_per_s")) {
      return {};
    }

    // The anchor speed survives the field being cleared mid-edit, so retyping
    // a value still scales relative to the last real speed.
    const currentSpeed = parseSpeedNumber(node.data.parameters.speed_rpm);
    if (lastValidSpeedByNodeIdRef.current[nodeId] === undefined && currentSpeed !== null) {
      lastValidSpeedByNodeIdRef.current[nodeId] = currentSpeed;
    }

    const nextSpeed = parseSpeedNumber(value);
    if (nextSpeed === null) {
      return {};
    }

    const previousSpeed = lastValidSpeedByNodeIdRef.current[nodeId];
    lastValidSpeedByNodeIdRef.current[nodeId] = nextSpeed;
    const currentAcceleration = parseSpeedNumber(node.data.parameters.acceleration_rpm_per_s);
    if (previousSpeed === undefined || previousSpeed === nextSpeed || currentAcceleration === null) {
      return {};
    }

    return {
      acceleration_rpm_per_s: Math.round((currentAcceleration * nextSpeed / previousSpeed) * 100) / 100,
    };
  }

  function handleUpdateParameter(
    nodeId: string,
    input: WorkflowInputDefinition,
    value: WorkflowParameterValue,
  ) {
    const linkedUpdates = getLinkedAccelerationUpdate(nodeId, input, value);
    setNodes((currentNodes) =>
      currentNodes.map((node) =>
        node.id === nodeId
          ? {
              ...node,
              data: {
                ...node.data,
                parameters: {
                  ...node.data.parameters,
                  [input.key]: value,
                  ...linkedUpdates,
                },
              },
            }
          : node,
      ),
    );
  }

  function recordNodeDuration(nodeId: string, durationMs: number) {
    setNodes((currentNodes) =>
      currentNodes.map((node) => {
        if (node.id !== nodeId) {
          return node;
        }

        const previousRunCount = node.data.runCount ?? 0;
        const previousBenchmark = node.data.benchmarkDurationMs ?? null;
        const nextBenchmark = previousBenchmark !== null
          ? Math.round(((previousBenchmark * previousRunCount) + durationMs) / (previousRunCount + 1))
          : Math.round(durationMs);

        return {
          ...node,
          data: {
            ...node.data,
            runCount: previousRunCount + 1,
            lastDurationMs: Math.round(durationMs),
            benchmarkDurationMs: nextBenchmark,
          },
        };
      }),
    );
  }

  async function runSingleNode(
    node: WorkflowFlowNode,
    inputData: Record<string, unknown> | null,
    blockResults: Record<string, Record<string, unknown> | null | undefined> = {},
    signal?: AbortSignal,
  ): Promise<FunctionTestResponse> {
    const disabledReason = getDisabledHardwareReason(node.data.block, hardwareMap);
    if (disabledReason) {
      return {
        function_id: node.data.block.id,
        ok: true,
        inputs: node.data.parameters,
        input_data: inputData,
        result: {
          status: "hardware_disabled",
          message: disabledReason,
        },
        error: null,
      };
    }

    const resolvedParameters = resolveWorkflowParameters(
      getAllBlockInputs(node.data.block),
      node.data.parameters,
      inputData,
      { blockResults },
    );
    const hardwareResolvedParameters = resolveHardwareMapParameters(
      node.data.block,
      resolvedParameters,
      hardwareMap,
    );

    if (node.data.block.kind === "broken") {
      return runBuiltInBlockTest(node.data.block, hardwareResolvedParameters, inputData);
    }

    if (node.data.block.kind === "compound") {
      return runCompoundBlock(node.data.block, hardwareResolvedParameters, inputData, blockResults, signal);
    }

    if (node.data.block.id === "delay") {
      const durationMs = Number(hardwareResolvedParameters.duration_ms ?? 0);
      if (Number.isFinite(durationMs) && durationMs > 0) {
        await new Promise((resolve) => window.setTimeout(resolve, durationMs));
      }
    }

    if (isClientExecutedBlock(node.data.block)) {
      return runBuiltInBlockTest(node.data.block, hardwareResolvedParameters, inputData);
    }

    return testFunction(node.data.block.id, hardwareResolvedParameters, inputData, signal);
  }

  async function runCompoundBlock(
    block: WorkflowBlockDefinition,
    parameters: Record<string, WorkflowParameterValue>,
    inputData: Record<string, unknown> | null,
    blockResults: Record<string, Record<string, unknown> | null | undefined>,
    signal?: AbortSignal,
  ): Promise<FunctionTestResponse> {
    const compound = block.compound;
    if (!compound) {
      throw new Error("This compound function does not contain any editable inner blocks.");
    }

    const innerNodes = compound.nodes as WorkflowFlowNode[];
    const innerEdges = compound.edges as Edge[];
    const innerNodeLookup = new Map(innerNodes.map((innerNode) => [innerNode.id, innerNode]));
    const orderedNodeIds = collectCompoundRunOrder(compound.entryNodeId, innerEdges);
    const innerResults = new Map<string, FunctionTestResponse>();
    const compoundBlockResults = { ...blockResults };

    for (const innerNodeId of orderedNodeIds) {
      const innerNode = innerNodeLookup.get(innerNodeId);
      if (!innerNode) {
        continue;
      }

      const upstreamEdge = innerEdges.find((edge) => edge.target === innerNodeId);
      const innerInputData = upstreamEdge
        ? innerResults.get(upstreamEdge.source)?.result ?? null
        : inputData;
      const result = await runSingleNode(innerNode, innerInputData, compoundBlockResults, signal);
      innerResults.set(innerNodeId, result);
      compoundBlockResults[innerNodeId] = result.result ?? null;

      if (!result.ok) {
        return {
          function_id: block.id,
          ok: false,
          inputs: parameters,
          input_data: inputData,
          result: {
            status: "compound_failed",
            failed_node_id: innerNodeId,
            failed_block: innerNode.data.block.displayName,
            inner_results: Object.fromEntries(innerResults),
          },
          error: result.error ?? `${innerNode.data.block.displayName} failed inside ${block.displayName}.`,
        };
      }
    }

    return {
      function_id: block.id,
      ok: true,
      inputs: parameters,
      input_data: inputData,
      result: {
        status: "completed",
        inner_block_count: orderedNodeIds.length,
        outputs: block.outputs.map((output) => output.key),
        inner_results: Object.fromEntries(innerResults),
      },
      error: null,
    };
  }

  function collectCompoundRunOrder(
    startNodeId: string,
    innerEdges: Edge[],
    visited = new Set<string>(),
    orderedNodeIds: string[] = [],
  ): string[] {
    if (visited.has(startNodeId)) {
      return orderedNodeIds;
    }

    visited.add(startNodeId);
    orderedNodeIds.push(startNodeId);

    for (const edge of innerEdges.filter((candidate) => candidate.source === startNodeId)) {
      collectCompoundRunOrder(edge.target, innerEdges, visited, orderedNodeIds);
    }

    return orderedNodeIds;
  }

  async function executeNode(
    nodeId: string,
    inputData: Record<string, unknown> | null,
    nodeOverride?: WorkflowFlowNode,
  ): Promise<FunctionTestResponse> {
    const node = nodeOverride ?? nodeLookup.get(nodeId);
    if (!node) {
      throw new Error(`Could not find node '${nodeId}' for execution.`);
    }

    const disabledReason = getDisabledHardwareReason(node.data.block, hardwareMap);
    if (disabledReason) {
      const disabledResult: FunctionTestResponse = {
        function_id: node.data.block.id,
        ok: true,
        inputs: node.data.parameters,
        input_data: inputData,
        result: {
          status: "hardware_disabled",
          message: disabledReason,
        },
        error: null,
      };

      updateTestState((currentState) => ({
        ...currentState,
        [nodeId]: {
          status: "success",
          result: disabledResult,
          error: null,
        },
      }));

      return disabledResult;
    }

    if (node.data.isActive === false) {
      const inactiveResult: FunctionTestResponse = {
        function_id: node.data.block.id,
        ok: true,
        inputs: node.data.parameters,
        input_data: inputData,
        result: {
          status: "inactive",
          message: "This block is deactivated.",
        },
        error: null,
      };

      updateTestState((currentState) => ({
        ...currentState,
        [nodeId]: {
          status: "success",
          result: inactiveResult,
          error: null,
        },
      }));

      return inactiveResult;
    }

    updateTestState((currentState) => ({
      ...currentState,
      [nodeId]: {
        status: "running",
        result: currentState[nodeId]?.result ?? null,
        error: null,
      },
    }));

    const startedAt = performance.now();
    const abortController = new AbortController();
    testAbortControllersRef.current[nodeId] = abortController;

    try {
      const blockResults = buildBlockResultLookup();
      const result = await runSingleNode(node, inputData, blockResults, abortController.signal);
      const durationMs = performance.now() - startedAt;
      recordNodeDuration(nodeId, durationMs);
      delete testAbortControllersRef.current[nodeId];

      updateTestState((currentState) => ({
        ...currentState,
        [nodeId]: {
          status: result.ok ? "success" : "error",
          result,
          error: result.error ?? null,
        },
      }));

      return result;
    } catch (error) {
      const durationMs = performance.now() - startedAt;
      recordNodeDuration(nodeId, durationMs);
      delete testAbortControllersRef.current[nodeId];
      const message = error instanceof DOMException && error.name === "AbortError"
        ? "Cancellation requested."
        : error instanceof Error
          ? error.message
          : "Block test failed.";
      updateTestState((currentState) => ({
        ...currentState,
        [nodeId]: {
          status: "error",
          result: currentState[nodeId]?.result ?? null,
          error: message,
        },
      }));
      throw error;
    }
  }

  async function handleCancelNodeExecution(nodeId: string, nodeOverride?: WorkflowFlowNode) {
    const node = nodeOverride ?? nodeLookup.get(nodeId);
    if (!node) {
      return;
    }

    testAbortControllersRef.current[nodeId]?.abort();

    updateTestState((currentState) => ({
      ...currentState,
      [nodeId]: {
        status: "error",
        result: currentState[nodeId]?.result ?? null,
        error: "Cancellation requested.",
      },
    }));

    if (!isAdvancedBlock(node.data.block)) {
      return;
    }

    try {
      const response = await cancelFunction(
        node.data.block.id,
        node.data.parameters,
      );
      updateTestState((currentState) => ({
        ...currentState,
        [nodeId]: {
          status: response.ok ? "error" : (currentState[nodeId]?.status ?? "error"),
          result: currentState[nodeId]?.result ?? null,
          error: response.message,
        },
      }));
    } catch (error) {
      updateTestState((currentState) => ({
        ...currentState,
        [nodeId]: {
          status: "error",
          result: currentState[nodeId]?.result ?? null,
          error: error instanceof Error ? error.message : "Could not cancel this block.",
        },
      }));
    }
  }

  async function runNodeTestRecursively(
    nodeId: string,
    visited = new Set<string>(),
  ): Promise<FunctionTestResponse> {
    if (visited.has(nodeId)) {
      throw new Error("Cannot test a cyclic workflow path.");
    }

    visited.add(nodeId);

    const node = nodeLookup.get(nodeId);
    if (!node) {
      throw new Error(`Could not find node '${nodeId}' for test execution.`);
    }

    let inputData: Record<string, unknown> | null = null;
    const upstreamEdge = edges.find((edge) => edge.target === nodeId);

    if (blockUsesUpstreamInput(node.data.block)) {
      if (!upstreamEdge) {
        throw new Error("This step needs upstream input. Connect and test the previous step first.");
      }

      const upstreamResult = await runNodeTestRecursively(upstreamEdge.source, visited);
      inputData = upstreamResult.result ?? null;
    }

    return executeNode(nodeId, inputData);
  }

  async function handleRunTest() {
    if (!openedNode) {
      return;
    }

    await handleRunTestForNode(openedNode.id);
  }

  async function handleRunTestForNode(nodeId: string) {
    try {
      await runNodeTestRecursively(nodeId);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Block test failed.";
      updateTestState((currentState) => ({
        ...currentState,
        [nodeId]: {
          status: "error",
          result: currentState[nodeId]?.result ?? null,
          error: message,
        },
      }));
    }
  }

  // Runs a node that lives outside the main canvas (e.g. inside the compound
  // editor). It executes standalone, without resolving upstream inputs.
  async function handleRunDetachedNode(node: WorkflowFlowNode) {
    try {
      await executeNode(node.id, null, node);
    } catch {
      // executeNode already records the failure in the node's test state.
    }
  }

  async function handleSaveCustomBlock(
    nodeId: string,
    displayName: string,
    nodeOverride?: WorkflowFlowNode,
  ): Promise<Esp32CustomBlockSaveResponse> {
    const node = nodeOverride ?? nodeLookup.get(nodeId);
    if (!node) {
      throw new Error("Could not find the selected block.");
    }

    if (!node.data.block.builderBoardId) {
      throw new Error("This block is not linked to an ESP32 workspace.");
    }

    const trimmedDisplayName = displayName.trim();
    if (!trimmedDisplayName) {
      throw new Error("Custom block name cannot be empty.");
    }

    const response = await saveEsp32CustomBlock(
      node.data.block.builderBoardId,
      node.data.block.id,
      trimmedDisplayName,
      `${trimmedDisplayName} reusable preset.`,
      node.data.parameters,
    );
    await Promise.all([loadFunctions(), loadBoards(), loadHardwareMap()]);
    return response;
  }

  async function handleDeleteCustomBlock(block: WorkflowBlockDefinition) {
    if (!block.builderBoardId || !block.builderBaseFunctionId) {
      setFunctionsError("Only saved custom block presets can be deleted.");
      return;
    }

    try {
      const response = await deleteEsp32CustomBlock(block.builderBoardId, block.id);
      await Promise.all([loadFunctions(), loadBoards()]);
      setFunctionsError(`Deleted custom block ${response.display_name}`);
    } catch (error) {
      setFunctionsError(error instanceof Error ? error.message : "Could not delete custom block.");
    }
  }

  function collectRunAllOrder(
    startNodeId: string,
    traversalVisited = new Set<string>(),
    orderedNodeIds: string[] = [],
  ): string[] {
    if (traversalVisited.has(startNodeId)) {
      return orderedNodeIds;
    }

    traversalVisited.add(startNodeId);
    orderedNodeIds.push(startNodeId);

    const downstreamEdges = edges.filter((edge) => edge.source === startNodeId);
    for (const edge of downstreamEdges) {
      collectRunAllOrder(edge.target, traversalVisited, orderedNodeIds);
    }

    return orderedNodeIds;
  }

  function collectEsp32BoardIdsFromBlock(
    block: WorkflowBlockDefinition,
    boardIds: Set<string>,
  ) {
    if (getDisabledHardwareReason(block, hardwareMap)) {
      return;
    }

    if (getHardwareDependencyDeviceIds(block).length === 0 && isEsp32WorkflowBoardId(block.hardwareBoardId)) {
      boardIds.add(block.hardwareBoardId);
    }

    for (const innerNode of block.compound?.nodes ?? []) {
      collectEsp32BoardIdsFromBlock(innerNode.data.block, boardIds);
    }
  }

  function collectEsp32BoardIdsForRun(orderedNodeIds: string[]): string[] {
    const boardIds = new Set<string>();

    for (const nodeId of orderedNodeIds) {
      const node = nodeLookup.get(nodeId);
      if (!node) {
        continue;
      }

      collectEsp32BoardIdsFromBlock(node.data.block, boardIds);
    }

    return Array.from(boardIds);
  }

  function getHardwareMapEsp32BoardIds(): Set<string> {
    return new Set((hardwareMap?.boards ?? [])
      .filter((board) => isHardwareEnabled(board))
      .map((board) => board.id)
      .filter(isEsp32WorkflowBoardId));
  }

  function filterBoardIdsToHardwareMap(boardIds: string[]): string[] {
    const hardwareBoardIds = getHardwareMapEsp32BoardIds();
    if (hardwareBoardIds.size === 0) {
      return [];
    }

    return Array.from(new Set(boardIds.filter((boardId) => hardwareBoardIds.has(boardId))));
  }

  function addHardwareDeviceBoardIds(
    block: WorkflowBlockDefinition,
    deviceIds: string[],
    boardIds: Set<string>,
  ) {
    for (const deviceId of deviceIds) {
      const blockDevice = block.hardwareDevices?.find((device) => device.id === deviceId);
      const mappedDevice = hardwareMap?.devices.find((device) => device.id === deviceId);
      if (mappedDevice && hardwareMap && !isHardwareDeviceEnabled(hardwareMap, mappedDevice)) {
        continue;
      }

      if (!mappedDevice && isEsp32WorkflowBoardId(blockDevice?.board_id)) {
        boardIds.add(blockDevice.board_id);
        continue;
      }

      if (isEsp32WorkflowBoardId(mappedDevice?.board_id)) {
        boardIds.add(mappedDevice.board_id);
      }
    }
  }

  function getBoardIdsForFirmwareRequirement(
    block: WorkflowBlockDefinition,
    requirement: WorkflowFirmwareRequirement,
  ): string[] {
    if (requirement.controller_role === "raspberry_pi") {
      return [];
    }

    const boardIds = new Set<string>();
    const canUseLegacyBoardFallback = requirement.required_device_ids.length === 0;

    if (requirement.controller_role === "device_board") {
      addHardwareDeviceBoardIds(block, requirement.required_device_ids, boardIds);
      if (boardIds.size === 0 && canUseLegacyBoardFallback && isEsp32WorkflowBoardId(block.hardwareBoardId)) {
        boardIds.add(block.hardwareBoardId);
      }
      return Array.from(boardIds);
    }

    if (requirement.controller_role === "builder_board") {
      addHardwareDeviceBoardIds(block, requirement.required_device_ids, boardIds);
      if (boardIds.size === 0 && canUseLegacyBoardFallback && isEsp32WorkflowBoardId(block.hardwareBoardId)) {
        boardIds.add(block.hardwareBoardId);
      }
      return Array.from(boardIds);
    }

    if (boardIds.size === 0 && canUseLegacyBoardFallback && isEsp32WorkflowBoardId(block.hardwareBoardId)) {
      boardIds.add(block.hardwareBoardId);
    }
    if (boardIds.size === 0) {
      addHardwareDeviceBoardIds(block, requirement.required_device_ids, boardIds);
    }

    return Array.from(boardIds);
  }

  function addWorkflowFirmwarePlanItem(
    itemsByKey: Map<string, Esp32WorkflowFirmwarePlanRequestItem>,
    blockId: string,
    block: WorkflowBlockDefinition,
    boardId: string,
    requirement: WorkflowFirmwareRequirement,
  ) {
    const itemKey = `${blockId}:${boardId}`;
    const existingItem = itemsByKey.get(itemKey);
    if (existingItem) {
      existingItem.requirements.push(requirement);
      return;
    }

    itemsByKey.set(itemKey, {
      block_id: blockId,
      block_name: block.displayName,
      board_id: boardId,
      requirements: [requirement],
    });
  }

  function collectWorkflowFirmwarePlanItemsFromBlock(
    block: WorkflowBlockDefinition,
    blockId: string,
    itemsByKey: Map<string, Esp32WorkflowFirmwarePlanRequestItem>,
  ) {
    if (getDisabledHardwareReason(block, hardwareMap)) {
      return;
    }

    for (const requirement of block.firmwareRequirements ?? []) {
      const boardIds = getBoardIdsForFirmwareRequirement(block, requirement);
      for (const boardId of boardIds) {
        addWorkflowFirmwarePlanItem(itemsByKey, blockId, block, boardId, requirement);
      }
    }

    for (const innerNode of block.compound?.nodes ?? []) {
      collectWorkflowFirmwarePlanItemsFromBlock(
        innerNode.data.block,
        `${blockId}/${innerNode.id}`,
        itemsByKey,
      );
    }
  }

  function collectWorkflowFirmwarePlanItemsForRun(
    orderedNodeIds: string[],
  ): Esp32WorkflowFirmwarePlanRequestItem[] {
    const itemsByKey = new Map<string, Esp32WorkflowFirmwarePlanRequestItem>();

    for (const nodeId of orderedNodeIds) {
      const node = nodeLookup.get(nodeId);
      if (!node) {
        continue;
      }

      collectWorkflowFirmwarePlanItemsFromBlock(node.data.block, nodeId, itemsByKey);
    }

    const hardwareBoardIds = getHardwareMapEsp32BoardIds();
    if (hardwareBoardIds.size === 0) {
      return [];
    }

    return Array.from(itemsByKey.values()).filter((item) => hardwareBoardIds.has(item.board_id));
  }

  function summarizeWorkflowFirmwarePlanFailure(errors: string[], warnings: string[]): string {
    const details = errors.length > 0 ? errors : warnings;
    if (details.length === 0) {
      return "Could not prepare ESP32 firmware for this workflow.";
    }

    return `Could not prepare ESP32 firmware for this workflow. ${details.slice(0, 4).join(" ")}`;
  }

  async function prepareEsp32FirmwareForRun(
    planItems: Esp32WorkflowFirmwarePlanRequestItem[],
    fallbackBoardIds: string[],
  ): Promise<string[]> {
    if (planItems.length === 0) {
      return fallbackBoardIds;
    }

    const plan = await planWorkflowFirmware(planItems);
    if (!plan.ok) {
      throw new Error(summarizeWorkflowFirmwarePlanFailure(plan.errors, plan.warnings));
    }

    return Array.from(new Set([...fallbackBoardIds, ...plan.boards.map((board) => board.board_id)]));
  }

  async function flashEsp32BoardsForRun(boardIds: string[]) {
    const abortController = new AbortController();
    flashAbortControllerRef.current = abortController;
    try {
      for (const boardId of boardIds) {
        setWorkflowRunState((currentState) => ({
          ...currentState,
          flashingBoardId: boardId,
        }));

        const response = await flashEsp32BoardFirmware(boardId, abortController.signal);
        if (!response.ok) {
          throw new Error(`Could not flash ESP32 '${boardId}'. ${response.log || response.auto_reset_note}`);
        }
      }
    } finally {
      flashAbortControllerRef.current = null;
    }
  }

  async function runOrderedWorkflowNodes(orderedNodeIds: string[], resultsByNodeId: Map<string, FunctionTestResponse>) {
    for (const nodeId of orderedNodeIds) {
      if (resultsByNodeId.has(nodeId)) {
        continue;
      }

      const node = nodeLookup.get(nodeId);
      if (!node) {
        continue;
      }

      setWorkflowRunState((currentState) => ({
        ...currentState,
        currentNodeId: nodeId,
      }));

      let inputData: Record<string, unknown> | null = null;
      const upstreamEdge = edges.find((edge) => edge.target === nodeId);
      if (blockUsesUpstreamInput(node.data.block) && upstreamEdge) {
        inputData = resultsByNodeId.get(upstreamEdge.source)?.result ?? null;
      }

      const result = await executeNode(nodeId, inputData);
      resultsByNodeId.set(nodeId, result);
      workflowResultsRef.current = resultsByNodeId;

      setWorkflowRunState((currentState) => ({
        ...currentState,
        completedNodeIds: currentState.completedNodeIds.includes(nodeId)
          ? currentState.completedNodeIds
          : [...currentState.completedNodeIds, nodeId],
      }));
    }
  }

  async function runWorkflowFromOrder(
    orderedNodeIds: string[],
    resultsByNodeId: Map<string, FunctionTestResponse>,
    options: { flashBeforeRun: boolean },
  ) {
    const fallbackBoardIdsToFlash = skipEsp32Flashing
      ? []
      : filterBoardIdsToHardwareMap(collectEsp32BoardIdsForRun(orderedNodeIds));
    const firmwarePlanItems = skipEsp32Flashing ? [] : collectWorkflowFirmwarePlanItemsForRun(orderedNodeIds);
    const hasEsp32FirmwareWork = fallbackBoardIdsToFlash.length > 0 || firmwarePlanItems.length > 0;

    setFunctionsError(null);
    setSelectedNodeId(null);
    setOpenedNodeId(null);
    setWorkflowDrawer(null);
    setWorkflowRunState({
      isRunning: true,
      phase: hasEsp32FirmwareWork ? "flashing" : "running",
      orderedNodeIds,
      currentNodeId: null,
      completedNodeIds: Array.from(resultsByNodeId.keys()),
      flashingBoardId: null,
    });

    try {
      if (options.flashBeforeRun) {
        const boardIdsToFlash = await prepareEsp32FirmwareForRun(firmwarePlanItems, fallbackBoardIdsToFlash);
        await flashEsp32BoardsForRun(boardIdsToFlash);
      }
      setWorkflowRunState((currentState) => ({
        ...currentState,
        phase: "running",
        flashingBoardId: null,
      }));
      await runOrderedWorkflowNodes(orderedNodeIds, resultsByNodeId);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        setFunctionsError("Workflow stopped by E-Stop.");
      } else {
        setFunctionsError(error instanceof Error ? error.message : "Workflow run failed.");
      }
    } finally {
      setWorkflowRunState((currentState) => ({
        ...currentState,
        isRunning: false,
        phase: "idle",
        currentNodeId: null,
        flashingBoardId: null,
      }));
    }
  }

  async function resumeStoppedWorkflowRun() {
    if (workflowRunState.isRunning || workflowRunState.orderedNodeIds.length === 0) {
      return;
    }

    setFunctionsError(null);
    await runWorkflowFromOrder(workflowRunState.orderedNodeIds, workflowResultsRef.current, { flashBeforeRun: false });
  }

  async function handleRunAll() {
    // Pressing Run all re-arms the E-Stop (clears any latched "RESUME" state).
    window.dispatchEvent(new CustomEvent("robot-emergency-reset"));

    const startNodeIds = nodes
      .filter((node) => node.data.block.id === "start")
      .map((node) => node.id);
    const orphanRootNodeIds = nodes
      .filter((node) => !edges.some((edge) => edge.target === node.id))
      .map((node) => node.id);
    const rootNodeIds = Array.from(new Set([...startNodeIds, ...orphanRootNodeIds]));

    if (rootNodeIds.length === 0) {
      setFunctionsError("No start or root block is available to run.");
      return;
    }

    const orderedNodeIds: string[] = [];
    const traversalVisited = new Set<string>();
    for (const nodeId of rootNodeIds) {
      collectRunAllOrder(nodeId, traversalVisited, orderedNodeIds);
    }

    workflowResultsRef.current = new Map();
    await runWorkflowFromOrder(orderedNodeIds, workflowResultsRef.current, { flashBeforeRun: true });
  }

  async function handleCancelRun() {
    // Abort the in-flight flash request and any running node tests locally...
    flashAbortControllerRef.current?.abort();
    flashAbortControllerRef.current = null;
    Object.values(testAbortControllersRef.current).forEach((controller) => controller.abort());
    testAbortControllersRef.current = {};
    // ...then tell the backend to kill an in-progress board flash and stop motion.
    try {
      await emergencyStop();
    } catch {
      // Ignore network errors: the local abort and state reset still cancel the run.
    }
    setWorkflowRunState((currentState) => ({
      ...currentState,
      isRunning: false,
      phase: "idle",
      currentNodeId: null,
      flashingBoardId: null,
    }));
    setFunctionsError("Workflow run cancelled.");
  }

  const headerControls = (
    <div className="workflow-editor__actions">
      <div className="toolbar-group">
        <button
          className={saveState === "saved"
            ? "workflow-editor__action workflow-editor__action--ghost workflow-editor__action--saved"
            : "workflow-editor__action workflow-editor__action--ghost"}
          disabled={saveState === "saving"}
          onClick={() => void handleSaveWorkflow()}
          title={hasUnsavedChanges ? "You have unsaved changes" : undefined}
          type="button"
        >
          {saveState === "saving" ? "Saving…" : saveState === "saved" ? "Saved ✓" : "Save"}
          {saveState === "idle" && hasUnsavedChanges ? <span className="toolbar-unsaved-dot" /> : null}
        </button>
      </div>

      <div className="toolbar-group toolbar-group--run">
        <label className="workflow-editor__skip-flash">
          <input
            checked={skipEsp32Flashing}
            disabled={workflowRunState.isRunning}
            onChange={(event) => setSkipEsp32Flashing(event.target.checked)}
            type="checkbox"
          />
          <span>Skip ESP32 flash</span>
        </label>
        <button
          className="workflow-editor__action workflow-editor__action--primary"
          disabled={workflowRunState.isRunning}
          onClick={() => void handleRunAll()}
          type="button"
        >
          {workflowRunState.phase === "flashing" ? "Flashing ESP32..." : workflowRunState.isRunning ? "Running flow..." : "Run all"}
        </button>
      </div>
    </div>
  );

  return (
    <section className="editor-workspace editor-workspace--workflow-page workflow-editor">
        {headerSlot && isActive ? createPortal(headerControls, headerSlot) : null}

        {functionsError ? (
          <div className="workflow-error-banner" role="alert">
            <span className="workflow-error-banner__message">{functionsError}</span>
            <button
              aria-label="Dismiss"
              className="workflow-error-banner__dismiss"
              onClick={() => setFunctionsError(null)}
              type="button"
            >
              ×
            </button>
          </div>
        ) : null}

        <div className="editor-workspace__canvas-frame workflow-editor__surface">
          <div
            className="workflow-editor__canvas-shell"
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            onPointerDownCapture={handleControlDragPan}
          >
            {workflowDrawer !== "blocks" ? (
              <button
                aria-label="Add blocks"
                className="workflow-canvas-add"
                onClick={() => {
                  setWorkflowDrawer("blocks");
                  setQuickAddSource(null);
                }}
                title="Add blocks"
                type="button"
              >
                +
              </button>
            ) : null}
            <div className="workflow-editor__stats">
              <span>{nodes.length} block{nodes.length === 1 ? "" : "s"}</span>
              <span>Est. total {formatDurationShort(nodes.reduce((total, node) => total + estimateNodeDuration(node), 0))}</span>
            </div>

            <div className="workflow-editor__canvas">
              <ReactFlow
                edges={renderedEdges}
                edgeTypes={edgeTypes}
                fitView
                nodeTypes={nodeTypes}
                nodes={renderedNodes}
                onConnect={handleConnect}
                onEdgesChange={onEdgesChange}
                onEdgeClick={(event, edge) => {
                  event.stopPropagation();
                  setActiveEdgeId(edge.id);
                  setSelectedNodeId(null);
                  setOpenedNodeId(null);
                  setContextMenu(null);
                }}
                onNodeClick={(event, node) => {
                  event.stopPropagation();
                  setSelectedNodeId(node.id);
                  setOpenedNodeId(null);
                  setActiveEdgeId(null);
                  setContextMenu(null);
                }}
                onNodeDoubleClick={(event, node) => {
                  event.stopPropagation();
                  setSelectedNodeId(node.id);
                  setOpenedNodeId(node.id);
                  setActiveEdgeId(null);
                  setContextMenu(null);
                }}
                onNodeContextMenu={(event, node) => openWorkflowContextMenu(event, node.id)}
                onNodesChange={onNodesChange}
                onPaneClick={() => {
                  setSelectedNodeId(null);
                  setOpenedNodeId(null);
                  setWorkflowDrawer(null);
                  setQuickAddSource(null);
                  setActiveEdgeId(null);
                  setContextMenu(null);
                }}
                onPaneContextMenu={(event) => {
                  if (nodes.some((node) => node.selected)) {
                    openWorkflowContextMenu(event);
                  }
                }}
                onSelectionContextMenu={(event) => openWorkflowContextMenu(event)}
                nodesDraggable={!controlKeyPressed}
                panActivationKeyCode="Control"
                panOnDrag={false}
                selectionMode={SelectionMode.Partial}
                selectionOnDrag
              >
                <MiniMap pannable zoomable />
                <Controls />
                <Background gap={24} size={1} />
              </ReactFlow>
              {contextMenu ? (
                <div
                  className="workflow-context-menu"
                  style={{
                    left: contextMenu.x,
                    top: contextMenu.y,
                  }}
                >
                  {nodeLookup.get(contextMenu.nodeId)?.data.block.kind === "compound" ? (
                    <>
                      <button
                        onClick={() => handleEditCompoundFunction(contextMenu.nodeId)}
                        type="button"
                      >
                        Edit compound function
                      </button>
                      <button
                        onClick={() => handleUncompoundFunction(contextMenu.nodeId)}
                        type="button"
                      >
                        Uncompound function
                      </button>
                    </>
                  ) : null}
                  <button
                    onClick={() => handleDuplicateSelectedNodes(contextMenu.nodeId)}
                    type="button"
                  >
                    Duplicate
                  </button>
                  <button
                    onClick={() => handleCreateCompoundFunction(contextMenu.nodeId)}
                    type="button"
                  >
                    Create compound function
                  </button>
                </div>
              ) : null}
            </div>

            {openedNode ? (
              <WorkflowInspector
                allNodeTestEntries={nodes.map((node) => ({
                  nodeId: node.id,
                  nodeName: node.data.block.displayName,
                  status: testStateByNodeId[node.id]?.status ?? "idle",
                  result: testStateByNodeId[node.id]?.result ?? null,
                  error: testStateByNodeId[node.id]?.error ?? null,
                }))}
                edges={edges}
                nodes={nodes}
                onClose={() => {
                  setOpenedNodeId(null);
                }}
                onNavigateToNode={(nodeId) => {
                  setSelectedNodeId(nodeId);
                  setOpenedNodeId(nodeId);
                }}
                onCancel={() => void handleCancelNodeExecution(openedNode.id)}
                onEditCompound={() => handleEditCompoundFunction(openedNode.id)}
                onRunTest={handleRunTest}
                onRunNode={(nodeId) => void handleRunTestForNode(nodeId)}
                onSaveCustomBlock={(displayName) => handleSaveCustomBlock(openedNode.id, displayName)}
                onUpdateParameter={handleUpdateParameter}
                onUpdateSettings={handleUpdateNodeSettings}
                previousNodeTestError={previousOpenedNodeTestState.error}
                previousNodeTestResult={previousOpenedNodeTestState.result}
                previousNodeTestStatus={previousOpenedNodeTestState.status}
                selectedNode={openedNode}
                testError={openedNodeTestState.error}
                testResult={openedNodeTestState.result}
                testStatus={openedNodeTestState.status}
              />
            ) : null}

            {workflowDrawer === "blocks" ? (
              <aside className="editor-drawer editor-drawer--workflow">
                <div className="editor-drawer__header">
                  <div>
                    <span>{quickAddSource ? "Add & connect" : "Add"}</span>
                    <strong>Blocks</strong>
                  </div>
                  <button
                    className="editor-drawer__close"
                    onClick={() => {
                      setWorkflowDrawer(null);
                      setQuickAddSource(null);
                    }}
                    type="button"
                  >
                    x
                  </button>
                </div>
                <WorkflowPalette
                  blocks={availableBlocks}
                  discoveryErrors={discoveryErrors.map((error) => `${error.folder_name}: ${error.message}`)}
                  onDeleteCustomBlock={(block) => void handleDeleteCustomBlock(block)}
                  onSelectBlock={quickAddSource ? handleQuickAddSelectBlock : undefined}
                />
              </aside>
            ) : null}
          </div>
        </div>

        {editingCompoundNode ? (
          <CompoundFunctionEditor
            key={editingCompoundNode.id}
            node={editingCompoundNode}
            testStateByNodeId={testStateByNodeId}
            onClose={() => setEditingCompoundNodeId(null)}
            onSave={handleSaveCompoundEdit}
            onRunNode={(innerNode) => void handleRunDetachedNode(innerNode)}
            onCancelNode={(innerNode) => void handleCancelNodeExecution(innerNode.id, innerNode)}
            onSaveCustomBlock={(innerNode, displayName) => handleSaveCustomBlock(innerNode.id, displayName, innerNode)}
          />
        ) : null}

    </section>
  );
}

interface WorkflowEditorCardProps {
  hardwareMapRevision: number;
  headerSlot: HTMLElement | null;
  isActive: boolean;
}

export function WorkflowEditorCard({ hardwareMapRevision, headerSlot, isActive }: WorkflowEditorCardProps) {
  return (
    <ReactFlowProvider>
      <WorkflowEditorSurface hardwareMapRevision={hardwareMapRevision} headerSlot={headerSlot} isActive={isActive} />
    </ReactFlowProvider>
  );
}
