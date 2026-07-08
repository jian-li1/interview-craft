"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  CheckCircle2,
  ChevronDown,
  Circle,
  Loader2,
  Sparkles,
  XCircle,
} from "lucide-react";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn, formatElapsed } from "@/lib/utils";
import type { ActivityItem, ProposedPlan } from "@/stores/useChatStore";

interface ActivityFeedProps {
  /** Live tool-activity log sourced from useChatStore.activity — appended to as tool_call_start/tool_call_result WS events arrive, and rebuilt from persisted history on hydrateHistory. The store caps this at 30 entries; every entry is rendered here (in a scrollable sub-list — see the wrapper below). */
  activity: ActivityItem[];
  /** Current phase's human label (useChatStore.phaseLabel, set via the phase_change WS event); shown as the feed's headline while there's no phaseLabel-derived heading elsewhere. */
  phaseLabel: string | null;
  /** The currently-proposed/approved task plan (useChatStore.plan), if any. Drives the "Curriculum outline" section below: a real per-task status list once a plan exists, skeleton placeholders before one does. */
  plan: ProposedPlan | null;
}

/**
 * Explicit map from raw tool name -> a friendly, human-readable action label. Replaces
 * the previous `humanizeLabel` heuristic (which produced the "Searching: the web" bug —
 * stripping a token off the tool name and falling back to the literal word "the web"
 * instead of using the query, which actually lives in `detail`). Falls back to a
 * Title-Cased snake_case conversion for any tool name not listed here (e.g. a new tool
 * added server-side before this map is updated).
 */
const TOOL_ACTION_LABELS: Record<string, string> = {
  web_search: "Searching the web",
  fetch_url: "Reading a web page",
  save_sources: "Saving sources",
  list_curriculum_structure: "Reviewing the curriculum structure",
  write_section: "Writing a section",
  read_section: "Reading a section",
  update_section: "Updating a section",
  write_curriculum_overview: "Writing the overview",
  set_curriculum_title: "Naming the curriculum",
  set_module_status: "Updating module status",
  request_user_input: "Asking you a question",
  update_scratchpad: "Updating working notes",
  complete_phase: "Moving to the next phase",
  get_user_profile: "Reading your profile",
  propose_task_plan: "Proposing the task plan",
  get_task_plan: "Checking the task plan",
};

/** Friendly label for a raw tool name, falling back to Title Case snake_case -> spaced words. */
function actionLabel(name: string): string {
  return (
    TOOL_ACTION_LABELS[name] ??
    name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

/**
 * One collapsible activity-log row, modeled on `ToolCallItem` in
 * `components/studio/chat/ToolCallCard.tsx` (same visual language: status icon,
 * friendly label + subtitle, elapsed time, chevron disclosure revealing raw
 * input/output JSON). Kept as its own component so each row owns its own `open` state
 * independently.
 */
function ActivityRow({ item }: { item: ActivityItem }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="min-w-0 rounded-lg border border-border/70 bg-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full min-w-0 items-center gap-2.5 px-3 py-2 text-left text-xs"
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
          <p className="truncate font-medium">{actionLabel(item.name)}</p>
          {item.detail && <p className="truncate text-muted-foreground">{item.detail}</p>}
        </div>
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          {item.elapsed_ms !== undefined && item.status !== "running" && (
            <span className="text-[10px] tabular-nums text-muted-foreground">
              {formatElapsed(item.elapsed_ms)}
            </span>
          )}
          <ChevronDown
            className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform", open && "rotate-180")}
            aria-hidden="true"
          />
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-border/70 p-3">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Input
            </p>
            {/* break-all prevents long URLs from forcing horizontal overflow. */}
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted/60 p-2 text-[11px] scrollbar-thin">
              {JSON.stringify(item.input, null, 2)}
            </pre>
          </div>
          {item.output_preview && (
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Output
              </p>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted/60 p-2 text-[11px] scrollbar-thin">
                {item.output_preview}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Shown in the curriculum panel while the agent is researching/planning and there's no
 * curriculum content to render yet. Two live sections:
 *  - "Live activity": every item in `activity` (the store already caps this at 30),
 *    each row an independent collapsible disclosure, in its own scrollable
 *    (max-h-[50vh]) sub-list so a long-running session doesn't push the outline section
 *    below the fold.
 *  - "Curriculum outline": once `plan` exists, a real per-task status list (done /
 *    in-progress / pending icon + title) instead of the skeleton placeholders shown
 *    before any plan has been proposed — fixes the outline card being stuck on
 *    skeletons indefinitely once a plan actually exists.
 *
 * `overflow-x-hidden` on the root plus `min-w-0` on every text-holding flex child is
 * defense-in-depth against the horizontal-overflow bug this panel previously had (long
 * nowrap activity text widening the whole studio page — see the `min-w-0` fix on the
 * desktop curriculum column in studio/[conversationId]/page.tsx).
 */
export function ActivityFeed({ activity, phaseLabel, plan }: ActivityFeedProps) {
  return (
    <div className="flex h-full flex-col gap-6 overflow-x-hidden overflow-y-auto p-6 scrollbar-thin">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
          <motion.span
            animate={{ rotate: 360 }}
            transition={{ duration: 2.2, repeat: Infinity, ease: "linear" }}
            className="flex"
          >
            <Sparkles className="h-4.5 w-4.5" aria-hidden="true" />
          </motion.span>
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{phaseLabel ?? "Getting started…"}</p>
          <p className="truncate text-xs text-muted-foreground">
            Your curriculum will appear here as the agent works.
          </p>
        </div>
      </div>

      <div className="min-w-0 space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Live activity
        </p>
        {activity.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
            Waiting for the agent to start working…
          </div>
        ) : (
          // Max-h [50vh], no layout/exit animation: the `layout` prop was implicated in
          // max-update-depth errors; do not reintroduce it.
          <ul className="max-h-[50vh] space-y-1.5 overflow-y-auto scrollbar-thin">
            {activity.map((item) => (
              <motion.li
                key={item.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.15 }}
                className="min-w-0"
              >
                <ActivityRow item={item} />
              </motion.li>
            ))}
          </ul>
        )}
      </div>

      <div className="min-w-0 space-y-3">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Curriculum outline
        </p>
        {plan ? (
          <div className="flex min-w-0 flex-col gap-1.5 rounded-xl border border-border bg-muted/20 p-4">
            {plan.tasks.map((task) => (
              <div key={task.id} className="flex min-w-0 items-center gap-2 text-xs">
                {task.status === "done" ? (
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" aria-label="Done" />
                ) : task.status === "in_progress" ? (
                  <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" aria-label="In progress" />
                ) : (
                  <Circle className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-label="Pending" />
                )}
                <span className="truncate">{task.title}</span>
              </div>
            ))}
          </div>
        ) : (
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
        )}
      </div>
    </div>
  );
}
