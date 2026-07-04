"use client";

import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Loader2, Sparkles, XCircle } from "lucide-react";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/utils";
import type { ActivityItem } from "@/stores/useChatStore";

interface ActivityFeedProps {
  /** Live tool-activity log sourced from useChatStore.activity — appended to as tool_call_start/tool_call_result WS events arrive; capped to the most recent 30 items in the store itself (only the first 12 are rendered here, see `.slice(0, 12)` below). */
  activity: ActivityItem[];
  /** Current phase's human label (useChatStore.phaseLabel, set via the phase_change WS event); shown as the feed's headline while there's no phaseLabel-derived heading elsewhere. */
  phaseLabel: string | null;
}

/**
 * Shown in the curriculum panel while the agent is researching/planning and
 * there's no curriculum content to render yet. Mirrors recent tool activity
 * from the chat ("Searching: …", "Reading: example.com") alongside skeleton
 * placeholders for the eventual workflow canvas.
 */
export function ActivityFeed({ activity, phaseLabel }: ActivityFeedProps) {
  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto p-6 scrollbar-thin">
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
          <motion.span
            animate={{ rotate: 360 }}
            transition={{ duration: 2.2, repeat: Infinity, ease: "linear" }}
            className="flex"
          >
            <Sparkles className="h-4.5 w-4.5" aria-hidden="true" />
          </motion.span>
        </span>
        <div>
          <p className="text-sm font-semibold">{phaseLabel ?? "Getting started…"}</p>
          <p className="text-xs text-muted-foreground">
            Your curriculum will appear here as the agent works.
          </p>
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Live activity
        </p>
        {activity.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
            Waiting for the agent to start working…
          </div>
        ) : (
          <ul className="space-y-1.5">
            <AnimatePresence initial={false}>
              {/* The store already caps `activity` at its most recent 30 items;
                  this view only has room to show a handful at a time, so we
                  additionally slice to the first (most recent) 12 for display. */}
              {activity.slice(0, 12).map((item) => (
                <motion.li
                  key={item.id}
                  layout
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="flex items-start gap-2.5 rounded-lg border border-border/70 bg-card px-3 py-2 text-xs"
                >
                  <span className="mt-0.5 shrink-0">
                    {item.status === "running" && (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" aria-label="Running" />
                    )}
                    {item.status === "ok" && (
                      <CheckCircle2 className="h-3.5 w-3.5 text-success" aria-label="Done" />
                    )}
                    {item.status === "error" && (
                      <XCircle className="h-3.5 w-3.5 text-destructive" aria-label="Failed" />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{humanizeLabel(item.label)}</p>
                    {item.detail && (
                      <p className="truncate text-muted-foreground">{item.detail}</p>
                    )}
                  </div>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
      </div>

      <div className="space-y-3">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Curriculum outline
        </p>
        <div className={cn("flex flex-col gap-3 rounded-xl border border-border bg-muted/20 p-4")}>
          <Skeleton className="h-6 w-2/3" />
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="h-8 w-8 shrink-0 rounded-full" />
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-3.5 w-3/4" />
                <Skeleton className="h-3 w-1/2" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Turns a raw activity label into a friendlier display string, special-casing search/read/fetch/scrape tool names before falling back to a generic snake_case -> Title Case conversion. */
function humanizeLabel(label: string): string {
  const key = label.toLowerCase();
  if (key.includes("search")) return `Searching: ${label.replace(/^\w+_?/, "").trim() || "the web"}`;
  if (key.includes("read") || key.includes("fetch") || key.includes("scrape")) {
    return `Reading: ${label}`;
  }
  return label
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
