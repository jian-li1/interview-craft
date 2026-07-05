"use client";

import { motion } from "framer-motion";
import { CheckCircle2, Compass, Loader2, ListChecks, PenLine, Search, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

// Maps the backend's `phase` string (see phase_change WS event) to a
// representative icon. Falls back to Sparkles for any phase not listed here
// (e.g. future phases added server-side before the frontend catches up).
const PHASE_ICONS: Record<string, typeof Search> = {
  deep_research: Search,
  research: Search,
  planning: ListChecks,
  awaiting_approval: Compass,
  writing: PenLine,
  ready: CheckCircle2,
};

interface PhaseBannerProps {
  /** Machine-readable phase id, e.g. "research" | "planning" | "writing" | "ready" — used only to pick an icon here. */
  phase: string;
  /** Human-readable label for the current phase, shown as the banner's main text. */
  label: string;
  /** Optional task-count progress (e.g. "3/7 tasks") shown as a sub-label and progress bar. */
  progress: { completed: number; total: number; detail: string } | null;
}

/**
 * Sticky banner pinned to the top of the chat transcript showing what the
 * agent is currently doing. `phase`, `label`, and `progress` all come from
 * `useChatStore` and are populated by the `phase_change` (-> setPhase) and
 * `progress` (-> setProgress) WS events dispatched in `useChatSocket.ts` —
 * this component itself has no knowledge of the socket, it just renders
 * whatever the store currently holds. Rendered only when both `phase` and
 * `phaseLabel` are set (see ChatPanel), so there's no "no phase yet" state
 * to handle here.
 */
export function PhaseBanner({ phase, label, progress }: PhaseBannerProps) {
  const Icon = PHASE_ICONS[phase] ?? Sparkles;
  const isReady = phase === "ready";

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="sticky top-0 z-10 flex items-center gap-2.5 border-b border-border bg-card/90 px-4 py-2.5 backdrop-blur-sm"
    >
      <span
        className={cn(
          "flex h-7 w-7 items-center justify-center rounded-full",
          isReady ? "bg-success/15 text-success" : "bg-accent-soft text-accent"
        )}
      >
        {isReady ? (
          <Icon className="h-4 w-4" aria-hidden="true" />
        ) : (
          <motion.span
            animate={{ rotate: 360 }}
            transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
            className="flex"
          >
            <Loader2 className="h-4 w-4" aria-hidden="true" />
          </motion.span>
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{label}</p>
        {progress && progress.total > 0 && (
          <p className="truncate text-xs text-muted-foreground">
            {/* Resume snapshot sends detail: "" — only append "— {detail}" suffix
                when detail is non-empty. */}
            {progress.completed}/{progress.total} tasks
            {progress.detail && ` — ${progress.detail}`}
          </p>
        )}
      </div>
      {progress && progress.total > 0 && (
        <div className="hidden h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-muted sm:block">
          <motion.div
            className="h-full rounded-full bg-accent"
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(100, (progress.completed / progress.total) * 100)}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>
      )}
    </motion.div>
  );
}
