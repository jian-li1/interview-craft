import { BaseEdge, getSmoothStepPath, type EdgeProps, type Edge } from "@xyflow/react";

export type StatusEdgeData = {
  animated: boolean;
};

export type StatusEdgeType = Edge<StatusEdgeData, "status">;

export function StatusEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  markerEnd,
}: EdgeProps<StatusEdgeType>) {
  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 12,
  });

  return (
    <BaseEdge
      path={edgePath}
      markerEnd={markerEnd}
      style={{
        stroke: "var(--border)",
        strokeWidth: 2,
        strokeDasharray: data?.animated ? "6 4" : undefined,
        animation: data?.animated ? "xyflow-dash 0.6s linear infinite" : undefined,
      }}
    />
  );
}
