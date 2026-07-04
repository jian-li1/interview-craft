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
import { StartNode, type StartNodeType } from "@/components/studio/curriculum/nodes/StartNode";
import { ModuleNode, type ModuleNodeType } from "@/components/studio/curriculum/nodes/ModuleNode";
import { StatusEdge, type StatusEdgeType } from "@/components/studio/curriculum/edges/StatusEdge";
import type { CurriculumFull } from "@/lib/types";
import { useEffect } from "react";

const NODE_WIDTH = 240;
const NODE_HEIGHT = 110;
const V_GAP = 70;
const COLS = 2;

const nodeTypes: NodeTypes = {
  start: StartNode,
  module: ModuleNode,
};

const edgeTypes: EdgeTypes = {
  status: StatusEdge,
};

interface WorkflowViewProps {
  curriculum: CurriculumFull;
  onSelectModule: (order: number) => void;
}

function buildLayout(curriculum: CurriculumFull, onSelectModule: (order: number) => void) {
  const nodes: (StartNodeType | ModuleNodeType)[] = [
    {
      id: "start",
      type: "start",
      position: { x: (NODE_WIDTH * COLS) / 2 - NODE_WIDTH / 2, y: 0 },
      data: { title: curriculum.title, emoji: curriculum.emoji },
    },
  ];

  const edges: StatusEdgeType[] = [];
  const modules = [...curriculum.modules].sort((a, b) => a.order - b.order);

  modules.forEach((mod, i) => {
    // Serpentine layout: alternate left/right column per row.
    const row = Math.floor(i / COLS);
    const colIndex = i % COLS;
    const rowReversed = row % 2 === 1;
    const col = rowReversed ? COLS - 1 - colIndex : colIndex;
    const x = col * (NODE_WIDTH + 40);
    const y = (row + 1) * (NODE_HEIGHT + V_GAP);

    nodes.push({
      id: mod.id,
      type: "module",
      position: { x, y },
      data: {
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
        maskColor="rgba(0,0,0,0.08)"
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
