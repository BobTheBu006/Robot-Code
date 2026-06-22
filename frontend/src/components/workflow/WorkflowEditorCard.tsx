import type { DragEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

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
  fetchEsp32Boards,
  fetchFunctions,
  fetchHardwareMap,
  fetchSavedWorkflow,
  flashEsp32BoardFirmware,
  saveEsp32CustomBlock,
  saveWorkflowToFile,
  testFunction,
} from "../../lib/api";
import {
  blockUsesUpstreamInput,
  formatDurationShort,
  formatWorkflowParameterValue,
  WORKFLOW_BLOCK_MIME,
  createBuiltInBlocks,
  createDefaultParameters,
  createDefaultNodeSettings,
  createBrokenWorkflowBlock,
  createHardwareBasicBlocks,
  createStarterWorkflow,
  createWorkflowNode,
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
  WorkflowInputDefinition,
  WorkflowNodeData,
  WorkflowParameterValue,
  WorkflowOutputDefinition,
} from "../../types/workflow";
import type { Esp32CustomBlockSaveResponse } from "../../types/esp32Builder";
import type { Esp32BoardSummary } from "../../types/esp32Builder";
import type { HardwareMap } from "../../types/hardwareMap";
import { Panel } from "../Panel";
import { StatusBadge } from "../StatusBadge";
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
type CompoundOutputBuild = WorkflowOutputDefinition & {
  sourceNodeId: string;
  sourceHandle?: string | null;
};

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

const nodeTypes: NodeTypes = {
  workflowBlock: WorkflowNode,
};

const edgeTypes: EdgeTypes = {
  workflowEdge: WorkflowEdge,
};

interface CompoundFunctionEditorProps {
  node: WorkflowFlowNode;
  onClose: () => void;
  onSave: (nodeId: string, innerNodes: WorkflowFlowNode[], innerEdges: Edge[]) => void;
}

function CompoundFunctionEditor({ node, onClose, onSave }: CompoundFunctionEditorProps) {
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
  const [selectedInnerNodeId, setSelectedInnerNodeId] = useState<string | null>(null);
  const selectedInnerNode = editorNodes.find((innerNode) => innerNode.id === selectedInnerNodeId) ?? null;
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
    setSelectedInnerNodeId((currentNodeId) => (currentNodeId === nodeId ? null : currentNodeId));
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

  function coerceEditorInputValue(
    input: WorkflowInputDefinition,
    value: string,
    checked = false,
  ): WorkflowParameterValue {
    if (input.type === "boolean") {
      return checked;
    }

    if (input.type === "number" && !value.includes("{{")) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : value;
    }

    return value;
  }

  const renderedEditorNodes = editorNodes.map((innerNode) => ({
    ...innerNode,
    data: {
      ...innerNode.data,
      executionStatus: "idle" as WorkflowExecutionStatus,
      executionEtaMs: null,
      onDelete: () => handleDeleteInnerNode(innerNode.id),
      onToggleActive: () => handleToggleInnerNodeActive(innerNode.id),
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
                setSelectedInnerNodeId(innerNode.id);
              }}
              onNodesChange={onEditorNodesChange}
              onPaneClick={() => setSelectedInnerNodeId(null)}
              panActivationKeyCode="Control"
              panOnDrag={false}
              selectionMode={SelectionMode.Partial}
              selectionOnDrag
            >
              <MiniMap pannable zoomable />
              <Controls />
              <Background gap={24} size={1} />
            </ReactFlow>
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

            {selectedInnerNode ? (
              <section>
                <h4>{selectedInnerNode.data.block.displayName}</h4>
                <div className="workflow-compound-editor__fields">
                  {getAllBlockInputs(selectedInnerNode.data.block).map((input) => (
                    <label className="workflow-compound-editor__field" key={input.key}>
                      <span>{input.label}</span>
                      {input.type === "select" ? (
                        <select
                          onChange={(event) => handleUpdateInnerParameter(selectedInnerNode.id, input, event.target.value)}
                          value={String(selectedInnerNode.data.parameters[input.key] ?? "")}
                        >
                          {input.options.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      ) : input.type === "boolean" ? (
                        <input
                          checked={Boolean(selectedInnerNode.data.parameters[input.key])}
                          onChange={(event) =>
                            handleUpdateInnerParameter(selectedInnerNode.id, input, coerceEditorInputValue(input, event.target.value, event.target.checked))}
                          type="checkbox"
                        />
                      ) : (
                        <input
                          onChange={(event) =>
                            handleUpdateInnerParameter(selectedInnerNode.id, input, coerceEditorInputValue(input, event.target.value))}
                          type="text"
                          value={formatWorkflowParameterValue(selectedInnerNode.data.parameters[input.key])}
                        />
                      )}
                    </label>
                  ))}
                </div>
              </section>
            ) : (
              <p className="workflow-compound-editor__empty">Select a block inside the compound to edit its parameters.</p>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}

interface WorkflowEditorSurfaceProps {
  hardwareMapRevision: number;
}

function WorkflowEditorSurface({ hardwareMapRevision }: WorkflowEditorSurfaceProps) {
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
  const [saveAsOpen, setSaveAsOpen] = useState(false);
  const [saveAsPath, setSaveAsPath] = useState("");
  const [saveAsName, setSaveAsName] = useState("active-workflow");
  const [workflowRunState, setWorkflowRunState] = useState<WorkflowRunState>({
    isRunning: false,
    phase: "idle",
    orderedNodeIds: [],
    currentNodeId: null,
    completedNodeIds: [],
    flashingBoardId: null,
  });
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

  const renderedNodes = nodes.map((node) => ({
    ...node,
    data: {
      ...node.data,
      executionStatus: testStateByNodeId[node.id]?.status ?? "idle",
      executionEtaMs: getNodeExecutionEta(node.id),
      onDelete: () => handleDeleteNode(node.id),
      onRun: () => void handleRunTestForNode(node.id),
      onCancel: () => void handleCancelNodeExecution(node.id),
      onToggleActive: () => handleToggleNodeActive(node.id),
    },
  }));
  const renderedEdges = edges.map((edge) => ({
    ...edge,
    data: {
      ...(edge.data ?? {}),
      isActive: edge.id === activeEdgeId,
      onDelete: handleDeleteEdge,
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
      } catch (error) {
        if (cancelled) {
          return;
        }

        const status = (error as Error & { status?: number }).status;
        if (status === 404) {
          return;
        }

        setFunctionsError(error instanceof Error ? error.message : "Could not load saved workflow file.");
      }
    }

    void loadSavedWorkflowFile();

    return () => {
      cancelled = true;
    };
  }, [setEdges, setNodes]);

  const robotActionBlocks = useMemo(
    () => discoveredFunctions.map((discoveredFunction) =>
      mapDiscoveredFunctionToBlock(discoveredFunction, esp32Boards, hardwareMap),
    ),
    [discoveredFunctions, esp32Boards, hardwareMap],
  );
  const hardwareBasicBlocks = useMemo(
    () => createHardwareBasicBlocks(hardwareMap),
    [hardwareMap],
  );
  const availableBlocks = useMemo(
    () => [...builtInBlocks, ...hardwareBasicBlocks, ...robotActionBlocks, ...compoundBlocks],
    [builtInBlocks, hardwareBasicBlocks, robotActionBlocks, compoundBlocks],
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
  const totalRunNodes = workflowRunState.orderedNodeIds.length;
  const completedRunNodes = workflowRunState.completedNodeIds.length;
  const remainingEstimateMs = workflowRunState.orderedNodeIds
    .filter((nodeId) => !workflowRunState.completedNodeIds.includes(nodeId))
    .reduce((total, nodeId) => {
      const node = nodeLookup.get(nodeId);
      return total + (node ? estimateNodeDuration(node) : 0);
    }, 0);
  const flashingBoard = workflowRunState.flashingBoardId
    ? esp32Boards.find((board) => board.board_id === workflowRunState.flashingBoardId)
    : null;
  const workflowStatusMessage = functionsError
    ? functionsError
    : workflowRunState.phase === "flashing"
      ? `Building and flashing ${flashingBoard?.display_name ?? workflowRunState.flashingBoardId ?? "ESP32 firmware"} before running the workflow.`
      : `${hardwareBasicBlocks.length} hardware basic block${hardwareBasicBlocks.length === 1 ? "" : "s"} and ${robotActionBlocks.length} advanced function${robotActionBlocks.length === 1 ? "" : "s"} available.`;

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
    try {
      const saveResult = await saveWorkflowToFile(
        nodes as WorkflowCanvasNode[],
        edges as WorkflowCanvasEdge[],
        saveAsPath,
        saveAsName,
      );
      setSaveAsOpen(false);
      setFunctionsError(`Saved workflow to ${saveResult.path}`);
    } catch (error) {
      setFunctionsError(error instanceof Error ? error.message : "Could not save workflow file.");
    }
  }

  async function handleLoadSavedWorkflow() {
    try {
      const savedWorkflow = await fetchSavedWorkflow();
      const parsedNodes = normalizeWorkflowNodes((savedWorkflow.workflow.nodes ?? []) as WorkflowFlowNode[]);
      const parsedEdges = (savedWorkflow.workflow.edges ?? []) as Edge[];
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

  function handleUpdateParameter(
    nodeId: string,
    input: WorkflowInputDefinition,
    value: WorkflowParameterValue,
  ) {
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
    const resolvedParameters = resolveWorkflowParameters(
      getAllBlockInputs(node.data.block),
      node.data.parameters,
      inputData,
      { blockResults },
    );

    if (node.data.block.kind === "broken") {
      return runBuiltInBlockTest(node.data.block, resolvedParameters, inputData);
    }

    if (node.data.block.kind === "compound") {
      return runCompoundBlock(node.data.block, resolvedParameters, inputData, blockResults, signal);
    }

    if (node.data.block.id === "delay") {
      const durationMs = Number(resolvedParameters.duration_ms ?? 0);
      if (Number.isFinite(durationMs) && durationMs > 0) {
        await new Promise((resolve) => window.setTimeout(resolve, durationMs));
      }
    }

    if (isClientExecutedBlock(node.data.block)) {
      return runBuiltInBlockTest(node.data.block, resolvedParameters, inputData);
    }

    return testFunction(node.data.block.id, resolvedParameters, inputData, signal);
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
  ): Promise<FunctionTestResponse> {
    const node = nodeLookup.get(nodeId);
    if (!node) {
      throw new Error(`Could not find node '${nodeId}' for execution.`);
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

  async function handleCancelNodeExecution(nodeId: string) {
    const node = nodeLookup.get(nodeId);
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

  async function handleSaveCustomBlock(
    nodeId: string,
    displayName: string,
  ): Promise<Esp32CustomBlockSaveResponse> {
    const node = nodeLookup.get(nodeId);
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
    if (block.builderBoardId) {
      boardIds.add(block.builderBoardId);
    }

    if (block.hardwareBoardId) {
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

  async function flashEsp32BoardsForRun(boardIds: string[]) {
    for (const boardId of boardIds) {
      setWorkflowRunState((currentState) => ({
        ...currentState,
        flashingBoardId: boardId,
      }));

      const response = await flashEsp32BoardFirmware(boardId);
      if (!response.ok) {
        throw new Error(`Could not flash ESP32 '${boardId}'. ${response.log || response.auto_reset_note}`);
      }
    }
  }

  async function handleRunAll() {
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
    const boardIdsToFlash = collectEsp32BoardIdsForRun(orderedNodeIds);

    setFunctionsError(null);
    setSelectedNodeId(null);
    setOpenedNodeId(null);
    setWorkflowRunState({
      isRunning: true,
      phase: boardIdsToFlash.length > 0 ? "flashing" : "running",
      orderedNodeIds,
      currentNodeId: null,
      completedNodeIds: [],
      flashingBoardId: null,
    });

    const resultsByNodeId = new Map<string, FunctionTestResponse>();

    try {
      await flashEsp32BoardsForRun(boardIdsToFlash);
      setWorkflowRunState((currentState) => ({
        ...currentState,
        phase: "running",
        flashingBoardId: null,
      }));

      for (const nodeId of orderedNodeIds) {
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

        setWorkflowRunState((currentState) => ({
          ...currentState,
          completedNodeIds: currentState.completedNodeIds.includes(nodeId)
            ? currentState.completedNodeIds
            : [...currentState.completedNodeIds, nodeId],
        }));
      }
    } catch (error) {
      setFunctionsError(error instanceof Error ? error.message : "Workflow run failed.");
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

  return (
    <Panel
      title="Workflow Editor"
      subtitle="Drag basic blocks, advanced robot functions, and compound functions onto the canvas, then connect them left to right."
      headerAction={
        <StatusBadge
          label={functionsStatus === "success" ? `${availableBlocks.length} Blocks` : functionsStatus === "loading" ? "Loading Blocks" : "Block Error"}
          tone={functionsStatus === "success" ? "online" : functionsStatus === "loading" ? "neutral" : "offline"}
        />
      }
    >
      <div className="workflow-editor">
        <div className="workflow-editor__toolbar">
          <div>
            <strong>Function discovery</strong>
            <p>
              {workflowStatusMessage}
            </p>
            <div className="workflow-editor__run-stats">
              <span>
                {workflowRunState.phase === "flashing"
                  ? "Preparing ESP32 firmware"
                  : workflowRunState.isRunning
                  ? `${completedRunNodes} / ${totalRunNodes} blocks executed`
                  : `${nodes.length} blocks on canvas`}
              </span>
              <span>
                {workflowRunState.phase === "flashing"
                  ? "Workflow will start after flashing"
                  : workflowRunState.isRunning
                  ? `~${formatDurationShort(remainingEstimateMs)} remaining`
                  : `Est. total ${formatDurationShort(nodes.reduce((total, node) => total + estimateNodeDuration(node), 0))}`}
              </span>
            </div>
          </div>

          <div className="workflow-editor__actions">
            <button
              className="workflow-editor__action workflow-editor__action--primary"
              disabled={workflowRunState.isRunning}
              onClick={() => void handleRunAll()}
              type="button"
            >
              {workflowRunState.phase === "flashing" ? "Flashing ESP32..." : workflowRunState.isRunning ? "Running flow..." : "Run all"}
            </button>
            <button
              className="workflow-editor__action"
              onClick={() => setSaveAsOpen((currentValue) => !currentValue)}
              type="button"
            >
              Save as
            </button>
            <button className="workflow-editor__action" onClick={() => void handleLoadSavedWorkflow()} type="button">Load saved</button>
            <button className="workflow-editor__action" onClick={handleResetWorkflow} type="button">Reset canvas</button>
          </div>
        </div>

        {saveAsOpen ? (
          <div className="workflow-editor__save-as">
            <label className="workflow-editor__save-field">
              <span>Path</span>
              <input
                onChange={(event) => setSaveAsPath(event.target.value)}
                placeholder="optional/subfolder"
                type="text"
                value={saveAsPath}
              />
            </label>
            <label className="workflow-editor__save-field">
              <span>Name</span>
              <input
                onChange={(event) => setSaveAsName(event.target.value)}
                placeholder="workflow-name"
                type="text"
                value={saveAsName}
              />
            </label>
            <div className="workflow-editor__save-actions">
              <button className="workflow-editor__action" onClick={() => void handleSaveWorkflow()} type="button">
                Save
              </button>
              <button className="workflow-editor__action" onClick={() => setSaveAsOpen(false)} type="button">
                Cancel
              </button>
            </div>
          </div>
        ) : null}

        <div className="workflow-editor__surface">
          <div
            className="workflow-editor__canvas-shell"
            onDragOver={handleDragOver}
            onDrop={handleDrop}
          >
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
                  setActiveEdgeId(null);
                  setContextMenu(null);
                }}
                onPaneContextMenu={(event) => {
                  if (nodes.some((node) => node.selected)) {
                    openWorkflowContextMenu(event);
                  }
                }}
                onSelectionContextMenu={(event) => openWorkflowContextMenu(event)}
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
                onClose={() => setOpenedNodeId(null)}
                onNavigateToNode={(nodeId) => {
                  setSelectedNodeId(nodeId);
                  setOpenedNodeId(nodeId);
                }}
                onCancel={() => void handleCancelNodeExecution(openedNode.id)}
                onEditCompound={() => handleEditCompoundFunction(openedNode.id)}
                onRunTest={handleRunTest}
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
          </div>

          <WorkflowPalette
            blocks={availableBlocks}
            discoveryErrors={discoveryErrors.map((error) => `${error.folder_name}: ${error.message}`)}
            onDeleteCustomBlock={(block) => void handleDeleteCustomBlock(block)}
          />
        </div>

        {editingCompoundNode ? (
          <CompoundFunctionEditor
            key={editingCompoundNode.id}
            node={editingCompoundNode}
            onClose={() => setEditingCompoundNodeId(null)}
            onSave={handleSaveCompoundEdit}
          />
        ) : null}

      </div>
    </Panel>
  );
}

interface WorkflowEditorCardProps {
  hardwareMapRevision: number;
}

export function WorkflowEditorCard({ hardwareMapRevision }: WorkflowEditorCardProps) {
  return (
    <ReactFlowProvider>
      <WorkflowEditorSurface hardwareMapRevision={hardwareMapRevision} />
    </ReactFlowProvider>
  );
}
