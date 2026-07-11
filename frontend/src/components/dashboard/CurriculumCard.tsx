"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { BookOpen, Layers, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { curriculaApi, ApiError } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import type { CurriculumSummary } from "@/lib/types";

const STATUS_META: Record<
  CurriculumSummary["status"],
  { label: string; variant: "default" | "success" | "warning" | "destructive" | "info" | "outline" }
> = {
  researching: { label: "Researching", variant: "info" },
  planning: { label: "Planning", variant: "info" },
  awaiting_approval: { label: "Awaiting approval", variant: "warning" },
  writing: { label: "Writing", variant: "warning" },
  reviewing: { label: "Reviewing", variant: "info" },
  ready: { label: "Ready", variant: "success" },
  error: { label: "Error", variant: "destructive" },
};

interface CurriculumCardProps {
  curriculum: CurriculumSummary;
  onDeleted: (id: string) => void;
}

/**
 * A single curriculum tile in the dashboard grid. Renders the title, the
 * agent-written description (falling back to the originating user prompt for
 * legacy curricula or pre-plan phases), a status badge (mapped from
 * `CurriculumSummary["status"]` via `STATUS_META`), and — while the agent is
 * still generating (researching/planning/writing/reviewing) — an animated
 * progress bar driven by `curriculum.progress`. Clicking the card navigates
 * to the studio for its conversation; the trash icon opens a `ConfirmDialog`
 * and, on confirm, calls `curriculaApi.remove` then notifies the parent via
 * `onDeleted` so it can drop the item from its list (this component holds no
 * list state itself).
 */
export function CurriculumCard({ curriculum, onDeleted }: CurriculumCardProps) {
  const router = useRouter();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const status = STATUS_META[curriculum.status];
  // "reviewing" counts as generating too — the agent is still actively editing sections.
  const isGenerating = ["researching", "planning", "writing", "reviewing"].includes(curriculum.status);
  const progressPct =
    curriculum.progress.total_tasks > 0
      ? Math.round((curriculum.progress.completed_tasks / curriculum.progress.total_tasks) * 100)
      : 0;

  async function handleDelete() {
    setDeleting(true);
    try {
      await curriculaApi.remove(curriculum.id);
      onDeleted(curriculum.id);
      toast.success("Curriculum deleted");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to delete");
    } finally {
      setDeleting(false);
      setConfirmOpen(false);
    }
  }

  return (
    <>
      <motion.div
        layout
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96 }}
        transition={{ duration: 0.25 }}
      >
        <Card
          role="button"
          tabIndex={0}
          onClick={() => router.push(`/studio/${curriculum.conversation_id}`)}
          onKeyDown={(e) => {
            if (e.key === "Enter") router.push(`/studio/${curriculum.conversation_id}`);
          }}
          className="group flex h-full cursor-pointer flex-col gap-3 p-5 transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <div className="flex items-start justify-between gap-2">
            <span className="text-2xl leading-none">{curriculum.emoji ?? "📘"}</span>
            <button
              type="button"
              aria-label={`Delete ${curriculum.title}`}
              onClick={(e) => {
                e.stopPropagation();
                setConfirmOpen(true);
              }}
              className="rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>

          <div className="flex-1">
            <h3 className="font-semibold leading-snug line-clamp-2">{curriculum.title}</h3>
            {/* Falls back to user_prompt for legacy curricula or before a plan is first proposed. */}
            <p className="mt-1 text-xs text-muted-foreground line-clamp-3">
              {curriculum.description || curriculum.user_prompt}
            </p>
          </div>

          <Badge variant={status.variant} className="w-fit">
            {status.label}
          </Badge>

          {isGenerating && (
            <div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <motion.div
                  className="h-full rounded-full bg-accent"
                  initial={{ width: 0 }}
                  animate={{ width: `${progressPct}%` }}
                  transition={{ duration: 0.4 }}
                />
              </div>
              <p className="mt-1 truncate text-[11px] text-muted-foreground">
                {curriculum.progress.detail || "Working…"}
              </p>
            </div>
          )}

          <div className="flex items-center justify-between border-t border-border pt-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <Layers className="h-3.5 w-3.5" aria-hidden="true" />
              {curriculum.module_count} modules
            </span>
            <span className="flex items-center gap-1">
              <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
              {timeAgo(curriculum.updated_at)}
            </span>
          </div>
        </Card>
      </motion.div>

      <ConfirmDialog
        open={confirmOpen}
        title="Delete this curriculum?"
        description={`"${curriculum.title}" and all its modules will be permanently deleted.`}
        confirmLabel="Delete"
        destructive
        loading={deleting}
        onConfirm={handleDelete}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}
