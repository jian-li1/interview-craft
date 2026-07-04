import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Rocket } from "lucide-react";
import type { Node } from "@xyflow/react";

export type StartNodeData = {
  title: string;
  emoji: string | null;
};

export type StartNodeType = Node<StartNodeData, "start">;

export function StartNode({ data }: NodeProps<StartNodeType>) {
  return (
    <div className="flex min-w-[220px] items-center gap-3 rounded-2xl border border-accent/40 bg-gradient-accent px-4 py-3 text-white shadow-md">
      <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/20 text-lg">
        {data.emoji ?? <Rocket className="h-4 w-4" aria-hidden="true" />}
      </span>
      <div className="min-w-0">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-white/80">
          Curriculum
        </p>
        <p className="truncate text-sm font-semibold">{data.title}</p>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-white" />
    </div>
  );
}
