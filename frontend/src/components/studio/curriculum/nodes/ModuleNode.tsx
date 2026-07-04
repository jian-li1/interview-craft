import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import { motion } from "framer-motion";
import { CheckCircle2, Circle, Clock, FileText, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ModuleStatus } from "@/lib/types";

export type ModuleNodeData = {
  order: number;
  title: string;
  status: ModuleStatus;
  sectionCount: number;
  estimatedMinutes: number;
  onSelect: (order: number) => void;
};

export type ModuleNodeType = Node<ModuleNodeData, "module">;

const STATUS_META: Record<ModuleStatus, { label: string; icon: typeof Circle }> = {
  planned: { label: "Planned", icon: Circle },
  writing: { label: "Writing", icon: Loader2 },
  complete: { label: "Complete", icon: CheckCircle2 },
};

export function ModuleNode({ data }: NodeProps<ModuleNodeType>) {
  const meta = STATUS_META[data.status];
  const Icon = meta.icon;

  return (
    <div>
      <Handle type="target" position={Position.Top} className="!bg-border" />
      <motion.button
        type="button"
        onClick={() => data.onSelect(data.order)}
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
      <Handle type="source" position={Position.Bottom} className="!bg-border" />
    </div>
  );
}
