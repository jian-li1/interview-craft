import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import { motion } from "framer-motion";
import { CheckCircle2, Circle, Clock, FileText, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ModuleStatus } from "@/lib/types";

// This module is only ever imported by WorkflowView.tsx, which itself
// assumes @xyflow/react is only ever loaded client-side via
// CurriculumPanel's dynamic-import boundary (see WorkflowView.tsx's
// top-of-file comment) — no additional ssr:false handling needed here.

export type ModuleNodeData = {
  id: string;
  order: number;
  title: string;
  /** Module's current status as tracked server-side (planned/writing/complete); drives this card's border/badge/progress-bar and the connecting StatusEdge's animation. */
  status: ModuleStatus;
  sectionCount: number;
  estimatedMinutes: number;
  /** Called with this module's id on click — wired by WorkflowView to CurriculumPanel.handleSelectModule, which switches the panel to ReaderView focused on this module's first section. */
  onSelect: (moduleId: string) => void;
};

export type ModuleNodeType = Node<ModuleNodeData, "module">;

/** Per-status label + icon used for the card's status badge. */
const STATUS_META: Record<ModuleStatus, { label: string; icon: typeof Circle }> = {
  planned: { label: "Planned", icon: Circle },
  writing: { label: "Writing", icon: Loader2 },
  complete: { label: "Complete", icon: CheckCircle2 },
};

/**
 * Custom React Flow node registered under the "module" node type (see
 * `nodeTypes` in WorkflowView.tsx). Renders one module as a clickable card
 * showing its order, title, status badge, section count, and estimated
 * reading time. Visual state is entirely status-driven:
 *  - `planned` — dashed border, muted badge, static icon.
 *  - `writing` — accent border, accent badge, spinning icon, plus an
 *    animated indeterminate progress bar along the bottom of the card.
 *  - `complete` — success-tinted border and badge, static check icon.
 * Clicking the card calls `data.onSelect(data.id)` (see ModuleNodeData);
 * the node itself has no selection/drag behavior since WorkflowView disables
 * React Flow's built-in interactivity (`nodesDraggable`/`elementsSelectable`
 * are both false).
 */
export function ModuleNode({ data }: NodeProps<ModuleNodeType>) {
  const meta = STATUS_META[data.status];
  const Icon = meta.icon;

  return (
    <div>
      <Handle type="target" position={Position.Left} className="!bg-border" />
      <motion.button
        type="button"
        onClick={() => data.onSelect(data.id)}
        layout
        className={cn(
          "flex w-[240px] flex-col gap-2 rounded-xl border bg-card p-3.5 text-left shadow-sm transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          data.status === "planned" && "border-dashed border-border",
          data.status === "writing" && "border-accent",
          data.status === "complete" && "border-success/50"
        )}
      >
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-semibold">
            {data.order}
          </span>
          <p className="min-w-0 flex-1 truncate text-sm font-semibold">{data.title}</p>
        </div>

        <div className="flex items-center gap-1.5 text-xs">
          <span
            className={cn(
              "flex items-center gap-1 rounded-full px-2 py-0.5 font-medium",
              data.status === "planned" && "bg-muted text-muted-foreground",
              data.status === "writing" && "bg-accent-soft text-accent",
              data.status === "complete" && "bg-success/15 text-success"
            )}
          >
            <Icon
              className={cn("h-3 w-3", data.status === "writing" && "animate-spin")}
              aria-hidden="true"
            />
            {meta.label}
          </span>
        </div>

        <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1">
            <FileText className="h-3 w-3" aria-hidden="true" />
            {data.sectionCount} sections
          </span>
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" aria-hidden="true" />
            {data.estimatedMinutes}m
          </span>
        </div>

        {data.status === "writing" && (
          <motion.div
            className="h-0.5 w-full overflow-hidden rounded-full bg-accent/20"
            aria-hidden="true"
          >
            <motion.div
              className="h-full w-1/3 rounded-full bg-accent"
              animate={{ x: ["0%", "200%"] }}
              transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
            />
          </motion.div>
        )}
      </motion.button>
      <Handle type="source" position={Position.Right} className="!bg-border" />
    </div>
  );
}
