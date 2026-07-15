import type { CSSProperties } from "react";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

import { formatDurationShort, getWorkflowNodeDisplayName, getWorkflowNodeOutputs } from "../../lib/workflow";
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
  const isActive = data.isActive !== false;
  const disabledReason = data.block.disabledReason ?? null;
  const canRun = isActive && !disabledReason;
  const executionStatus = data.executionStatus ?? "idle";
  const showEstimate = executionStatus === "running" || Boolean(data.benchmarkDurationMs);
  const kindLabel = data.block.kind === "compound"
    ? "Compound Function"
    : data.block.kind === "broken"
      ? "Missing Block"
    : data.block.kind === "advanced" || data.block.kind === "robot-action"
      ? "Advanced Function"
      : "Basic Block";
  const isBroken = data.block.kind === "broken";

  return (
    <div
      className={`workflow-node ${selected ? "workflow-node--selected" : ""} ${canRun ? "" : "workflow-node--inactive"} ${isBroken ? "workflow-node--broken" : ""} ${executionStatus === "running" ? "workflow-node--running" : ""} ${executionStatus === "error" ? "workflow-node--error" : ""}`}
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
          disabled={isBroken || (!canRun && executionStatus !== "running")}
          onClick={(event) => {
            event.stopPropagation();
            if (executionStatus === "running") {
              data.onCancel?.();
              return;
            }
            data.onRun?.();
          }}
          onMouseDown={(event) => event.stopPropagation()}
          title={isBroken ? "Restore or replace this missing block before running it" : disabledReason ?? (executionStatus === "running" ? "Cancel block test" : "Run block test")}
          type="button"
        >
          {executionStatus === "running" ? "Cancel" : "Run"}
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
        <span className="workflow-node__kind">{kindLabel}</span>
        <strong title={getWorkflowNodeDisplayName(data)}>{getWorkflowNodeDisplayName(data)}</strong>
        <p title={data.block.description}>{data.block.description}</p>
        {disabledReason ? <p className="workflow-node__disabled-reason">{disabledReason}</p> : null}
        {isBroken ? <p className="workflow-node__repair">{data.block.missingReference?.suggestedFix}</p> : null}
      </div>

      <div className="workflow-node__ports">
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
              {data.onQuickAdd ? (
                <button
                  className="workflow-node__quick-add nodrag nopan"
                  onClick={(event) => {
                    event.stopPropagation();
                    data.onQuickAdd?.(output.key);
                  }}
                  onMouseDown={(event) => event.stopPropagation()}
                  title={`Add a block after ${output.label}`}
                  type="button"
                >
                  +
                </button>
              ) : null}
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
