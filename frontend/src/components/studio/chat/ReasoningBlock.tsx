"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { BrainCircuit, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface ReasoningBlockProps {
  /** Accumulated reasoning text for this message, built up from `reasoning_delta` WS events. */
  reasoning: string;
  /** True while more reasoning deltas are still expected for this message (i.e. before message_end). */
  streaming: boolean;
}

/**
 * Renders the agent's `<thinking>...</thinking>` stream for one assistant
 * message — a provider-agnostic convention (see root CLAUDE.md "Agent
 * streaming") where the backend splits reasoning text from user-facing text
 * and the WS layer emits them as two distinct event types:
 * `reasoning_delta` (appended here via useChatStore.appendReasoningDelta)
 * vs `text_delta` (rendered in MessageBubble's markdown bubble instead).
 * This component only ever sees the reasoning half of that split.
 *
 * Collapsible: auto-opens while `streaming` is true (so the user watches the
 * thought process live) and can be toggled manually afterward via the
 * disclosure button. Renders nothing once `reasoning` is empty (e.g. before
 * the first delta arrives).
 */
export function ReasoningBlock({ reasoning, streaming }: ReasoningBlockProps) {
  // Seed `open` from `streaming` so a message that arrives already-streaming
  // starts expanded; once toggled by the user it's independent of `streaming`.
  const [open, setOpen] = useState(streaming);

  if (!reasoning) return null;

  return (
    <div className="rounded-lg border border-border/70 bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        <BrainCircuit className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className={cn(streaming && "shimmer-text")}>
          {streaming ? "Thinking…" : "Thought process"}
        </span>
        <ChevronDown
          className={cn("ml-auto h-3.5 w-3.5 transition-transform", open && "rotate-180")}
          aria-hidden="true"
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <p className="whitespace-pre-wrap px-3 pb-3 text-xs leading-relaxed text-muted-foreground">
              {reasoning}
              {streaming && <span className="blinking-caret" aria-hidden="true" />}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
