"use client";

import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  useReactFlow,
  type NodeTypes,
  type EdgeTypes,
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

const NODE_WIDTH = 240;
// Approximate rendered height of a ModuleNode card (title row + status pill +
// meta row, with padding) — used only so the MiniMap can draw node rects
// without waiting on DOM measurement (see WorkflowView minimap notes below).
const NODE_HEIGHT = 132;
const START_NODE_HEIGHT = 64;
const H_GAP = 80;

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

function buildLayout(curriculum: CurriculumFull, onSelectModule: (moduleId: string) => void) {
  const nodes: (StartNodeType | ModuleNodeType)[] = [
    {
      id: "start",
      type: "start",
      position: { x: 0, y: 0 },
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
        status: mod.status,
        sectionCount: mod.sections.length,
        estimatedMinutes: mod.estimated_minutes,
        onSelect: onSelectModule,
      },
    });

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

const MINIMAP_STATUS_COLOR: Record<ModuleStatus, string> = {
  planned: "var(--muted-foreground)",
  writing: "var(--accent)",
  complete: "var(--success)",
};

function minimapNodeColor(node: { type?: string; data?: unknown }): string {
  if (node.type === "start") return "var(--accent)";
  const status = (node.data as { status?: ModuleStatus } | undefined)?.status;
  return status ? MINIMAP_STATUS_COLOR[status] : "var(--muted-foreground)";
}

function WorkflowInner({ curriculum, onSelectModule }: WorkflowViewProps) {
  const { resolvedTheme } = useTheme();
  const { fitView } = useReactFlow();

  const { nodes, edges } = useMemo(
    () => buildLayout(curriculum, onSelectModule),
    [curriculum, onSelectModule]
  );

  useEffect(() => {
    const id = requestAnimationFrame(() => fitView({ padding: 0.25, duration: 300 }));
    return () => cancelAnimationFrame(id);
  }, [curriculum.modules.length, fitView]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      colorMode={resolvedTheme === "dark" ? "dark" : "light"}
      fitView
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={20} />
      <Controls showInteractive={false} position="bottom-right" />
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

export function WorkflowView(props: WorkflowViewProps) {
  return (
    <div className="h-full w-full">
      <ReactFlowProvider>
        <WorkflowInner {...props} />
      </ReactFlowProvider>
    </div>
  );
}
