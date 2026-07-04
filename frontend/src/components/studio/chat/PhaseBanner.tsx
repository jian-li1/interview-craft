"use client";

import { motion } from "framer-motion";
import { CheckCircle2, Compass, Loader2, ListChecks, PenLine, Search, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

const PHASE_ICONS: Record<string, typeof Search> = {
  deep_research: Search,
  research: Search,
  planning: ListChecks,
  awaiting_approval: Compass,
  writing: PenLine,
  ready: CheckCircle2,
};

interface PhaseBannerProps {
  phase: string;
  label: string;
  progress: { completed: number; total: number; detail: string } | null;
}

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
            {progress.completed}/{progress.total} tasks — {progress.detail}
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
