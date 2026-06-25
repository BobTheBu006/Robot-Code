import type { ChangeEvent, DragEvent as ReactDragEvent } from "react";
import { useEffect, useMemo, useState } from "react";

import type { Edge, Node } from "@xyflow/react";

import { formatWorkflowParameterValue } from "../../lib/workflow";
import type { Esp32CustomBlockSaveResponse } from "../../types/esp32Builder";
import type {
  FunctionTestResponse,
  WorkflowFailureMode,
  WorkflowInputDefinition,
  WorkflowNodeData,
  WorkflowParameterValue,
} from "../../types/workflow";

type WorkflowFlowNode = Node<WorkflowNodeData>;
type TestStatus = "idle" | "running" | "success" | "error";
type InspectorTab = "parameters" | "settings";
type InputSourceMode = "all_blocks" | "previous";

interface WorkflowInspectorTestEntry {
  nodeId: string;
  nodeName: string;
  status: TestStatus;
  result: FunctionTestResponse | null;
  error: string | null;
}

interface FlattenedOutputField {
  label: string;
  expression: string;
  preview: string;
}

interface ExpressionPreview {
  text: string;
  multiline: boolean;
}

interface WorkflowInspectorProps {
  allNodeTestEntries: WorkflowInspectorTestEntry[];
  selectedNode: WorkflowFlowNode;
  nodes: WorkflowFlowNode[];
  edges: Edge[];
  previousNodeTestStatus: TestStatus;
  previousNodeTestResult: FunctionTestResponse | null;
  previousNodeTestError: string | null;
  testStatus: TestStatus;
  testResult: FunctionTestResponse | null;
  testError: string | null;
  onClose: () => void;
  onNavigateToNode: (nodeId: string) => void;
  onCancel: () => void;
  onEditCompound: () => void;
  onRunTest: () => void;
  onSaveCustomBlock: (displayName: string) => Promise<Esp32CustomBlockSaveResponse>;
  onUpdateParameter: (
    nodeId: string,
    input: WorkflowInputDefinition,
    value: WorkflowParameterValue,
  ) => void;
  onUpdateSettings: (
    nodeId: string,
    updates: Partial<{ failureMode: WorkflowFailureMode; retryCount: number }>,
  ) => void;
}

const WORKFLOW_EXPRESSION_MIME = "application/x-workflow-expression";

function coerceInputValue(
  input: WorkflowInputDefinition,
  event: ChangeEvent<HTMLInputElement | HTMLSelectElement>,
): WorkflowParameterValue {
  if (input.type === "boolean") {
    return (event.target as HTMLInputElement).checked;
  }

  if (input.type === "number") {
    const nextValue = event.target.value;
    if (nextValue.includes("{{")) {
      return nextValue;
    }

    const parsed = Number(nextValue);
    return Number.isFinite(parsed) ? parsed : nextValue;
  }

  return event.target.value;
}

function getResultPayload(result: FunctionTestResponse | null): unknown {
  return result?.result ?? null;
}

function formatPreviewValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  if (value === null || value === undefined) {
    return "null";
  }

  const json = JSON.stringify(value);
  return json.length > 64 ? `${json.slice(0, 61)}...` : json;
}

function stringifyPreviewValue(value: unknown): ExpressionPreview | null {
  if (value === null || value === undefined) {
    return null;
  }

  if (typeof value === "string") {
    return {
      text: value,
      multiline: value.includes("\n") || value.length > 80,
    };
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return {
      text: String(value),
      multiline: false,
    };
  }

  const json = JSON.stringify(value, null, 2);
  return {
    text: json,
    multiline: true,
  };
}

function resolveValueAtPath(source: unknown, path: string): unknown {
  if (!path.trim()) {
    return source;
  }

  const segments = path
    .split(".")
    .map((segment) => segment.trim())
    .filter(Boolean);

  let current = source;
  for (const segment of segments) {
    if (current === null || current === undefined || typeof current !== "object") {
      return null;
    }

    if (!(segment in (current as Record<string, unknown>))) {
      return null;
    }

    current = (current as Record<string, unknown>)[segment];
  }

  return current;
}

function resolveExpressionPreview(
  rawValue: WorkflowParameterValue,
  previousPayload: unknown,
  blockPayloadLookup: Record<string, unknown>,
): ExpressionPreview | null {
  if (typeof rawValue !== "string" || !rawValue.includes("{{")) {
    return null;
  }

  const trimmed = rawValue.trim();
  const wholeExpressionMatch = trimmed.match(/^\{\{([^}]+)\}\}$/);

  const resolveBody = (body: string): unknown => {
    const normalized = body.trim()
      .replace(/^\$json\./, "input.")
      .replace(/^\$input\./, "input.")
      .replace(/^json\./, "input.")
      .replace(/^previous\./, "input.")
      .replace(/^\$blocks\./, "blocks.");

    if (
      normalized === "input"
      || normalized === "$json"
      || normalized === "$input"
      || normalized === "previous"
      || normalized === "json"
    ) {
      return previousPayload;
    }

    if (normalized === "blocks" || normalized === "$blocks") {
      return blockPayloadLookup;
    }

    if (normalized.startsWith("input.")) {
      return resolveValueAtPath(previousPayload, normalized.slice("input.".length));
    }

    if (normalized.startsWith("blocks.")) {
      return resolveValueAtPath(blockPayloadLookup, normalized.slice("blocks.".length));
    }

    return resolveValueAtPath(previousPayload, normalized);
  };

  if (wholeExpressionMatch) {
    return stringifyPreviewValue(resolveBody(wholeExpressionMatch[1]));
  }

  const expressionMatches = [...rawValue.matchAll(/\{\{([^}]+)\}\}/g)];
  if (expressionMatches.length === 0) {
    return null;
  }

  let nextValue = rawValue;
  for (const match of expressionMatches) {
    const resolvedValue = resolveBody(match[1]);
    if (resolvedValue === null || resolvedValue === undefined) {
      return null;
    }

    nextValue = nextValue.replace(match[0], formatPreviewValue(resolvedValue));
  }

  return {
    text: nextValue,
    multiline: nextValue.includes("\n") || nextValue.length > 80,
  };
}

function flattenOutputFields(
  value: unknown,
  expressionRoot: string,
  path = "",
  depth = 0,
): FlattenedOutputField[] {
  if (depth > 5) {
    return [];
  }

  if (value === null || value === undefined) {
    return path
      ? [{ label: path, expression: `{{${expressionRoot}}}`, preview: "null" }]
      : [];
  }

  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return [{
      label: path || "$root",
      expression: `{{${expressionRoot}}}`,
      preview: formatPreviewValue(value),
    }];
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return path
        ? [{ label: path, expression: `{{${expressionRoot}}}`, preview: "[]" }]
        : [];
    }

    return value.flatMap((item, index) => {
      const nextPath = path ? `${path}.${index}` : String(index);
      const nextExpressionRoot = `${expressionRoot}.${index}`;
      return flattenOutputFields(item, nextExpressionRoot, nextPath, depth + 1);
    });
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) {
      return path
        ? [{ label: path, expression: `{{${expressionRoot}}}`, preview: "{}" }]
        : [];
    }

    return entries.flatMap(([key, nestedValue]) => {
      const nextPath = path ? `${path}.${key}` : key;
      const nextExpressionRoot = `${expressionRoot}.${key}`;
      return flattenOutputFields(nestedValue, nextExpressionRoot, nextPath, depth + 1);
    });
  }

  return [];
}

function handleDragStart(event: ReactDragEvent<HTMLButtonElement>, expression: string) {
  event.dataTransfer.effectAllowed = "copy";
  event.dataTransfer.setData(WORKFLOW_EXPRESSION_MIME, expression);
  event.dataTransfer.setData("text/plain", expression);
}

async function copyTextToClipboard(text: string) {
  if (!navigator.clipboard) {
    return;
  }

  await navigator.clipboard.writeText(text);
}

export function WorkflowInspector({
  allNodeTestEntries,
  selectedNode,
  nodes,
  edges,
  previousNodeTestStatus,
  previousNodeTestResult,
  previousNodeTestError,
  testStatus,
  testResult,
  testError,
  onClose,
  onNavigateToNode,
  onCancel,
  onEditCompound,
  onRunTest,
  onSaveCustomBlock,
  onUpdateParameter,
  onUpdateSettings,
}: WorkflowInspectorProps) {
  const [activeTab, setActiveTab] = useState<InspectorTab>("parameters");
  const [inputSourceMode, setInputSourceMode] = useState<InputSourceMode>("previous");
  const [focusedInputKey, setFocusedInputKey] = useState<string | null>(null);
  const [advancedExpanded, setAdvancedExpanded] = useState(false);
  const [customBlockName, setCustomBlockName] = useState(`${selectedNode.data.block.displayName} Preset`);
  const [customBlockSaveState, setCustomBlockSaveState] = useState<"idle" | "saving" | "success" | "error">("idle");
  const [customBlockSaveMessage, setCustomBlockSaveMessage] = useState<string | null>(null);
  const { block, parameters, settings } = selectedNode.data;
  const isBrokenBlock = block.kind === "broken";
  const incomingEdges = edges.filter((edge) => edge.target === selectedNode.id);
  const outgoingEdges = edges.filter((edge) => edge.source === selectedNode.id);
  const previousNode = incomingEdges.length > 0
    ? nodes.find((node) => node.id === incomingEdges[0]?.source) ?? null
    : null;
  const nextNode = outgoingEdges.length > 0
    ? nodes.find((node) => node.id === outgoingEdges[0]?.target) ?? null
    : null;
  const previousPayload = useMemo(() => getResultPayload(previousNodeTestResult), [previousNodeTestResult]);
  const currentPayload = useMemo(() => getResultPayload(testResult), [testResult]);
  const linkedHardwareBlocks = useMemo(
    () =>
      (block.hardwareDevices ?? []).map((device, index) => ({
        id: block.referencedBasicBlockIds?.[index] ?? device.basic_block_id ?? device.id,
        label: `${device.kind === "sensor" ? "Read" : "Move"} ${device.name}`,
        meta: device.kind === "sensor" && device.sensor_kind ? device.sensor_kind : device.kind,
      })),
    [block.hardwareDevices, block.referencedBasicBlockIds],
  );
  const firmwareRequirements = block.firmwareRequirements ?? [];
  const blockPayloadLookup = useMemo(
    () =>
      Object.fromEntries(
        allNodeTestEntries
          .filter((entry) => entry.nodeId !== selectedNode.id)
          .map((entry) => [entry.nodeId, getResultPayload(entry.result)]),
      ),
    [allNodeTestEntries, selectedNode.id],
  );
  const previousOutputFields = useMemo(
    () => flattenOutputFields(previousPayload, "input"),
    [previousPayload],
  );
  const allBlockOutputs = useMemo(
    () =>
      allNodeTestEntries
        .filter((entry) => entry.nodeId !== selectedNode.id)
        .map((entry) => {
          const payload = getResultPayload(entry.result);
          return {
            ...entry,
            payload,
            fields: flattenOutputFields(payload, `blocks.${entry.nodeId}`),
          };
        })
        .filter((entry) => entry.payload !== null || entry.error || entry.status === "running"),
    [allNodeTestEntries],
  );

  useEffect(() => {
    setActiveTab("parameters");
    setInputSourceMode("previous");
    setFocusedInputKey(null);
    setAdvancedExpanded(false);
    setCustomBlockName(`${selectedNode.data.block.displayName} Preset`);
    setCustomBlockSaveState("idle");
    setCustomBlockSaveMessage(null);
  }, [selectedNode.id]);

  async function handleSaveCustomBlock() {
    try {
      setCustomBlockSaveState("saving");
      setCustomBlockSaveMessage(null);
      const response = await onSaveCustomBlock(customBlockName);
      setCustomBlockSaveState("success");
      setCustomBlockSaveMessage(`Saved '${response.display_name}' to the block library.`);
    } catch (error) {
      setCustomBlockSaveState("error");
      setCustomBlockSaveMessage(error instanceof Error ? error.message : "Could not save custom block.");
    }
  }

  function handleParameterDrop(
    event: ReactDragEvent<HTMLInputElement>,
    input: WorkflowInputDefinition,
  ) {
    event.preventDefault();
    const expression = event.dataTransfer.getData(WORKFLOW_EXPRESSION_MIME)
      || event.dataTransfer.getData("text/plain");
    if (!expression) {
      return;
    }

    onUpdateParameter(selectedNode.id, input, expression);
  }

  function renderParameterField(input: WorkflowInputDefinition) {
    return (
      <label className="workflow-overlay__field" key={input.key}>
        <div className="workflow-overlay__field-meta">
          <span>{input.label}</span>
          <small>{input.type}</small>
        </div>

        {input.type === "select" ? (
          <select
            value={String(parameters[input.key] ?? "")}
            onChange={(event) => onUpdateParameter(selectedNode.id, input, coerceInputValue(input, event))}
          >
            {input.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        ) : input.type === "boolean" ? (
          <input
            checked={Boolean(parameters[input.key])}
            onChange={(event) => onUpdateParameter(selectedNode.id, input, coerceInputValue(input, event))}
            type="checkbox"
          />
        ) : (
          <>
            <input
              onChange={(event) => onUpdateParameter(selectedNode.id, input, coerceInputValue(input, event))}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => handleParameterDrop(event, input)}
              onFocus={() => setFocusedInputKey(input.key)}
              onClick={() => setFocusedInputKey(input.key)}
              placeholder={input.placeholder ?? "Drag a value here"}
              type="text"
              value={formatWorkflowParameterValue(parameters[input.key])}
            />
            {focusedInputKey === input.key ? (() => {
              const preview = resolveExpressionPreview(
                parameters[input.key],
                previousPayload,
                blockPayloadLookup,
              );

              if (!preview) {
                return null;
              }

              return preview.multiline ? (
                <textarea
                  className="workflow-overlay__expression-preview"
                  readOnly
                  rows={Math.min(Math.max(preview.text.split("\n").length, 2), 8)}
                  value={preview.text}
                />
              ) : (
                <input
                  className="workflow-overlay__expression-preview"
                  readOnly
                  type="text"
                  value={preview.text}
                />
              );
            })() : null}
          </>
        )}

        <p>{input.description ?? "No additional description for this field."}</p>
      </label>
    );
  }

  function renderCopyableResult(label: string, value: unknown, variant?: "input") {
    const serialized = JSON.stringify(value, null, 2);

    return (
      <div className="workflow-overlay__copyable-result">
        <div className="workflow-overlay__result-header">
          <strong>{label}</strong>
          <button
            className="workflow-overlay__copy-button"
            onClick={() => void copyTextToClipboard(serialized)}
            type="button"
          >
            Copy
          </button>
        </div>
        <pre className={variant === "input" ? "workflow-overlay__result workflow-overlay__result--input" : "workflow-overlay__result"}>
          {serialized}
        </pre>
      </div>
    );
  }

  return (
    <div className="workflow-overlay">
      <div className="workflow-overlay__topbar">
        <div className="workflow-overlay__topbar-side">
          <span>Input</span>
        </div>

        <div className="workflow-overlay__topbar-center">
          <div className="workflow-overlay__title">
            <span className="workflow-overlay__eyebrow">
              {block.kind === "compound" ? "Compound Function" : block.kind === "broken" ? "Missing Block" : block.kind === "advanced" || block.kind === "robot-action" ? "Advanced Function" : "Basic Block"}
            </span>
            <strong>{block.displayName}</strong>
          </div>

          <button
            className={testStatus === "running" ? "workflow-overlay__run workflow-overlay__run--cancel" : "workflow-overlay__run"}
            disabled={isBrokenBlock}
            onClick={testStatus === "running" ? onCancel : onRunTest}
            type="button"
          >
            {isBrokenBlock ? "Missing" : testStatus === "running" ? "Cancel" : "Test step"}
          </button>
        </div>

        <div className="workflow-overlay__topbar-side workflow-overlay__topbar-side--right">
          <span>Output</span>
          <button className="workflow-overlay__close" onClick={onClose} type="button">
            x
          </button>
        </div>
      </div>

      <div className="workflow-overlay__layout">
        <aside className="workflow-overlay__panel workflow-overlay__panel--side">
          {previousNode ? (
            <button
              className="workflow-overlay__nav workflow-overlay__nav--prev"
              onClick={() => onNavigateToNode(previousNode.id)}
              type="button"
            >
              <span className="workflow-overlay__nav-arrow">←</span>
              <span>{previousNode.data.block.displayName}</span>
            </button>
          ) : null}

          <div className="workflow-overlay__input-switches">
            <button
              className={inputSourceMode === "all_blocks"
                ? "workflow-overlay__input-switch workflow-overlay__input-switch--active"
                : "workflow-overlay__input-switch"}
              onClick={() => setInputSourceMode("all_blocks")}
              type="button"
            >
              All blocks
            </button>
            <button
              className={inputSourceMode === "previous"
                ? "workflow-overlay__input-switch workflow-overlay__input-switch--active"
                : "workflow-overlay__input-switch"}
              onClick={() => setInputSourceMode("previous")}
              type="button"
            >
              Previous block output
            </button>
          </div>

          {inputSourceMode === "previous" ? (
            <section className="workflow-overlay__section workflow-overlay__section--stretch">
              {previousNodeTestStatus === "idle" ? (
                <p className="workflow-overlay__empty-text">Run the previous block to preview its output here.</p>
              ) : null}
              {previousNodeTestStatus === "running" ? (
                <p className="workflow-overlay__empty-text">Previous block is currently running...</p>
              ) : null}
              {previousNodeTestError ? <p className="error-text">{previousNodeTestError}</p> : null}
              {previousOutputFields.length > 0 ? (
                <div className="workflow-overlay__token-list">
                  {previousOutputFields.map((field) => (
                    <button
                      className="workflow-overlay__token"
                      draggable
                      key={field.expression}
                      onDragStart={(event) => handleDragStart(event, field.expression)}
                      type="button"
                    >
                      <strong>{field.label}</strong>
                      <span>{field.preview}</span>
                    </button>
                  ))}
                </div>
              ) : null}
              {previousNodeTestResult ? renderCopyableResult("Previous block JSON", previousPayload, "input") : null}
            </section>
          ) : (
            <section className="workflow-overlay__section workflow-overlay__section--stretch">
              {allBlockOutputs.length === 0 ? (
                <p className="workflow-overlay__empty-text">Run one or more blocks to see their outputs here.</p>
              ) : (
                <div className="workflow-overlay__all-blocks">
                  {allBlockOutputs.map((entry) => (
                    <div className="workflow-overlay__all-block" key={entry.nodeId}>
                      <div className="workflow-overlay__all-block-header">
                        <strong>{entry.nodeName}</strong>
                        <span>{entry.status}</span>
                      </div>
                      {entry.error ? <p className="error-text">{entry.error}</p> : null}
                      {entry.fields.length > 0 ? (
                        <div className="workflow-overlay__token-list">
                          {entry.fields.map((field) => (
                            <button
                              className="workflow-overlay__token"
                              draggable
                              key={`${entry.nodeId}-${field.expression}`}
                              onDragStart={(event) => handleDragStart(event, field.expression)}
                              type="button"
                            >
                              <strong>{field.label}</strong>
                              <span>{field.preview}</span>
                            </button>
                          ))}
                        </div>
                      ) : null}
                      {entry.payload ? renderCopyableResult(`${entry.nodeName} JSON`, entry.payload, "input") : null}
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}
        </aside>

        <section className="workflow-overlay__editor">
          <div className="workflow-overlay__tabs">
            <button
              className={activeTab === "parameters" ? "workflow-overlay__tab workflow-overlay__tab--active" : "workflow-overlay__tab"}
              onClick={() => setActiveTab("parameters")}
              type="button"
            >
              Parameters
            </button>
            <button
              className={activeTab === "settings" ? "workflow-overlay__tab workflow-overlay__tab--active" : "workflow-overlay__tab"}
              onClick={() => setActiveTab("settings")}
              type="button"
            >
              Settings
            </button>
          </div>

          <div className="workflow-overlay__editor-body">
            {activeTab === "parameters" ? (
              isBrokenBlock ? (
                <div className="workflow-overlay__missing-reference">
                  <strong>Missing reference</strong>
                  <p>{block.missingReference?.reason ?? "This block cannot be resolved from the current project state."}</p>
                  <p>{block.missingReference?.suggestedFix ?? "Restore the missing function, device, or module, then reload the workflow."}</p>
                  <div className="workflow-overlay__setting-row">
                    <span>Original id</span>
                    <strong>{block.missingReference?.originalId ?? block.id}</strong>
                  </div>
                  <div className="workflow-overlay__setting-row">
                    <span>Original kind</span>
                    <strong>{block.missingReference?.originalKind ?? "unknown"}</strong>
                  </div>
                </div>
              ) :
              block.inputs.length > 0 || (block.advancedInputs?.length ?? 0) > 0 ? (
                <div className="workflow-overlay__fields">
                  {linkedHardwareBlocks.length > 0 ? (
                    <section className="workflow-overlay__hardware-links">
                      <strong>Linked basic blocks</strong>
                      <div>
                        {linkedHardwareBlocks.map((linkedBlock) => (
                          <span key={linkedBlock.id}>
                            {linkedBlock.label}
                            <small>{linkedBlock.meta}</small>
                          </span>
                        ))}
                      </div>
                    </section>
                  ) : null}

                  {firmwareRequirements.length > 0 ? (
                    <section className="workflow-overlay__hardware-links">
                      <strong>Firmware routines</strong>
                      <div>
                        {firmwareRequirements.map((requirement) => (
                          <span key={requirement.routine_id}>
                            {requirement.routine_id}
                            <small>{requirement.controller_role}</small>
                          </span>
                        ))}
                      </div>
                    </section>
                  ) : null}

                  {block.inputs.map(renderParameterField)}

                  {(block.advancedInputs?.length ?? 0) > 0 ? (
                    <div className="workflow-overlay__advanced">
                      <button
                        className="workflow-overlay__advanced-toggle"
                        onClick={() => setAdvancedExpanded((currentValue) => !currentValue)}
                        type="button"
                      >
                        <span>{advancedExpanded ? "Hide advanced inputs" : "Show advanced inputs"}</span>
                        <span>{advancedExpanded ? "−" : "+"}</span>
                      </button>

                      {advancedExpanded ? (
                        <div className="workflow-overlay__advanced-body">
                          <div className="workflow-overlay__fields">
                            {(block.advancedInputs ?? []).map(renderParameterField)}
                          </div>

                          {(block.kind === "advanced" || block.kind === "robot-action") && block.builderBoardId ? (
                            <div className="workflow-overlay__custom-block">
                              <label className="workflow-overlay__field">
                                <div className="workflow-overlay__field-meta">
                                  <span>Custom block name</span>
                                  <small>library</small>
                                </div>
                                <input
                                  onChange={(event) => setCustomBlockName(event.target.value)}
                                  placeholder="Name this reusable preset"
                                  type="text"
                                  value={customBlockName}
                                />
                                <p>Choose a unique name and save the current normal and advanced values as a reusable block in the palette.</p>
                              </label>
                              <button
                                className="workflow-overlay__save-block"
                                disabled={customBlockSaveState === "saving"}
                                onClick={() => void handleSaveCustomBlock()}
                                type="button"
                              >
                                {customBlockSaveState === "saving" ? "Saving..." : "Save as custom block"}
                              </button>
                              {customBlockSaveMessage ? (
                                <p className={customBlockSaveState === "error" ? "error-text" : "workflow-overlay__success-text"}>
                                  {customBlockSaveMessage}
                                </p>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : (
                <p className="workflow-overlay__empty-text">This block has no editable parameters.</p>
              )
            ) : (
              <div className="workflow-overlay__settings">
                <label className="workflow-overlay__field">
                  <div className="workflow-overlay__field-meta">
                    <span>Upon fail</span>
                    <small>behavior</small>
                  </div>
                  <select
                    onChange={(event) =>
                      onUpdateSettings(selectedNode.id, {
                        failureMode: event.target.value as WorkflowFailureMode,
                      })}
                    value={settings.failureMode}
                  >
                    <option value="stop_flow">Stop whole flow</option>
                    <option value="separate_path">Throw error on separate path</option>
                  </select>
                  <p>Choose whether this block should stop the workflow or expose an error branch when execution fails.</p>
                </label>

                <label className="workflow-overlay__field">
                  <div className="workflow-overlay__field-meta">
                    <span>Retry n times</span>
                    <small>retries</small>
                  </div>
                  <input
                    min={0}
                    onChange={(event) =>
                      onUpdateSettings(selectedNode.id, {
                        retryCount: Number(event.target.value),
                      })}
                    type="number"
                    value={settings.retryCount}
                  />
                  <p>How many times the executor should retry this block before marking it as failed.</p>
                </label>

                {block.kind === "compound" ? (
                  <button
                    className="workflow-overlay__save-block"
                    onClick={onEditCompound}
                    type="button"
                  >
                    Edit compound function
                  </button>
                ) : null}

                <div className="workflow-overlay__setting-row">
                  <span>Node id</span>
                  <strong>{selectedNode.id}</strong>
                </div>
                <div className="workflow-overlay__setting-row">
                  <span>Block id</span>
                  <strong>{block.id}</strong>
                </div>
                <div className="workflow-overlay__setting-row">
                  <span>Category</span>
                  <strong>{block.category}</strong>
                </div>
                <div className="workflow-overlay__setting-row">
                  <span>Version</span>
                  <strong>{block.version}</strong>
                </div>
                <div className="workflow-overlay__setting-row">
                  <span>Firmware routines</span>
                  <strong>{firmwareRequirements.length}</strong>
                </div>
                <div className="workflow-overlay__setting-row">
                  <span>Incoming edges</span>
                  <strong>{incomingEdges.length}</strong>
                </div>
                <div className="workflow-overlay__setting-row">
                  <span>Outgoing edges</span>
                  <strong>{outgoingEdges.length}</strong>
                </div>
              </div>
            )}
          </div>
        </section>

        <aside className="workflow-overlay__panel workflow-overlay__panel--side">
          {nextNode ? (
            <button
              className="workflow-overlay__nav workflow-overlay__nav--next"
              onClick={() => onNavigateToNode(nextNode.id)}
              type="button"
            >
              <span>{nextNode.data.block.displayName}</span>
              <span className="workflow-overlay__nav-arrow">→</span>
            </button>
          ) : null}

          <section className="workflow-overlay__section workflow-overlay__section--stretch">
            {testStatus === "idle" ? (
              <p className="workflow-overlay__empty-text">Run this step to preview its output.</p>
            ) : null}
            {testStatus === "running" ? (
              <p className="workflow-overlay__empty-text">Running block test...</p>
            ) : null}
            {testError ? <p className="error-text">{testError}</p> : null}
            {testResult ? renderCopyableResult("Last test result", currentPayload) : null}
          </section>
        </aside>
      </div>
    </div>
  );
}
