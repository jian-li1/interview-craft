"use client";

import { useEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUp, Bot, EyeOff, FileText, Globe, Loader2, Square, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ModelOption } from "@/lib/types";
import { ChipSelect, SEARCH_PROVIDER_LABELS } from "@/components/ui/ChipSelect";

// Context-usage warning card appears once usage crosses 70% of the limit — ahead of
// COMPACTION_TRIGGER_FRACTION (0.8, "threshold" below), where auto-compaction actually fires.
const CONTEXT_WARN_FRACTION = 0.7;

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  /** True while a plan decision/question is pending or the socket isn't connected — see ChatPanel's composerDisabled. */
  disabled: boolean;
  /** True while the agent is actively running; swaps the send button for a stop button. */
  running: boolean;
  /** Cause-specific placeholder shown while disabled (e.g. plan vs. question gate); falls back to a generic one. */
  disabledPlaceholder?: string;
  /** Latest context-token usage estimate (from the `context_usage` WS event), or null before the first one arrives. */
  contextUsage?: { tokens: number; limit: number; threshold: number } | null;
  /** Sends a manual `compact` WS frame — wired to the "Compact now" button below. */
  onCompact?: () => void;
  /** True while a manual or auto compaction is in flight; disables the button and swaps its label. */
  compacting?: boolean;
  /** Model chip options (union of OPENAI_MODEL/GEMINI_MODEL), from `session_ready`. */
  availableModels: ModelOption[];
  /** Model chip's current selection; null before `session_ready` arrives. */
  selectedModel: string | null;
  onModelChange: (id: string) => void;
  /** Search-provider chip options, from `session_ready`. */
  searchProviders: string[];
  /** Search-provider chip's current selection; null before `session_ready` arrives. */
  selectedSearchProvider: string | null;
  onSearchProviderChange: (name: string) => void;
  /** The Reader's current written section, or null to hide the "current section" chip
   * entirely (wrong view/phase/no section/section still "planned" — see ChatPanel). */
  sectionContext: { label: string } | null;
  /** Whether the section-context chip is in its "included" (true) or "excluded" (false)
   * state — sticky for the session, defaults to included. */
  sectionContextOn: boolean;
  /** Toggles `sectionContextOn`; the chip stays clickable even when excluded. */
  onToggleSectionContext: () => void;
}

/**
 * Bottom-pinned message input for the chat panel. Inside a single outlined box: a
 * controlled, auto-growing textarea on top (grows up to 200px, then scrolls), and a
 * bottom row with the model/search-provider chips (and, when applicable, the "current
 * section" toggle chip — see `sectionContext`) on the left and a single action
 * button on the right that toggles between "send" and "stop":
 *  - `running` (agent is mid-turn) shows a Stop button that calls `onStop`,
 *    which forwards to `ChatSocket.sendStop()` via the parent.
 *  - otherwise shows a Send button, disabled when `disabled` is true or the
 *    draft is empty/whitespace-only.
 * `disabled` also greys out and locks the textarea and both chips (e.g. while a HITL
 * plan decision is awaiting the user, per ChatPanel's composerDisabled) and swaps the
 * placeholder to explain why input is blocked.
 */
export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  disabled,
  running,
  disabledPlaceholder,
  contextUsage,
  onCompact,
  compacting,
  availableModels,
  selectedModel,
  onModelChange,
  searchProviders,
  selectedSearchProvider,
  onSearchProviderChange,
  sectionContext,
  sectionContextOn,
  onToggleSectionContext,
}: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // Warning card shows once usage crosses CONTEXT_WARN_FRACTION of the limit — guard
  // against a zero/missing limit (division by zero) with the `limit > 0` check.
  const showContextWarning =
    !!contextUsage && contextUsage.limit > 0 && contextUsage.tokens / contextUsage.limit >= CONTEXT_WARN_FRACTION;
  const contextPct = contextUsage
    ? Math.min(100, Math.round((contextUsage.tokens / contextUsage.limit) * 100))
    : 0;

  // Auto-grow the textarea to fit its content on every value change, capped
  // at 200px (matches max-h-[200px] below) — past that it scrolls internally
  // instead of pushing the rest of the layout around.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  // Keyboard shortcut: Enter submits, Shift+Enter inserts a newline (see the
  // hint text rendered below the input). Submission is a no-op if the draft
  // is empty/whitespace or the composer is disabled.
  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (value.trim() && !disabled) onSend();
    }
  }

  return (
    <div className="border-t border-border p-3">
      {/* Context-usage warning card, visually attached to the top of the input box below
          (rounded-b-xl swap on the input makes the two read as one unit — see cn() call). */}
      <AnimatePresence initial={false}>
        {showContextWarning && contextUsage && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="flex items-center gap-2 rounded-t-xl border border-b-0 border-warning/40 bg-warning/10 px-3 py-2 text-xs">
              <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <span className="font-medium text-warning">Context {contextPct}% full</span>
                <span className="text-muted-foreground">
                  {" "}
                  &middot; Older messages auto-compact at {Math.round(contextUsage.threshold * 100)}%.
                </span>
              </span>
              <button
                type="button"
                onClick={onCompact}
                disabled={running || compacting}
                className="flex h-7 shrink-0 items-center gap-1 rounded-lg border border-warning/40 bg-warning/15 px-2.5 text-xs text-warning transition-colors hover:bg-warning/25 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {compacting && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
                {compacting ? "Compacting…" : "Compact now"}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div
        className={cn(
          "flex flex-col border border-input bg-background p-2 transition-colors focus-within:ring-2 focus-within:ring-ring",
          // Swap full rounding for bottom-only when the warning card is attached above,
          // so the two read as one continuous unit rather than two separate boxes.
          showContextWarning ? "rounded-b-xl" : "rounded-xl",
          disabled && "opacity-60"
        )}
      >
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={1}
          aria-label="Message"
          placeholder={
            // Disabled placeholder names the actual blocker (plan card, question card,
            // or connection) — the parent knows the cause, we just render it.
            disabled
              ? (disabledPlaceholder ?? "Waiting…")
              : "Ask anything, or describe what to change…"
          }
          // placeholder:truncate forces the placeholder pseudo-element to a single line with
          // an ellipsis (independent of the textarea's own multi-line wrap behavior) — at
          // narrow widths the un-truncated placeholder used to wrap to a 2nd line and get
          // clipped by the fixed single-row height, rendering as hidden/cut-off text.
          className="max-h-[200px] w-full resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:truncate placeholder:text-muted-foreground disabled:cursor-not-allowed"
        />

        {/* Thin divider between the textarea and the chip row below it. */}
        <div className="mt-1 border-t border-border" />

        {/* Chip row: model + search-provider selectors on the left, action button pinned to
            the right. Chips live in their own no-wrap, shrinkable container so on narrow
            widths they scale down (and truncate their labels) instead of wrapping to a new
            line or pushing the send/stop button out of place — that button sits outside
            this wrapper (shrink-0) so it always stays fixed at the row's end. */}
        <div className="flex items-center gap-1.5 px-1 pt-1.5 pb-0.5">
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            <ChipSelect
              icon={Bot}
              ariaLabel="Select model"
              value={selectedModel}
              onChange={onModelChange}
              disabled={disabled}
              options={availableModels.map((m) => ({ id: m.id, label: m.id, badge: m.provider }))}
            />
            <ChipSelect
              icon={Globe}
              ariaLabel="Select search provider"
              value={selectedSearchProvider}
              onChange={onSearchProviderChange}
              disabled={disabled}
              options={searchProviders.map((p) => ({ id: p, label: SEARCH_PROVIDER_LABELS[p] ?? p }))}
            />
            {/* "Current section as context" toggle — VS Code's "current file as context" chip,
                adapted for the curriculum Reader. Only rendered when ChatPanel resolves a
                written, in-context-window section (see its sectionContext memo); a plain toggle
                button (not a ChipSelect popover), styled to match ChipSelect's chip exactly so
                it reads as a sibling of the model/search chips. */}
            {sectionContext !== null && (
              <button
                type="button"
                onClick={onToggleSectionContext}
                disabled={disabled}
                aria-pressed={sectionContextOn}
                aria-label={
                  sectionContextOn ? "Exclude current section as context" : "Include current section as context"
                }
                title={
                  sectionContextOn
                    ? `Sending "${sectionContext.label}" as context — click to exclude`
                    : `Not sending "${sectionContext.label}" as context — click to include`
                }
                className={cn(
                  // min-w-0 lets this chip shrink below its label's natural width (it's a
                  // direct flex item here, unlike ChipSelect's button) so it scales down
                  // alongside its siblings instead of wrapping to a new line.
                  "flex h-7 min-w-0 max-w-[160px] items-center gap-1.5 rounded-lg border border-border px-2 text-xs text-muted-foreground transition-colors",
                  "hover:bg-accent-soft hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  // Excluded state reads as "off" (dimmed) while staying clickable to re-include.
                  !sectionContextOn && "opacity-50",
                  disabled && "pointer-events-none opacity-50"
                )}
              >
                {sectionContextOn ? (
                  <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                ) : (
                  <EyeOff className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                )}
                <span className="min-w-0 flex-1 truncate text-left">{sectionContext.label}</span>
              </button>
            )}
          </div>
          {running ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="Stop the agent"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-destructive text-destructive-foreground shadow-sm transition-opacity hover:opacity-90"
            >
              <Square className="h-3.5 w-3.5" aria-hidden="true" fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={onSend}
              disabled={disabled || !value.trim()}
              aria-label="Send message"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm transition-opacity disabled:opacity-40"
            >
              <ArrowUp className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
      <p className="mt-1.5 px-1 text-[11px] text-muted-foreground">
        Enter to send &middot; Shift+Enter for a new line
      </p>
    </div>
  );
}
