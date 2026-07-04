import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Rocket } from "lucide-react";
import type { Node } from "@xyflow/react";

// This module is only ever imported by WorkflowView.tsx, which itself
// assumes @xyflow/react is only ever loaded client-side via
// CurriculumPanel's dynamic-import boundary (see WorkflowView.tsx's
// top-of-file comment) — no additional ssr:false handling needed here.

export type StartNodeData = {
  title: string;
  emoji: string | null;
};

export type StartNodeType = Node<StartNodeData, "start">;

/** Fixed width so the layout in WorkflowView.tsx can reliably position module
 * nodes to the right of this one without overlap, regardless of title length. */
export const START_NODE_WIDTH = 260;

/**
 * Custom React Flow node registered under the "start" node type (see
 * `nodeTypes` in WorkflowView.tsx). Purely decorative anchor at the head of
 * the linear LTR workflow chain — represents the curriculum itself (title +
 * emoji) rather than any one module, has no status, and isn't clickable
 * (no onSelect/onClick, unlike ModuleNode). Only exposes a source handle on
 * its right edge since it's always the first node in the chain.
 */
export function StartNode({ data }: NodeProps<StartNodeType>) {
  return (
    <div
      style={{ width: START_NODE_WIDTH }}
      className="flex items-center gap-3 rounded-2xl border border-accent/40 bg-gradient-accent px-4 py-3 text-white shadow-md"
    >
      <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/20 text-lg">
        {data.emoji ?? <Rocket className="h-4 w-4" aria-hidden="true" />}
      </span>
      <div className="min-w-0">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-white/80">
          Curriculum
        </p>
        <p className="truncate text-sm font-semibold">{data.title}</p>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-white" />
    </div>
  );
}
