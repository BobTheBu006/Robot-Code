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
  const isActive = Boolean(data?.isActive);

  return (
    <>
      <BaseEdge id={id} interactionWidth={24} markerEnd={markerEnd} path={edgePath} />
      {isActive && onDelete ? (
        <EdgeLabelRenderer>
          <button
            className="workflow-edge__delete nodrag nopan"
            onClick={(event) => {
              event.stopPropagation();
              onDelete(id);
            }}
            onMouseDown={(event) => event.stopPropagation()}
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
            type="button"
          >
            x
          </button>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
