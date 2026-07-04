import { BaseEdge, getSmoothStepPath, type EdgeProps, type Edge } from "@xyflow/react";

// This module is only ever imported by WorkflowView.tsx, which itself
// assumes @xyflow/react is only ever loaded client-side via
// CurriculumPanel's dynamic-import boundary (see WorkflowView.tsx's
// top-of-file comment) — no additional ssr:false handling needed here.

export type StatusEdgeData = {
  /** Whether this edge should render as an animated dashed "marching ants" line — true while the module it leads INTO (WorkflowView's `target`) has status "writing". */
  animated: boolean;
};

export type StatusEdgeType = Edge<StatusEdgeData, "status">;

/**
 * Custom React Flow edge registered under the "status" edge type (see
 * `edgeTypes` in WorkflowView.tsx). Draws a smooth step-path connector
 * between two nodes; styling is driven entirely by `data.animated`:
 *  - `animated: true` — dashed stroke with a CSS keyframe animation
 *    (`xyflow-dash`) that gives the "in progress" marching-ants effect,
 *    used for the edge leading into whichever module is currently being
 *    written.
 *  - `animated: false` — solid border-colored stroke, used for edges
 *    leading into planned or already-complete modules.
 */
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
