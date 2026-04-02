import type { Edge, Node, XYPosition } from "@xyflow/react";

import type {
  DiscoveredFunctionDefinition,
  FunctionTestResponse,
  WorkflowBlockDefinition,
  WorkflowFailureMode,
  WorkflowInputDefinition,
  WorkflowNodeData,
  WorkflowNodeSettings,
  WorkflowOutputDefinition,
  WorkflowParameterValue,
} from "../types/workflow";

export const WORKFLOW_STORAGE_KEY = "robot-control.workflow-editor";
export const WORKFLOW_BLOCK_MIME = "application/x-robot-workflow-block";

interface WorkflowResolutionContext {
  blockResults?: Record<string, Record<string, unknown> | null | undefined>;
}

const ERROR_OUTPUT: WorkflowOutputDefinition = {
  key: "error",
  label: "Error",
  type: "flow",
  description: "Continue down the error path when this block fails.",
};

function buildInput(
  key: string,
  label: string,
  type: WorkflowInputDefinition["type"],
  defaultValue: WorkflowParameterValue,
  description?: string,
  options: WorkflowInputDefinition["options"] = [],
): WorkflowInputDefinition {
  return {
    key,
    label,
    type,
    description,
    required: true,
    default: defaultValue,
    placeholder: null,
    options,
  };
}

function buildOutput(
  key: string,
  label: string,
  type: string,
  description?: string,
): WorkflowOutputDefinition {
  return {
    key,
    label,
    type,
    description,
  };
}

function resolveInputPath(
  inputData: Record<string, unknown> | null | undefined,
  path: string,
): unknown {
  if (!inputData) {
    return null;
  }

  if (!path.trim()) {
    return inputData;
  }

  const segments = path
    .split(".")
    .map((segment) => segment.trim())
    .filter(Boolean);

  let current: unknown = inputData;
  for (const segment of segments) {
    if (!current || typeof current !== "object" || !(segment in current)) {
      return null;
    }

    current = (current as Record<string, unknown>)[segment];
  }

  return current;
}

function coerceResolvedValue(
  value: unknown,
  inputType: WorkflowInputDefinition["type"],
): WorkflowParameterValue {
  if (inputType === "number") {
    if (typeof value === "number") {
      return value;
    }

    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
      throw new Error(`Expected a number-compatible value, received '${String(value)}'.`);
    }

    return parsed;
  }

  if (inputType === "boolean") {
    if (typeof value === "boolean") {
      return value;
    }

    if (typeof value === "string") {
      const normalized = value.trim().toLowerCase();
      if (normalized === "true") {
        return true;
      }

      if (normalized === "false") {
        return false;
      }
    }

    throw new Error(`Expected a boolean-compatible value, received '${String(value)}'.`);
  }

  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  return JSON.stringify(value);
}

function stringifyResolvedValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  return JSON.stringify(value);
}

function resolveExpressionReference(
  expressionBody: string,
  inputData: Record<string, unknown> | null | undefined,
  context: WorkflowResolutionContext = {},
): unknown {
  const trimmed = expressionBody.trim();
  const normalized = trimmed
    .replace(/^\$json\./, "input.")
    .replace(/^\$input\./, "input.")
    .replace(/^\$blocks\./, "blocks.")
    .replace(/^previous\./, "input.")
    .replace(/^json\./, "input.");

  if (normalized === "input" || normalized === "$json" || normalized === "$input" || normalized === "previous" || normalized === "json") {
    return inputData ?? null;
  }

  if (normalized === "blocks" || normalized === "$blocks") {
    return context.blockResults ?? null;
  }

  if (normalized.startsWith("blocks.")) {
    return resolveInputPath(context.blockResults ?? null, normalized.slice("blocks.".length));
  }

  const path = normalized.startsWith("input.") ? normalized.slice("input.".length) : normalized;
  return resolveInputPath(inputData, path);
}

export function resolveWorkflowParameters(
  inputs: WorkflowInputDefinition[],
  parameters: Record<string, WorkflowParameterValue>,
  inputData: Record<string, unknown> | null | undefined,
  context: WorkflowResolutionContext = {},
): Record<string, WorkflowParameterValue> {
  const resolvedParameters: Record<string, WorkflowParameterValue> = {};

  for (const input of inputs) {
    const rawValue = parameters[input.key];

    if (typeof rawValue !== "string") {
      resolvedParameters[input.key] = rawValue;
      continue;
    }

    const expressionMatches = [...rawValue.matchAll(/\{\{([^}]+)\}\}/g)];
    if (expressionMatches.length === 0) {
      resolvedParameters[input.key] = input.type === "number"
        ? coerceResolvedValue(rawValue, input.type)
        : input.type === "boolean"
          ? coerceResolvedValue(rawValue, input.type)
          : rawValue;
      continue;
    }

    const wholeExpressionMatch = rawValue.trim().match(/^\{\{([^}]+)\}\}$/);
    if (wholeExpressionMatch) {
      const resolvedValue = resolveExpressionReference(wholeExpressionMatch[1], inputData, context);
      if (resolvedValue === null || resolvedValue === undefined) {
        throw new Error(`Could not resolve expression '${rawValue}' for '${input.label}'.`);
      }

      resolvedParameters[input.key] = coerceResolvedValue(resolvedValue, input.type);
      continue;
    }

    let nextValue = rawValue;
    for (const match of expressionMatches) {
      const token = match[0];
      const body = match[1];
      const resolvedValue = resolveExpressionReference(body, inputData, context);
      if (resolvedValue === null || resolvedValue === undefined) {
        throw new Error(`Could not resolve expression '${token}' for '${input.label}'.`);
      }

      nextValue = nextValue.replace(token, stringifyResolvedValue(resolvedValue));
    }

    resolvedParameters[input.key] = coerceResolvedValue(nextValue, input.type);
  }

  return resolvedParameters;
}

export function createBuiltInBlocks(): WorkflowBlockDefinition[] {
  return [
    {
      id: "start",
      displayName: "Start",
      category: "Trigger",
      description: "Entry point for a workflow.",
      version: "1.0.0",
      kind: "built-in",
      acceptsInput: false,
      accent: "#1b7f5c",
      inputs: [],
      outputs: [buildOutput("next", "Next", "flow", "Continue to the next block in the workflow.")],
    },
    {
      id: "if",
      displayName: "If",
      category: "Logic",
      description: "Branch the workflow based on a condition.",
      version: "1.0.0",
      kind: "built-in",
      acceptsInput: true,
      accent: "#a85d13",
      inputs: [buildInput("condition", "Condition", "string", "", "Expression or variable to evaluate.")],
      outputs: [
        buildOutput("true", "True", "flow", "Path used when the condition evaluates to true."),
        buildOutput("false", "False", "flow", "Path used when the condition evaluates to false."),
      ],
    },
    {
      id: "if_else",
      displayName: "If / Else",
      category: "Logic",
      description: "Split into explicit true and false branches.",
      version: "1.0.0",
      kind: "built-in",
      acceptsInput: true,
      accent: "#8e4ec6",
      inputs: [buildInput("condition", "Condition", "string", "", "Condition to evaluate before choosing a branch.")],
      outputs: [
        buildOutput("true", "True", "flow", "Explicit true branch."),
        buildOutput("false", "False", "flow", "Explicit false branch."),
      ],
    },
    {
      id: "while",
      displayName: "While",
      category: "Logic",
      description: "Repeat the loop body while the condition remains true.",
      version: "1.0.0",
      kind: "built-in",
      acceptsInput: true,
      accent: "#c63b63",
      inputs: [buildInput("condition", "Condition", "string", "", "Loop condition checked before each iteration.")],
      outputs: [
        buildOutput("loop", "Loop", "flow", "Continue into the loop body."),
        buildOutput("done", "Done", "flow", "Continue after the loop finishes."),
      ],
    },
    {
      id: "for",
      displayName: "For",
      category: "Logic",
      description: "Run the loop body a fixed number of times.",
      version: "1.0.0",
      kind: "built-in",
      acceptsInput: true,
      accent: "#175c96",
      inputs: [buildInput("iterations", "Iterations", "number", 1, "Number of iterations to execute.")],
      outputs: [
        buildOutput("loop", "Loop", "flow", "Continue into the current iteration."),
        buildOutput("done", "Done", "flow", "Continue after all iterations complete."),
      ],
    },
    {
      id: "loop_over",
      displayName: "Loop Over",
      category: "Logic",
      description: "Iterate over an upstream array or object input set.",
      version: "1.0.0",
      kind: "built-in",
      acceptsInput: true,
      accent: "#0f6f66",
      inputs: [
        buildInput("source_path", "Source Path", "string", "", "Dot path into the upstream input. Leave blank to loop over the full input object."),
        buildInput("item_label", "Item Label", "string", "item", "Name to use for the current item in later expressions."),
      ],
      outputs: [
        buildOutput("loop", "Loop", "flow", "Continue into the loop body for each item."),
        buildOutput("done", "Done", "flow", "Continue after the collection is exhausted."),
      ],
    },
    {
      id: "delay",
      displayName: "Delay / Wait",
      category: "Logic",
      description: "Pause execution for a number of milliseconds.",
      version: "1.0.0",
      kind: "built-in",
      acceptsInput: true,
      accent: "#48711f",
      inputs: [buildInput("duration_ms", "Duration (ms)", "number", 1000, "How long to wait before continuing.")],
      outputs: [buildOutput("next", "Next", "flow", "Continue when the wait period completes.")],
    },
  ];
}

export function mapDiscoveredFunctionToBlock(
  discoveredFunction: DiscoveredFunctionDefinition,
): WorkflowBlockDefinition {
  return {
    id: discoveredFunction.manifest.id,
    displayName: discoveredFunction.manifest.display_name,
    category: discoveredFunction.manifest.category,
    description: discoveredFunction.manifest.description,
    version: discoveredFunction.manifest.version,
    kind: "robot-action",
    acceptsInput: true,
    accent: "#0e7490",
    inputs: discoveredFunction.manifest.inputs,
    outputs:
      discoveredFunction.manifest.outputs.length > 0
        ? discoveredFunction.manifest.outputs.map((output) => ({
            key: output.key,
            label: output.label,
            type: output.type,
            description: output.description,
          }))
        : [buildOutput("next", "Next", "flow", "Continue to the next workflow node.")],
  };
}

export function createDefaultParameters(
  inputs: WorkflowInputDefinition[],
): Record<string, WorkflowParameterValue> {
  const parameters: Record<string, WorkflowParameterValue> = {};

  for (const input of inputs) {
    if (input.default !== undefined && input.default !== null) {
      parameters[input.key] = input.default;
      continue;
    }

    if (input.type === "boolean") {
      parameters[input.key] = false;
      continue;
    }

    if (input.type === "number") {
      parameters[input.key] = 0;
      continue;
    }

    if (input.type === "select") {
      parameters[input.key] = input.options[0]?.value ?? "";
      continue;
    }

    parameters[input.key] = "";
  }

  return parameters;
}

export function createDefaultNodeSettings(): WorkflowNodeSettings {
  return {
    failureMode: "stop_flow",
    retryCount: 0,
  };
}

export function getWorkflowNodeOutputs(nodeData: WorkflowNodeData): WorkflowOutputDefinition[] {
  if (nodeData.settings.failureMode !== "separate_path") {
    return nodeData.block.outputs;
  }

  if (nodeData.block.outputs.some((output) => output.key === ERROR_OUTPUT.key)) {
    return nodeData.block.outputs;
  }

  return [...nodeData.block.outputs, ERROR_OUTPUT];
}

export function normalizeFailureMode(value: string | undefined): WorkflowFailureMode {
  return value === "separate_path" ? "separate_path" : "stop_flow";
}

export function normalizeRetryCount(value: number | undefined): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 0;
  }

  return Math.max(0, Math.floor(value));
}

export function createWorkflowNode(
  block: WorkflowBlockDefinition,
  position: XYPosition,
  suffix = Math.random().toString(36).slice(2, 7),
): Node<WorkflowNodeData> {
  return {
    id: `${block.id}-${suffix}`,
    type: "workflowBlock",
    position,
    data: {
      block,
      parameters: createDefaultParameters(block.inputs),
      settings: createDefaultNodeSettings(),
      isActive: true,
      runCount: 0,
      benchmarkDurationMs: null,
      lastDurationMs: null,
    },
  };
}

export function createStarterWorkflow(): {
  nodes: Array<Node<WorkflowNodeData>>;
  edges: Edge[];
} {
  const builtInBlocks = createBuiltInBlocks();
  const start = builtInBlocks.find((block) => block.id === "start");
  const delay = builtInBlocks.find((block) => block.id === "delay");
  const ifElse = builtInBlocks.find((block) => block.id === "if_else");

  if (!start || !delay || !ifElse) {
    return { nodes: [], edges: [] };
  }

  const startNode = createWorkflowNode(start, { x: 80, y: 160 }, "seed-start");
  const delayNode = createWorkflowNode(delay, { x: 350, y: 120 }, "seed-delay");
  const branchNode = createWorkflowNode(ifElse, { x: 620, y: 120 }, "seed-branch");

  return {
    nodes: [startNode, delayNode, branchNode],
    edges: [
      {
        id: "edge-start-delay",
        source: startNode.id,
        target: delayNode.id,
        sourceHandle: "next",
        type: "workflowEdge",
      },
      {
        id: "edge-delay-branch",
        source: delayNode.id,
        target: branchNode.id,
        sourceHandle: "next",
        type: "workflowEdge",
      },
    ],
  };
}

export function serializeWorkflow(nodes: Array<Node<WorkflowNodeData>>, edges: Edge[]): string {
  return JSON.stringify(
    {
      version: 1,
      nodes,
      edges,
    },
    null,
    2,
  );
}

export function formatWorkflowParameterValue(value: WorkflowParameterValue | undefined): string {
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }

  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : "0";
  }

  return value ?? "";
}

export function formatDurationShort(durationMs: number | null | undefined): string {
  if (!durationMs || durationMs <= 0) {
    return "0s";
  }

  if (durationMs < 1000) {
    return `${Math.max(1, Math.round(durationMs))}ms`;
  }

  const seconds = durationMs / 1000;
  if (seconds < 60) {
    return `${seconds.toFixed(seconds >= 10 ? 0 : 1)}s`;
  }

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  return `${minutes}m ${remainingSeconds}s`;
}

export function runBuiltInBlockTest(
  block: WorkflowBlockDefinition,
  parameters: Record<string, WorkflowParameterValue>,
  inputData?: Record<string, unknown> | null,
): FunctionTestResponse {
  if (block.id === "start") {
    return {
      function_id: block.id,
      ok: true,
      inputs: parameters,
      input_data: inputData ?? null,
      result: {
        status: "ready",
        next_output: "next",
      },
      error: null,
    };
  }

  if (block.id === "delay") {
    return {
      function_id: block.id,
      ok: true,
      inputs: parameters,
      input_data: inputData ?? null,
      result: {
        status: "simulated",
        waited_ms: parameters.duration_ms ?? 0,
        next_output: "next",
      },
      error: null,
    };
  }

  if (block.id === "for") {
    return {
      function_id: block.id,
      ok: true,
      inputs: parameters,
      input_data: inputData ?? null,
      result: {
        status: "simulated",
        iterations: parameters.iterations ?? 0,
        outputs: ["loop", "done"],
      },
      error: null,
    };
  }

  if (block.id === "loop_over") {
    const sourcePath = formatWorkflowParameterValue(parameters.source_path);
    const itemLabel = formatWorkflowParameterValue(parameters.item_label) || "item";
    const resolvedValue = resolveInputPath(inputData ?? null, sourcePath);

    const items = Array.isArray(resolvedValue)
      ? resolvedValue
      : resolvedValue && typeof resolvedValue === "object"
        ? Object.entries(resolvedValue as Record<string, unknown>).map(([key, value]) => ({ key, value }))
        : [];

    return {
      function_id: block.id,
      ok: true,
      inputs: parameters,
      input_data: inputData ?? null,
      result: {
        status: "simulated",
        item_label: itemLabel,
        source_path: sourcePath,
        item_count: items.length,
        current_item: items[0] ?? null,
        items,
        outputs: ["loop", "done"],
      },
      error: null,
    };
  }

  if (block.id === "if" || block.id === "if_else" || block.id === "while") {
    const condition = formatWorkflowParameterValue(parameters.condition);

    return {
      function_id: block.id,
      ok: true,
      inputs: parameters,
      input_data: inputData ?? null,
      result: {
        status: "simulated",
        condition,
        input_data: inputData ?? null,
        outputs: block.outputs.map((output) => output.key),
      },
      error: null,
    };
  }

  return {
    function_id: block.id,
    ok: true,
    inputs: parameters,
    input_data: inputData ?? null,
    result: {
      status: "simulated",
      input_data: inputData ?? null,
      outputs: block.outputs.map((output) => output.key),
    },
    error: null,
  };
}

export function blockUsesUpstreamInput(block: WorkflowBlockDefinition): boolean {
  return (
    block.kind === "built-in"
    && block.id !== "start"
    && block.id !== "delay"
  );
}
