import type { CSSProperties } from "react";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

import { formatDurationShort, getWorkflowNodeOutputs } from "../../lib/workflow";
import type { WorkflowNodeData } from "../../types/workflow";

type WorkflowFlowNode = Node<WorkflowNodeData>;

export function WorkflowNode({ data, selected }: NodeProps<WorkflowFlowNode>) {
  function getHandleTop(index: number, total: number): string {
    return `${((index + 0.5) / total) * 100}%`;
  }

  const nodeStyle = {
    "--workflow-node-accent": data.block.accent,
  } as CSSProperties;
  const outputs = getWorkflowNodeOutputs(data);
  const portsHeight = Math.max(outputs.length * 22, 14);
  const isActive = data.isActive !== false;
  const executionStatus = data.executionStatus ?? "idle";
  const showEstimate = executionStatus === "running" || Boolean(data.benchmarkDurationMs);

  return (
    <div
      className={`workflow-node ${selected ? "workflow-node--selected" : ""} ${isActive ? "" : "workflow-node--inactive"} ${executionStatus === "running" ? "workflow-node--running" : ""} ${executionStatus === "error" ? "workflow-node--error" : ""}`}
      style={nodeStyle}
    >
      <div className="workflow-node__actions">
        <button
          className="workflow-node__action nodrag nopan"
          onClick={(event) => {
            event.stopPropagation();
            data.onDelete?.();
          }}
          onMouseDown={(event) => event.stopPropagation()}
          title="Delete block"
          type="button"
        >
          Delete
        </button>
        <button
          className="workflow-node__action nodrag nopan"
          disabled={!isActive}
          onClick={(event) => {
            event.stopPropagation();
            data.onRun?.();
          }}
          onMouseDown={(event) => event.stopPropagation()}
          title="Run block test"
          type="button"
        >
          Run
        </button>
        <button
          className="workflow-node__action nodrag nopan"
          onClick={(event) => {
            event.stopPropagation();
            data.onToggleActive?.();
          }}
          onMouseDown={(event) => event.stopPropagation()}
          title={isActive ? "Deactivate block" : "Activate block"}
          type="button"
        >
          {isActive ? "Deactivate" : "Activate"}
        </button>
      </div>

      {data.block.acceptsInput ? (
        <Handle className="workflow-node__handle" id="input" position={Position.Left} type="target" />
      ) : null}

      <div className="workflow-node__header">
        <span className="workflow-node__kind">{data.block.kind === "built-in" ? data.block.category : "Robot Action"}</span>
        <strong>{data.block.displayName}</strong>
        <p>{data.block.description}</p>
      </div>

      <div className="workflow-node__ports" style={{ minHeight: `${portsHeight}px` }}>
        {outputs.map((output, index) => {
          const top = getHandleTop(index, outputs.length);
          return (
            <div className="workflow-node__port" key={output.key} style={{ top }}>
              <span className="workflow-node__port-label">{output.label}</span>
              <Handle
                className="workflow-node__handle"
                id={output.key}
                position={Position.Right}
                style={{ top: "50%" }}
                type="source"
              />
            </div>
          );
        })}
      </div>

      {showEstimate ? (
        <div className="workflow-node__execution">
          <span>
            {executionStatus === "running"
              ? `ETA ${formatDurationShort(data.executionEtaMs ?? data.benchmarkDurationMs)}`
              : `Avg ${formatDurationShort(data.benchmarkDurationMs)}`}
          </span>
        </div>
      ) : null}
    </div>
  );
}
