"use client";

// *** This file statically imports `@xyflow/react` (React Flow) at the top
// level, which per root/frontend CLAUDE.md's "ssr:false rule" must NEVER be
// pulled into a server-rendered tree — React Flow measures DOM layout,
// computes viewport/pan/zoom state, and has no meaningful SSR output. This
// component does NOT itself apply next/dynamic/{ ssr:false } — it relies
// entirely on being imported ONLY through CurriculumPanel.tsx's
// `next/dynamic(() => import(".../WorkflowView"), { ssr: false })` boundary.
// Do not add a plain top-level `import { WorkflowView } from ...` anywhere
// else (e.g. a server component, a page, another panel) — that would defeat
// the dynamic-import boundary and break the build/hydration.
import { useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  useReactFlow,
  type NodeTypes,
  type EdgeTypes,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useTheme } from "next-themes";
import {
  StartNode,
  START_NODE_WIDTH,
  type StartNodeType,
} from "@/components/studio/curriculum/nodes/StartNode";
import { ModuleNode, type ModuleNodeType } from "@/components/studio/curriculum/nodes/ModuleNode";
import { StatusEdge, type StatusEdgeType } from "@/components/studio/curriculum/edges/StatusEdge";
import type { CurriculumFull, ModuleStatus } from "@/lib/types";
import { useEffect } from "react";

const NODE_WIDTH = 280;
// Approximate rendered height of a ModuleNode card (title row up to 2 lines +
// description up to 3 lines + status pill + meta row, with padding) — used
// only so the MiniMap can draw node rects without waiting on DOM measurement
// (see WorkflowView minimap notes below).
const NODE_HEIGHT = 188;
const START_NODE_HEIGHT = 64;
const H_GAP = 80;
// React Flow anchors Handles at CSS top:50% of the node wrapper's declared inline
// height. Centering the shorter start node against the module cards' vertical
// midpoint makes the first edge's endpoints share the same Y, so it renders straight
// instead of doglegging.
const START_NODE_Y = (NODE_HEIGHT - START_NODE_HEIGHT) / 2;

// React Flow node/edge type registries: map the `type` string on each node/
// edge object (set in buildLayout below) to the component that renders it.
// Must be module-scope constants (not recreated per-render) — React Flow
// warns/re-mounts nodes if these object identities change on every render.
const nodeTypes: NodeTypes = {
  start: StartNode,
  module: ModuleNode,
};

const edgeTypes: EdgeTypes = {
  status: StatusEdge,
};

interface WorkflowViewProps {
  curriculum: CurriculumFull;
  onSelectModule: (moduleId: string) => void;
}

/**
 * Builds the "linear LTR workflow" layout: a single horizontal row starting
 * with the fixed-width start node, followed by one ModuleNode per module
 * (in `order`), each connected to the previous one by a StatusEdge. This is
 * intentionally a simple left-to-right chain (n8n-style canvases can be much
 * more free-form, but curricula are inherently sequential, so a straight
 * line reads more clearly than a force-directed/grid layout here).
 * Module selection is handled by `WorkflowInner`'s `onNodeClick` (registered
 * on `<ReactFlow>`), not by anything built here — see the comment on that prop.
 */
function buildLayout(curriculum: CurriculumFull) {
  const nodes: (StartNodeType | ModuleNodeType)[] = [
    {
      id: "start",
      type: "start",
      // Centered against module nodes' handle Y (see START_NODE_Y) so the first edge is straight.
      position: { x: 0, y: START_NODE_Y },
      width: START_NODE_WIDTH,
      height: START_NODE_HEIGHT,
      data: { title: curriculum.title, emoji: curriculum.emoji },
    },
  ];

  const edges: StatusEdgeType[] = [];
  const modules = [...curriculum.modules].sort((a, b) => a.order - b.order);

  modules.forEach((mod, i) => {
    // Single horizontal row, left to right: start node occupies
    // [0, START_NODE_WIDTH], then each module one step further right so the
    // animated status edges read clearly.
    const x = START_NODE_WIDTH + H_GAP + i * (NODE_WIDTH + H_GAP);
    const y = 0;

    nodes.push({
      id: mod.id,
      type: "module",
      position: { x, y },
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      data: {
        id: mod.id,
        order: mod.order,
        title: mod.title,
        description: mod.description,
        status: mod.status,
        sectionCount: mod.sections.length,
        estimatedMinutes: mod.estimated_minutes,
      },
    });

    // Connect each module to the one before it (or "start" for the first
    // module) so the canvas reads as a single chain, left to right. The
    // edge's `animated` flag (rendered as a dashed marching-ants line by
    // StatusEdge) reflects whether the module currently being written is the
    // one this edge leads INTO — i.e. it's the module's own status, not the
    // edge's, that drives the animation; this is how "status flows to nodes"
    // extends visually along the connecting edges too.
    const prevId = i === 0 ? "start" : modules[i - 1].id;
    edges.push({
      id: `e-${prevId}-${mod.id}`,
      source: prevId,
      target: mod.id,
      type: "status",
      data: { animated: mod.status === "writing" },
    });
  });

  return { nodes, edges };
}

// Status -> minimap swatch color, mirroring the same status palette used on
// ModuleNode's card border/badge (planned=muted, writing=accent, complete=success).
const MINIMAP_STATUS_COLOR: Record<ModuleStatus, string> = {
  planned: "var(--muted-foreground)",
  writing: "var(--accent)",
  complete: "var(--success)",
};

/** Color callback passed to React Flow's <MiniMap nodeColor>: the start node is always accent-colored; module nodes are colored by their `status` (module/section status flowing all the way down to the minimap's rendering, not just the main canvas nodes). */
function minimapNodeColor(node: { type?: string; data?: unknown }): string {
  if (node.type === "start") return "var(--accent)";
  const status = (node.data as { status?: ModuleStatus } | undefined)?.status;
  return status ? MINIMAP_STATUS_COLOR[status] : "var(--muted-foreground)";
}

/**
 * Inner canvas — must be rendered inside a `ReactFlowProvider` (see
 * `WorkflowView` below) because it calls `useReactFlow()` to imperatively
 * fit the view. Rebuilds the node/edge layout via `buildLayout` whenever the
 * curriculum changes, and re-fits the camera whenever the module count
 * changes (e.g. the agent adds a new module).
 */
function WorkflowInner({ curriculum, onSelectModule }: WorkflowViewProps) {
  const { resolvedTheme } = useTheme();
  const { fitView } = useReactFlow();

  const { nodes, edges } = useMemo(() => buildLayout(curriculum), [curriculum]);

  // Re-fit the camera (with a short animated transition) whenever the module
  // count changes, e.g. a new module is added while the agent is planning.
  // Deferred to requestAnimationFrame so it runs after React Flow has laid
  // out the newly-added node(s), rather than fitting to the stale bounds
  // from the previous render.
  useEffect(() => {
    const id = requestAnimationFrame(() => fitView({ padding: 0.25, duration: 300 }));
    return () => cancelAnimationFrame(id);
  }, [curriculum.modules.length, fitView]);

  // Single click path: React Flow's NodeWrapper only drops pointer-events:none
  // on a node when it's selectable/draggable OR an onNodeClick handler is
  // registered here — since nodesDraggable/nodesConnectable/elementsSelectable
  // are all false below, THIS handler is the only reason ModuleNode's button
  // is clickable at all. Do not remove it without an alternative.
  const handleNodeClick = useCallback<NodeMouseHandler<StartNodeType | ModuleNodeType>>(
    (_event, node) => {
      if (node.type === "module") onSelectModule(node.id);
    },
    [onSelectModule]
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      colorMode={resolvedTheme === "dark" ? "dark" : "light"}
      fitView
      // The canvas is read-only / navigation-only: users can't rearrange or
      // rewire nodes — clicking a ModuleNode navigates to the reader view via
      // onNodeClick below (not React Flow's built-in selection model).
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      // Required for clicking to work at all: React Flow disables pointer-events
      // on node wrappers unless nodes are draggable/selectable or onNodeClick is
      // registered — with the flags above all false, this is the sole enabler.
      onNodeClick={handleNodeClick}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={20} />
      <Controls showInteractive={false} position="bottom-right" />
      {/* Working minimap: colors each node by module status (see
          minimapNodeColor) so the overall curriculum progress is visible even
          when zoomed into one part of a long chain; pannable/zoomable so it
          doubles as a navigation aid on wide curricula. */}
      <MiniMap
        pannable
        zoomable
        className="!bg-card"
        nodeColor={minimapNodeColor}
        nodeStrokeColor={() => "var(--border)"}
        nodeStrokeWidth={2}
        nodeBorderRadius={6}
        maskColor="color-mix(in srgb, var(--background) 65%, transparent)"
      />
    </ReactFlow>
  );
}

/**
 * Public entry point: the n8n-style React Flow canvas showing the
 * curriculum as a linear left-to-right chain of module nodes. Wraps
 * `WorkflowInner` in a `ReactFlowProvider`, which is required for
 * `useReactFlow()` (used inside WorkflowInner to imperatively call
 * `fitView`) to work.
 *
 * This component (and everything it imports, transitively pulling in
 * `@xyflow/react`) must only ever be reached through CurriculumPanel's
 * `next/dynamic(..., { ssr: false })` import — see the top-of-file comment.
 */
export function WorkflowView(props: WorkflowViewProps) {
  return (
    <div className="h-full w-full">
      <ReactFlowProvider>
        <WorkflowInner {...props} />
      </ReactFlowProvider>
    </div>
  );
}
