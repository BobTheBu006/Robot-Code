import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from "@xyflow/react";

export function WorkflowEdge({
  id,
  sourceX,
  sourceY,
  sourcePosition,
  targetX,
  targetY,
  targetPosition,
  markerEnd,
  data,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const onDelete = typeof data?.onDelete === "function" ? data.onDelete as (edgeId: string) => void : null;
  const onInsert = typeof data?.onInsert === "function" ? data.onInsert as (edgeId: string) => void : null;
  const isActive = Boolean(data?.isActive);

  return (
    <>
      <BaseEdge id={id} interactionWidth={24} markerEnd={markerEnd} path={edgePath} />
      {isActive && (onDelete || onInsert) ? (
        <EdgeLabelRenderer>
          <div
            className="workflow-edge__actions nodrag nopan"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
          >
            {onInsert ? (
              <button
                className="workflow-edge__insert nodrag nopan"
                onClick={(event) => {
                  event.stopPropagation();
                  onInsert(id);
                }}
                onMouseDown={(event) => event.stopPropagation()}
                title="Insert a block on this connection"
                type="button"
              >
                +
              </button>
            ) : null}
            {onDelete ? (
              <button
                className="workflow-edge__delete nodrag nopan"
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(id);
                }}
                onMouseDown={(event) => event.stopPropagation()}
                title="Delete connection"
                type="button"
              >
                x
              </button>
            ) : null}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
