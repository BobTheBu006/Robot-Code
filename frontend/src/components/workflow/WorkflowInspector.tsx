import type { ChangeEvent } from "react";
import { useEffect, useState } from "react";

import type { Edge, Node } from "@xyflow/react";

import { formatWorkflowParameterValue, getWorkflowNodeOutputs } from "../../lib/workflow";
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

interface WorkflowInspectorProps {
  selectedNode: WorkflowFlowNode;
  nodes: WorkflowFlowNode[];
  edges: Edge[];
  testStatus: TestStatus;
  testResult: FunctionTestResponse | null;
  testError: string | null;
  onClose: () => void;
  onNavigateToNode: (nodeId: string) => void;
  onRunTest: () => void;
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

function coerceInputValue(
  input: WorkflowInputDefinition,
  event: ChangeEvent<HTMLInputElement | HTMLSelectElement>,
): WorkflowParameterValue {
  if (input.type === "boolean") {
    return (event.target as HTMLInputElement).checked;
  }

  if (input.type === "number") {
    return Number(event.target.value);
  }

  return event.target.value;
}

export function WorkflowInspector({
  selectedNode,
  nodes,
  edges,
  testStatus,
  testResult,
  testError,
  onClose,
  onNavigateToNode,
  onRunTest,
  onUpdateParameter,
  onUpdateSettings,
}: WorkflowInspectorProps) {
  const [activeTab, setActiveTab] = useState<InspectorTab>("parameters");
  const { block, parameters, settings } = selectedNode.data;
  const incomingEdges = edges.filter((edge) => edge.target === selectedNode.id);
  const outgoingEdges = edges.filter((edge) => edge.source === selectedNode.id);
  const declaredOutputs = getWorkflowNodeOutputs(selectedNode.data).filter((output) => output.key !== "next");
  const previousNode = incomingEdges.length > 0
    ? nodes.find((node) => node.id === incomingEdges[0]?.source) ?? null
    : null;
  const nextNode = outgoingEdges.length > 0
    ? nodes.find((node) => node.id === outgoingEdges[0]?.target) ?? null
    : null;

  useEffect(() => {
    setActiveTab("parameters");
  }, [selectedNode.id]);

  return (
    <div className="workflow-overlay">
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

          <div className="workflow-overlay__panel-header">
            <span>Input</span>
          </div>

          <section className="workflow-overlay__section">
            <h3>Connected inputs</h3>
            {incomingEdges.length > 0 ? (
              <div className="workflow-overlay__list">
                {incomingEdges.map((edge) => (
                  <div className="workflow-overlay__list-item" key={edge.id}>
                    <strong>{edge.source}</strong>
                    <span>{`${edge.sourceHandle ?? "next"} -> input`}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="workflow-overlay__empty-text">No upstream node is connected to this block yet.</p>
            )}
          </section>

          <section className="workflow-overlay__section">
            <h3>Input fields</h3>
            {block.inputs.length > 0 ? (
              <div className="workflow-overlay__list">
                {block.inputs.map((input) => (
                  <div className="workflow-overlay__list-item" key={input.key}>
                    <strong>{input.label}</strong>
                    <span>{input.type}</span>
                    <p>{input.description ?? "No description provided."}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="workflow-overlay__empty-text">This block does not declare any input fields.</p>
            )}
          </section>
        </aside>

        <section className="workflow-overlay__editor">
          <div className="workflow-overlay__editor-header">
            <div>
              <span className="workflow-overlay__eyebrow">
                {block.kind === "robot-action" ? "Robot action" : block.category}
              </span>
              <h2>{block.displayName}</h2>
            </div>

            <div className="workflow-overlay__editor-actions">
              <button className="workflow-overlay__run" onClick={onRunTest} type="button">
                {testStatus === "running" ? "Running..." : "Test step"}
              </button>
            </div>
          </div>

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
              block.inputs.length > 0 ? (
                <div className="workflow-overlay__fields">
                  {block.inputs.map((input) => (
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
                        <input
                          onChange={(event) => onUpdateParameter(selectedNode.id, input, coerceInputValue(input, event))}
                          placeholder={input.placeholder ?? ""}
                          type={input.type === "number" ? "number" : "text"}
                          value={formatWorkflowParameterValue(parameters[input.key])}
                        />
                      )}

                      <p>{input.description ?? "No additional description for this field."}</p>
                    </label>
                  ))}
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

          <div className="workflow-overlay__panel-header">
            <span>Output</span>
            <button className="workflow-overlay__close" onClick={onClose} type="button">
              x
            </button>
          </div>

          <section className="workflow-overlay__section">
            <h3>Declared outputs</h3>
            {declaredOutputs.length > 0 ? (
              <div className="workflow-overlay__list">
                {declaredOutputs.map((output) => (
                  <div className="workflow-overlay__list-item" key={output.key}>
                    <strong>{output.label}</strong>
                    <span>{output.key}</span>
                    <p>{output.description ?? `Output type: ${output.type ?? "unknown"}`}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="workflow-overlay__empty-text">No declared outputs for this block.</p>
            )}
          </section>

          <section className="workflow-overlay__section">
            <h3>Connected outputs</h3>
            {outgoingEdges.length > 0 ? (
              <div className="workflow-overlay__list">
                {outgoingEdges.map((edge) => (
                  <div className="workflow-overlay__list-item" key={edge.id}>
                    <strong>{edge.sourceHandle ?? "next"}</strong>
                    <span>{edge.target}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="workflow-overlay__empty-text">No downstream block is connected yet.</p>
            )}
          </section>

          <section className="workflow-overlay__section">
            <h3>Last test result</h3>
            {testStatus === "idle" ? (
              <p className="workflow-overlay__empty-text">Run this step to preview its output.</p>
            ) : null}
            {testStatus === "running" ? (
              <p className="workflow-overlay__empty-text">Running block test...</p>
            ) : null}
            {testError ? <p className="error-text">{testError}</p> : null}
            {testResult ? (
              <pre className="workflow-overlay__result">
                {JSON.stringify(testResult, null, 2)}
              </pre>
            ) : null}
          </section>
        </aside>
      </div>
    </div>
  );
}
