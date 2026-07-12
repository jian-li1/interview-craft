"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, FoldVertical, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CompactionItem } from "@/stores/useChatStore";

interface CompactionChipProps {
  item: CompactionItem;
}

/** Formats a raw token count as a compact label, e.g. 48200 -> "48.2k", 900 -> "900". */
function formatTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;
}

/**
 * Full-width divider-style chip interleaved into the chat transcript marking a
 * compaction event (see `ChatPanel`'s interleaving logic). Two states, driven by
 * `item.status`:
 *  - `"running"` — a spinner + "Auto-compacting conversation…", rendered as soon as the
 *    `compaction_start` WS event arrives (before the small-model summarization finishes).
 *  - `"done"` — resolved in place (or, after a reconnect, appended directly in this
 *    state) with a before/after token-count detail and a toggle revealing the agent's
 *    FULL rolling summary in a scroll-capped dropdown (matching ReasoningBlock's pane).
 *
 * Survives page reloads: the WS reconnect snapshot replays a `done`-shaped `compaction`
 * event for the conversation's last checkpoint, which `useChatStore.finishCompaction`
 * appends directly (see that action's dedupe branch).
 */
export function CompactionChip({ item }: CompactionChipProps) {
  // Expandable summary panel, closed by default — same pattern as ToolCallCard/ReasoningBlock.
  const [open, setOpen] = useState(false);
  const isRunning = item.status === "running";
  // Only show the token detail when we actually have a non-zero before count (legacy
  // reconnect replays for pre-checkpoint conversations default both counts to 0).
  const hasTokenDetail = !isRunning && !!item.tokensBefore;
  const hasSummary = !isRunning && !!item.summary;

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="w-full"
    >
      <div className="flex items-center gap-3 py-1">
        <span className="h-px flex-1 bg-border" aria-hidden="true" />

        {hasSummary ? (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className="flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-muted/50 px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted"
          >
            <CompactionPillContent item={item} hasTokenDetail={hasTokenDetail} />
            <ChevronDown
              className={cn("h-3 w-3 shrink-0 transition-transform", open && "rotate-180")}
              aria-hidden="true"
            />
          </button>
        ) : (
          <span className="flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-muted/50 px-3 py-1 text-xs text-muted-foreground">
            <CompactionPillContent item={item} hasTokenDetail={hasTokenDetail} />
          </span>
        )}

        <span className="h-px flex-1 bg-border" aria-hidden="true" />
      </div>

      {/* Expandable full-summary panel, only reachable once hasSummary rendered the toggle button. */}
      <AnimatePresence initial={false}>
        {open && hasSummary && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            {/* Fills the transcript's full width (not capped like ReasoningBlock's pane) since
                this chip is already a full-width divider row rather than a narrow bubble. */}
            <div className="w-full rounded-lg border border-border/70 bg-muted/30 p-3 text-left">
              {/* Caption sits OUTSIDE the scrollable pane below so it never scrolls away. */}
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Summary of compacted history
              </p>
              {/* Scroll-capped pane, mirroring ReasoningBlock's reasoning panel styling. */}
              <p className="mt-1 max-h-60 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground scrollbar-thin">
                {item.summary}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

/** Icon + label + optional token-count text shared by both pill variants above. */
function CompactionPillContent({
  item,
  hasTokenDetail,
}: {
  item: CompactionItem;
  hasTokenDetail: boolean;
}) {
  if (item.status === "running") {
    return (
      <>
        <Loader2 className="h-3 w-3 shrink-0 animate-spin" aria-hidden="true" />
        Auto-compacting conversation…
      </>
    );
  }
  return (
    <>
      <FoldVertical className="h-3 w-3 shrink-0" aria-hidden="true" />
      Auto-compacted
      {hasTokenDetail && (
        <span className="tabular-nums text-muted-foreground/80">
          &middot; {formatTokens(item.tokensBefore!)} &rarr; {formatTokens(item.tokensAfter!)} tokens
        </span>
      )}
    </>
  );
}
