import type { DragEvent } from "react";
import { useEffect, useRef, useState } from "react";

import {
  addEdge,
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
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
  deleteEsp32CustomBlock,
  fetchEsp32Boards,
  fetchFunctions,
  fetchSavedWorkflow,
  saveEsp32CustomBlock,
  saveWorkflowToFile,
  testFunction,
} from "../../lib/api";
import {
  blockUsesUpstreamInput,
  formatDurationShort,
  WORKFLOW_BLOCK_MIME,
  createBuiltInBlocks,
  createDefaultParameters,
  createDefaultNodeSettings,
  createStarterWorkflow,
  createWorkflowNode,
  getAllBlockInputs,
  resolveWorkflowParameters,
  normalizeFailureMode,
  normalizeRetryCount,
  mapDiscoveredFunctionToBlock,
  runBuiltInBlockTest,
  serializeWorkflow,
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
} from "../../types/workflow";
import type { Esp32CustomBlockSaveResponse } from "../../types/esp32Builder";
import type { Esp32BoardSummary } from "../../types/esp32Builder";
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
  orderedNodeIds: string[];
  currentNodeId: string | null;
  completedNodeIds: string[];
};

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

const nodeTypes: NodeTypes = {
  workflowBlock: WorkflowNode,
};

const edgeTypes: EdgeTypes = {
  workflowEdge: WorkflowEdge,
};

function WorkflowEditorSurface() {
  const starterWorkflow = createStarterWorkflow();
  const builtInBlocks = createBuiltInBlocks();
  const [nodes, setNodes, onNodesChange] = useNodesState<WorkflowFlowNode>(starterWorkflow.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(starterWorkflow.edges);
  const [discoveredFunctions, setDiscoveredFunctions] = useState<DiscoveredFunctionDefinition[]>([]);
  const [esp32Boards, setEsp32Boards] = useState<Esp32BoardSummary[]>([]);
  const [discoveryErrors, setDiscoveryErrors] = useState<FunctionDiscoveryError[]>([]);
  const [functionsStatus, setFunctionsStatus] = useState<"loading" | "success" | "error">("loading");
  const [functionsError, setFunctionsError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [openedNodeId, setOpenedNodeId] = useState<string | null>(null);
  const [activeEdgeId, setActiveEdgeId] = useState<string | null>(null);
  const [testStateByNodeId, setTestStateByNodeId] = useState<Record<string, NodeTestState>>({});
  const testStateByNodeIdRef = useRef<Record<string, NodeTestState>>({});
  const [workflowJson, setWorkflowJson] = useState(() => serializeWorkflow(starterWorkflow.nodes, starterWorkflow.edges));
  const [saveAsOpen, setSaveAsOpen] = useState(false);
  const [saveAsPath, setSaveAsPath] = useState("");
  const [saveAsName, setSaveAsName] = useState("active-workflow");
  const [workflowRunState, setWorkflowRunState] = useState<WorkflowRunState>({
    isRunning: false,
    orderedNodeIds: [],
    currentNodeId: null,
    completedNodeIds: [],
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

  useEffect(() => {
    const cancellationToken = { cancelled: false };
    void loadFunctions(cancellationToken);
    void loadBoards(cancellationToken);

    return () => {
      cancellationToken.cancelled = true;
    };
  }, []);

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
        setWorkflowJson(serializeWorkflow(parsedNodes, parsedEdges));
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

  const robotActionBlocks = discoveredFunctions.map((discoveredFunction) =>
    mapDiscoveredFunctionToBlock(discoveredFunction, esp32Boards),
  );
  const availableBlocks = [...builtInBlocks, ...robotActionBlocks];
  const openedNode = nodes.find((node) => node.id === openedNodeId) ?? null;
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

  useEffect(() => {
    const blockLookup = new Map(availableBlocks.map((block) => [block.id, block]));
    setNodes((currentNodes) =>
      currentNodes.map((node) => {
        const latestBlock = blockLookup.get(node.data.block.id);
        if (!latestBlock) {
          return node;
        }

        return {
          ...node,
          data: {
            ...node.data,
            block: latestBlock,
            parameters: {
              ...createDefaultParameters(getAllBlockInputs(latestBlock)),
              ...node.data.parameters,
            },
          },
        };
      }),
    );
  }, [discoveredFunctions, setNodes]);

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

  async function handleSaveWorkflow() {
    const nextJson = serializeWorkflow(nodes, edges);
    setWorkflowJson(nextJson);
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

  function handleRefreshJson() {
    setWorkflowJson(serializeWorkflow(nodes, edges));
  }

  async function handleLoadSavedWorkflow() {
    try {
      const savedWorkflow = await fetchSavedWorkflow();
      const parsedNodes = normalizeWorkflowNodes((savedWorkflow.workflow.nodes ?? []) as WorkflowFlowNode[]);
      const parsedEdges = (savedWorkflow.workflow.edges ?? []) as Edge[];
      setNodes(parsedNodes);
      setEdges(parsedEdges);
      setSelectedNodeId(null);
      setOpenedNodeId(null);
      setActiveEdgeId(null);
      setWorkflowJson(serializeWorkflow(parsedNodes, parsedEdges));
      setFunctionsError(`Loaded workflow from ${savedWorkflow.path}`);
    } catch (error) {
      setFunctionsError(error instanceof Error ? error.message : "Could not load saved workflow file.");
    }
  }

  function handleLoadJson() {
    try {
      const parsed = JSON.parse(workflowJson) as { nodes: WorkflowFlowNode[]; edges: Edge[] };
      setNodes(normalizeWorkflowNodes(parsed.nodes ?? []));
      setEdges(parsed.edges ?? []);
      setSelectedNodeId(null);
      setOpenedNodeId(null);
      setActiveEdgeId(null);
    } catch {
      setFunctionsError("Workflow JSON could not be parsed.");
    }
  }

  function handleResetWorkflow() {
    const nextStarterWorkflow = createStarterWorkflow();
    setNodes(nextStarterWorkflow.nodes);
    setEdges(nextStarterWorkflow.edges);
    setSelectedNodeId(null);
    setOpenedNodeId(null);
    setActiveEdgeId(null);
    setWorkflowJson(serializeWorkflow(nextStarterWorkflow.nodes, nextStarterWorkflow.edges));
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
  ): Promise<FunctionTestResponse> {
    const resolvedParameters = resolveWorkflowParameters(
      getAllBlockInputs(node.data.block),
      node.data.parameters,
      inputData,
      { blockResults },
    );

    if (node.data.block.kind === "built-in" && node.data.block.id === "delay") {
      const durationMs = Number(resolvedParameters.duration_ms ?? 0);
      if (Number.isFinite(durationMs) && durationMs > 0) {
        await new Promise((resolve) => window.setTimeout(resolve, durationMs));
      }
    }

    if (node.data.block.kind === "built-in") {
      return runBuiltInBlockTest(node.data.block, resolvedParameters, inputData);
    }

    return testFunction(node.data.block.id, resolvedParameters, inputData);
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

    try {
      const blockResults = buildBlockResultLookup();
      const result = await runSingleNode(node, inputData, blockResults);
      const durationMs = performance.now() - startedAt;
      recordNodeDuration(nodeId, durationMs);

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
      const message = error instanceof Error ? error.message : "Block test failed.";
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
    await Promise.all([loadFunctions(), loadBoards()]);
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

    setFunctionsError(null);
    setSelectedNodeId(null);
    setOpenedNodeId(null);
    setWorkflowRunState({
      isRunning: true,
      orderedNodeIds,
      currentNodeId: null,
      completedNodeIds: [],
    });

    const resultsByNodeId = new Map<string, FunctionTestResponse>();

    try {
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
        currentNodeId: null,
      }));
    }
  }

  return (
    <Panel
      title="Workflow Editor"
      subtitle="Drag built-in control nodes and discovered robot actions onto the canvas, then connect them left to right."
      headerAction={
        <StatusBadge
          label={functionsStatus === "success" ? `${robotActionBlocks.length} Robot Blocks` : functionsStatus === "loading" ? "Loading Blocks" : "Block Error"}
          tone={functionsStatus === "success" ? "online" : functionsStatus === "loading" ? "neutral" : "offline"}
        />
      }
    >
      <div className="workflow-editor">
        <div className="workflow-editor__toolbar">
          <div>
            <strong>Function discovery</strong>
            <p>
              {functionsError
                ? functionsError
                : `${robotActionBlocks.length} custom robot action block${robotActionBlocks.length === 1 ? "" : "s"} discovered from backend folders.`}
            </p>
            <div className="workflow-editor__run-stats">
              <span>
                {workflowRunState.isRunning
                  ? `${completedRunNodes} / ${totalRunNodes} blocks executed`
                  : `${nodes.length} blocks on canvas`}
              </span>
              <span>
                {workflowRunState.isRunning
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
              {workflowRunState.isRunning ? "Running flow..." : "Run all"}
            </button>
            <button
              className="workflow-editor__action"
              onClick={() => setSaveAsOpen((currentValue) => !currentValue)}
              type="button"
            >
              Save as
            </button>
            <button className="workflow-editor__action" onClick={() => void handleLoadSavedWorkflow()} type="button">Load saved</button>
            <button className="workflow-editor__action" onClick={handleRefreshJson} type="button">Refresh JSON</button>
            <button className="workflow-editor__action" onClick={handleLoadJson} type="button">Load JSON</button>
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
                }}
                onNodeClick={(event, node) => {
                  event.stopPropagation();
                  setSelectedNodeId(node.id);
                  setOpenedNodeId(null);
                  setActiveEdgeId(null);
                }}
                onNodeDoubleClick={(event, node) => {
                  event.stopPropagation();
                  setSelectedNodeId(node.id);
                  setOpenedNodeId(node.id);
                  setActiveEdgeId(null);
                }}
                onNodesChange={onNodesChange}
                onPaneClick={() => {
                  setSelectedNodeId(null);
                  setOpenedNodeId(null);
                  setActiveEdgeId(null);
                }}
              >
                <MiniMap pannable zoomable />
                <Controls />
                <Background gap={24} size={1} />
              </ReactFlow>
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

        <div className="workflow-editor__json">
          <div className="workflow-editor__json-header">
            <strong>Workflow JSON</strong>
            <span>Simple local persistence model for this step.</span>
          </div>
          <textarea
            onChange={(event) => setWorkflowJson(event.target.value)}
            value={workflowJson}
          />
        </div>
      </div>
    </Panel>
  );
}

export function WorkflowEditorCard() {
  return (
    <ReactFlowProvider>
      <WorkflowEditorSurface />
    </ReactFlowProvider>
  );
}
