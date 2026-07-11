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
  /** Agent-written 1-2 sentence curriculum description, shown under the title; "" for legacy curricula. */
  description: string;
};

export type StartNodeType = Node<StartNodeData, "start">;

/** Fixed width so the layout in WorkflowView.tsx can reliably position module
 * nodes to the right of this one without overlap, regardless of title length.
 * Matches module cards' `w-[280px]` so both node kinds align visually. */
export const START_NODE_WIDTH = 280;

/**
 * Custom React Flow node registered under the "start" node type (see
 * `nodeTypes` in WorkflowView.tsx). Purely decorative anchor at the head of
 * the linear LTR workflow chain — represents the curriculum itself (title,
 * emoji, and agent-written description, with the title wrapping up to two
 * lines) rather than any one module, has no status, and isn't clickable
 * (no onSelect/onClick, unlike ModuleNode). Only exposes a source handle on
 * its right edge since it's always the first node in the chain.
 */
export function StartNode({ data }: NodeProps<StartNodeType>) {
  return (
    <div
      style={{ width: START_NODE_WIDTH }}
      className="flex flex-col gap-2 rounded-2xl border border-accent/40 bg-gradient-accent p-3.5 text-white shadow-md"
    >
      <div className="flex items-center gap-3">
        {/* shrink-0 stops flexbox from squishing the badge when the title wraps; rounded-xl matches module card badges */}
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/20 text-lg">
          {data.emoji ?? <Rocket className="h-4 w-4" aria-hidden="true" />}
        </span>
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-white/80">
            Curriculum
          </p>
          {/* line-clamp-2 wraps long titles to two lines instead of truncating */}
          <p className="line-clamp-2 text-sm font-semibold">{data.title}</p>
        </div>
      </div>
      {/* only rendered when non-empty; legacy curricula may lack it — white/80 (not text-muted-foreground) since this card sits on the accent gradient */}
      {data.description && (
        <p className="text-xs leading-snug text-white/80 line-clamp-3">{data.description}</p>
      )}
      <Handle type="source" position={Position.Right} className="!bg-white" />
    </div>
  );
}
