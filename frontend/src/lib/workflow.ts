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
import type { Esp32BoardSummary } from "../types/esp32Builder";
import type { HardwareDeviceMapping, HardwareMap, HardwarePinMapping } from "../types/hardwareMap";

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
const BASIC_BLOCK_CATEGORY = "Basic Blocks";
const ADVANCED_FUNCTION_CATEGORY = "Advanced Functions";
const BROKEN_REFERENCE_CATEGORY = "Broken References";

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

function buildHardwarePinOptions(
  hardwareMap: HardwareMap | null,
): Array<WorkflowInputDefinition["options"][number] & { inputKey?: string | null }> {
  if (!hardwareMap) {
    return [];
  }

  const boardLookup = new Map(hardwareMap.boards.map((board) => [board.id, board]));

  return hardwareMap.devices.flatMap((device) => {
    const board = boardLookup.get(device.board_id);

    return device.pins
      .filter((pin): pin is HardwarePinMapping & { gpio: string } => Boolean(pin.gpio) && pin.gpio !== "-" && pin.signal !== "-")
      .map((pin) => ({
        label: `${device.name} - ${pin.signal} GPIO ${pin.gpio}${board ? ` (${board.label})` : ""}`,
        value: pin.gpio,
        inputKey: pin.function_input_key ?? null,
      }));
  });
}

function getServoRange(device: HardwareDeviceMapping): { min: number; max: number } {
  const min = Number(device.rotation_min_deg ?? -5);
  const max = Number(device.rotation_max_deg ?? 175);

  return {
    min: Number.isFinite(min) ? min : -5,
    max: Number.isFinite(max) ? max : 175,
  };
}

function getPumpCalibrationMlPer200Steps(device: HardwareDeviceMapping): number | null {
  const calibration = Number(device.calibration_ml_per_200_steps);
  return Number.isFinite(calibration) && calibration > 0 ? calibration : null;
}

function getHardwareBasicBlockId(device: Pick<HardwareDeviceMapping, "id" | "kind">): string | null {
  if (device.kind === "stepper_motor") {
    return `basic-stepper-${device.id}`;
  }

  if (device.kind === "servo") {
    return `basic-servo-${device.id}`;
  }

  if (device.kind === "sensor") {
    return `basic-sensor-${device.id}`;
  }

  return null;
}

export function createBrokenWorkflowBlock(
  originalBlock: WorkflowBlockDefinition,
  reason?: string,
): WorkflowBlockDefinition {
  if (originalBlock.kind === "broken") {
    return originalBlock;
  }

  const originalKind = originalBlock.kind;
  const inferredReason = reason ?? (
    originalBlock.hardwareDeviceId
      ? `The hardware device '${originalBlock.hardwareDeviceId}' is no longer present in the Hardware Map.`
      : `The block '${originalBlock.id}' is not available in the current function, module, or hardware block library.`
  );
  const suggestedFix = originalBlock.hardwareDeviceId
    ? "Restore the missing device in the Hardware Map, or replace this block with a currently available hardware block."
    : "Restore or reinstall the missing function/module, or replace this block with a currently available block.";

  return {
    ...originalBlock,
    category: BROKEN_REFERENCE_CATEGORY,
    displayName: `Missing: ${originalBlock.displayName}`,
    description: inferredReason,
    kind: "broken",
    acceptsInput: originalBlock.acceptsInput,
    accent: "#b42318",
    inputs: originalBlock.inputs ?? [],
    advancedInputs: originalBlock.advancedInputs ?? [],
    outputs: originalBlock.outputs.length > 0
      ? originalBlock.outputs
      : [buildOutput("next", "Next", "flow", "Preserved placeholder output.")],
    missingReference: {
      originalId: originalBlock.id,
      originalKind,
      reason: inferredReason,
      suggestedFix,
    },
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
      category: BASIC_BLOCK_CATEGORY,
      description: "Entry point for a workflow.",
      version: "1.0.0",
      kind: "basic",
      acceptsInput: false,
      accent: "#1b7f5c",
      inputs: [],
      outputs: [buildOutput("next", "Next", "flow", "Continue to the next block in the workflow.")],
    },
    {
      id: "if",
      displayName: "If",
      category: BASIC_BLOCK_CATEGORY,
      description: "Branch the workflow based on a condition.",
      version: "1.0.0",
      kind: "basic",
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
      category: BASIC_BLOCK_CATEGORY,
      description: "Split into explicit true and false branches.",
      version: "1.0.0",
      kind: "basic",
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
      category: BASIC_BLOCK_CATEGORY,
      description: "Repeat the loop body while the condition remains true.",
      version: "1.0.0",
      kind: "basic",
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
      category: BASIC_BLOCK_CATEGORY,
      description: "Run the loop body a fixed number of times.",
      version: "1.0.0",
      kind: "basic",
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
      category: BASIC_BLOCK_CATEGORY,
      description: "Iterate over an upstream array or object input set.",
      version: "1.0.0",
      kind: "basic",
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
      category: BASIC_BLOCK_CATEGORY,
      description: "Pause execution for a number of milliseconds.",
      version: "1.0.0",
      kind: "basic",
      acceptsInput: true,
      accent: "#48711f",
      inputs: [buildInput("duration_ms", "Duration (ms)", "number", 1000, "How long to wait before continuing.")],
      outputs: [buildOutput("next", "Next", "flow", "Continue when the wait period completes.")],
    },
  ];
}

export function createHardwareBasicBlocks(hardwareMap: HardwareMap | null): WorkflowBlockDefinition[] {
  if (!hardwareMap) {
    return [];
  }

  const boardLookup = new Map(hardwareMap.boards.map((board) => [board.id, board]));

  return hardwareMap.devices.flatMap((device): WorkflowBlockDefinition[] => {
    const board = boardLookup.get(device.board_id);

    if (device.kind === "stepper_motor") {
      const pumpCalibration = getPumpCalibrationMlPer200Steps(device);
      if (pumpCalibration !== null) {
        return [{
          id: `basic-stepper-${device.id}`,
          displayName: `Pump ${device.name}`,
          category: BASIC_BLOCK_CATEGORY,
          description: `Run ${device.name} as a peristaltic pump${board ? ` on ${board.label}` : ""}.`,
          version: "1.0.0",
          kind: "basic",
          acceptsInput: true,
          accent: "#a85d13",
          inputs: [
            buildInput("volume_ml", "Volume (mL)", "number", 1, "Volume to pump. Positive values run the configured pump direction."),
            buildInput("calibration_ml_per_200_steps", "mL / 200 steps", "number", pumpCalibration, "Measured pump volume per one full 200-step motor rotation."),
          ],
          advancedInputs: [
            buildInput("speed_steps_per_second", "Speed (steps/s)", "number", 800, "Step pulse speed used by the pump."),
          ],
          outputs: [buildOutput("next", "Next", "flow", "Continue when the pump move completes.")],
          hardwareDeviceId: device.id,
          hardwareDeviceKind: "stepper_motor",
          hardwareBoardId: device.board_id,
          hardwareCalibrationMlPer200Steps: pumpCalibration,
        }];
      }

      return [{
        id: `basic-stepper-${device.id}`,
        displayName: `Move ${device.name}`,
        category: BASIC_BLOCK_CATEGORY,
        description: `Move ${device.name} by a signed step amount${board ? ` on ${board.label}` : ""}.`,
        version: "1.0.0",
        kind: "basic",
        acceptsInput: true,
        accent: "#a85d13",
        inputs: [
          buildInput("amount_steps", "Amount (steps)", "number", 0, "Signed step count. Positive and negative values move in opposite directions."),
        ],
        advancedInputs: [
          buildInput("speed_steps_per_second", "Speed (steps/s)", "number", 800, "Step pulse speed used by the basic move."),
        ],
        outputs: [buildOutput("next", "Next", "flow", "Continue when the stepper move completes.")],
        hardwareDeviceId: device.id,
        hardwareDeviceKind: "stepper_motor",
        hardwareBoardId: device.board_id,
        hardwareCalibrationMlPer200Steps: null,
      }];
    }

    if (device.kind === "servo") {
      const range = getServoRange(device);
      return [{
        id: `basic-servo-${device.id}`,
        displayName: `Move ${device.name}`,
        category: BASIC_BLOCK_CATEGORY,
        description: `Move ${device.name} to an angle between ${range.min} and ${range.max} degrees.`,
        version: "1.0.0",
        kind: "basic",
        acceptsInput: true,
        accent: "#8e4ec6",
        inputs: [
          buildInput("angle_deg", "Angle (deg)", "number", Math.max(range.min, Math.min(90, range.max)), `Target servo angle. Hardware range is ${range.min} to ${range.max} degrees.`),
        ],
        outputs: [buildOutput("next", "Next", "flow", "Continue when the servo reaches the target angle.")],
        hardwareDeviceId: device.id,
        hardwareDeviceKind: "servo",
        hardwareBoardId: device.board_id,
      }];
    }

    if (device.kind === "sensor") {
      return [{
        id: `basic-sensor-${device.id}`,
        displayName: `Read ${device.name}`,
        category: BASIC_BLOCK_CATEGORY,
        description: `Read ${device.name}${board ? ` on ${board.label}` : ""}.`,
        version: "1.0.0",
        kind: "basic",
        acceptsInput: true,
        accent: "#0f6f66",
        inputs: [],
        outputs: [buildOutput("next", "Next", "flow", "Continue after reading the sensor.")],
        hardwareDeviceId: device.id,
        hardwareDeviceKind: "sensor",
        hardwareBoardId: device.board_id,
      }];
    }

    return [];
  });
}

export function mapDiscoveredFunctionToBlock(
  discoveredFunction: DiscoveredFunctionDefinition,
  esp32Boards: Esp32BoardSummary[] = [],
  hardwareMap: HardwareMap | null = null,
): WorkflowBlockDefinition {
  const hardwareBoardOptions = (hardwareMap?.boards ?? [])
    .filter((board) => Boolean(board.usb_port))
    .map((board) => ({
      label: `${board.label} (${board.usb_port})`,
      value: board.usb_port,
    }));
  const hardwareBoardPorts = new Set(hardwareBoardOptions.map((option) => option.value));
  const detectedBoardOptions = esp32Boards
    .filter((board) => Boolean(board.port) && !hardwareBoardPorts.has(board.port as string))
    .map((board) => ({
      label: `${board.display_name}${board.port ? ` (${board.port})` : ""}`,
      value: board.port as string,
    }));
  const toolPortOptions = [...hardwareBoardOptions, ...detectedBoardOptions];
  const pinOptions = buildHardwarePinOptions(hardwareMap);
  const flowOutputs = discoveredFunction.manifest.outputs.filter((output) => output.type === "flow");
  const hardwareDevices = discoveredFunction.manifest.hardware_devices ?? [];
  const referencedBasicBlockIds = hardwareDevices
    .map((device) => device.basic_block_id ?? getHardwareBasicBlockId({ id: device.id, kind: device.kind }))
    .filter((blockId): blockId is string => Boolean(blockId));

  const mapInput = (input: WorkflowInputDefinition): WorkflowInputDefinition => {
    if (input.key === "tool_port" && toolPortOptions.length > 0) {
      const defaultValue = String(input.default ?? toolPortOptions[0]?.value ?? "");
      return {
        ...input,
        label: "Selected ESP32",
        type: "select",
        options: toolPortOptions,
        default: toolPortOptions.some((option) => option.value === defaultValue)
          ? defaultValue
          : toolPortOptions[0]?.value ?? defaultValue,
      };
    }

    if (!input.key.includes("pin") || pinOptions.length === 0) {
      return input;
    }

    const exactOptions = pinOptions.filter((option) => option.inputKey === input.key);
    const options = exactOptions.length > 0 ? exactOptions : pinOptions;
    const defaultValue = String(input.default ?? options[0]?.value ?? "");
    return {
      ...input,
      type: "select",
      options,
      default: options.some((option) => option.value === defaultValue)
        ? defaultValue
        : options[0]?.value ?? defaultValue,
    };
  };

  return {
    id: discoveredFunction.manifest.id,
    displayName: discoveredFunction.manifest.display_name,
    category: ADVANCED_FUNCTION_CATEGORY,
    description: discoveredFunction.manifest.description,
    version: discoveredFunction.manifest.version,
    kind: "advanced",
    acceptsInput: true,
    accent: "#0e7490",
    inputs: discoveredFunction.manifest.inputs.map(mapInput),
    advancedInputs: (discoveredFunction.manifest.advanced_inputs ?? []).map(mapInput),
    outputs:
      flowOutputs.length > 0
        ? flowOutputs.map((output) => ({
            key: output.key,
            label: output.label,
            type: output.type,
            description: output.description,
          }))
        : [buildOutput("next", "Next", "flow", "Continue to the next workflow node.")],
    builderBoardId: discoveredFunction.manifest.builder_board_id ?? null,
    builderSourcePath: discoveredFunction.manifest.builder_source_path ?? null,
    builderWorkspacePath: discoveredFunction.manifest.builder_workspace_path ?? null,
    builderFirmwareEntryFile: discoveredFunction.manifest.builder_firmware_entry_file ?? null,
    builderBaseFunctionId: discoveredFunction.manifest.builder_base_function_id ?? null,
    hardwareDevices,
    firmwareRequirements: discoveredFunction.manifest.firmware_requirements ?? [],
    referencedBasicBlockIds,
  };
}

export function getAllBlockInputs(block: WorkflowBlockDefinition): WorkflowInputDefinition[] {
  return [...block.inputs, ...(block.advancedInputs ?? [])];
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
      parameters: createDefaultParameters(getAllBlockInputs(block)),
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
      schema_version: 1,
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
  if (block.kind === "broken") {
    return {
      function_id: block.id,
      ok: false,
      inputs: parameters,
      input_data: inputData ?? null,
      result: {
        status: "missing_reference",
        original_id: block.missingReference?.originalId ?? block.id,
        reason: block.missingReference?.reason ?? "This workflow block cannot be resolved.",
        suggested_fix: block.missingReference?.suggestedFix ?? "Replace this block with an available block.",
      },
      error: block.missingReference?.reason ?? "This workflow block cannot be resolved.",
    };
  }

  if (block.kind === "compound") {
    return {
      function_id: block.id,
      ok: true,
      inputs: parameters,
      input_data: inputData ?? null,
      result: {
        status: "compound",
        inner_block_count: block.compound?.nodes.length ?? 0,
        outputs: block.outputs.map((output) => output.key),
      },
      error: null,
    };
  }

  if (block.hardwareDeviceKind === "stepper_motor") {
    const calibrationMlPer200Steps = Number(parameters.calibration_ml_per_200_steps ?? block.hardwareCalibrationMlPer200Steps);
    const volumeMl = Number(parameters.volume_ml);
    const isPumpMove = Number.isFinite(calibrationMlPer200Steps)
      && calibrationMlPer200Steps > 0
      && Number.isFinite(volumeMl);
    const amountSteps = isPumpMove
      ? Math.round((volumeMl / calibrationMlPer200Steps) * 200)
      : Number(parameters.amount_steps ?? 0);

    return {
      function_id: block.id,
      ok: true,
      inputs: parameters,
      input_data: inputData ?? null,
      result: {
        status: "simulated",
        action: isPumpMove ? "run_peristaltic_pump" : "move_stepper",
        device_id: block.hardwareDeviceId,
        board_id: block.hardwareBoardId,
        amount_steps: amountSteps,
        volume_ml: isPumpMove ? volumeMl : undefined,
        calibration_ml_per_200_steps: isPumpMove ? calibrationMlPer200Steps : undefined,
        speed_steps_per_second: parameters.speed_steps_per_second ?? 800,
        next_output: "next",
      },
      error: null,
    };
  }

  if (block.hardwareDeviceKind === "servo") {
    return {
      function_id: block.id,
      ok: true,
      inputs: parameters,
      input_data: inputData ?? null,
      result: {
        status: "simulated",
        action: "move_servo",
        device_id: block.hardwareDeviceId,
        board_id: block.hardwareBoardId,
        angle_deg: parameters.angle_deg ?? 0,
        next_output: "next",
      },
      error: null,
    };
  }

  if (block.hardwareDeviceKind === "sensor") {
    return {
      function_id: block.id,
      ok: true,
      inputs: parameters,
      input_data: inputData ?? null,
      result: {
        status: "simulated",
        action: "read_sensor",
        device_id: block.hardwareDeviceId,
        board_id: block.hardwareBoardId,
        next_output: "next",
      },
      error: null,
    };
  }

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
  return ["if", "if_else", "while", "for", "loop_over"].includes(block.id);
}
