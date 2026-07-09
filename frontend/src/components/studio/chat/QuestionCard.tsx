"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { HelpCircle, Send } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

interface QuestionCardProps {
  /** The clarifying question posed by the agent's `request_user_input` tool call (HITL pause), sourced from useChatStore's `pendingQuestion` field (set via the `user_input_requested` WS event -> askQuestion). */
  question: string;
  /** Quick-pick choices, or null/empty when only free-text is offered. */
  options: string[] | null;
  disabled: boolean;
  /**
   * Called with the chosen answer text — either a clicked option's label or
   * trimmed free-text input. The caller (ChatPanel.handleQuestionAnswer)
   * sends this through the exact same path as a normal composer message
   * (optimistic append + `user_message` WS frame), since resumption after
   * this HITL gate is an ordinary chat message, not a dedicated frame type.
   */
  onAnswer: (text: string) => void;
}

/**
 * HITL (human-in-the-loop) card rendered inline in the transcript whenever
 * the agent's `request_user_input` tool pauses the ReAct loop awaiting a
 * clarifying answer (see root CLAUDE.md "HITL" section). Mirrors
 * `PlanApprovalCard`'s visual language: same container styling, entrance
 * animation, and theme tokens. Offers two answer paths:
 *  - **Quick-pick options** (if provided) — tappable choice rows; clicking
 *    one immediately submits that option's text as the answer.
 *  - **Free text** — always shown below the options (even when options
 *    exist), since the user may want to answer in their own words; Enter or
 *    the send button submits, disabled while empty/whitespace-only.
 * Either path unblocks the composer (see ChatPanel's composerDisabled, which
 * gates on `pendingQuestion`) once the parent resolves the question.
 */
export function QuestionCard({ question, options, disabled, onAnswer }: QuestionCardProps) {
  // Draft text for the free-text answer path.
  const [draft, setDraft] = useState("");

  // Submits the free-text draft if it's non-empty after trimming.
  function submitDraft() {
    const trimmed = draft.trim();
    if (!trimmed) return;
    onAnswer(trimmed);
    setDraft("");
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.25 }}
      className="rounded-xl border border-accent/30 bg-accent-soft/40 p-4"
    >
      <div className="flex items-center gap-2">
        <HelpCircle className="h-4 w-4 text-accent" aria-hidden="true" />
        <h3 className="text-sm font-semibold">The agent needs your input</h3>
      </div>

      <p className="mt-3 text-sm font-medium text-foreground">{question}</p>

      {options && options.length > 0 && (
        <div className="mt-3 flex flex-col gap-1.5">
          {options.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => onAnswer(option)}
              disabled={disabled}
              className="rounded-lg border border-border bg-card px-3 py-2 text-left text-xs font-medium transition-colors hover:border-accent/50 hover:bg-accent-soft/60 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {option}
            </button>
          ))}
        </div>
      )}

      {/* Free-text input is always present, even with quick-pick options — the
          user may want to answer in their own words. It's the only input when
          `options` is empty. */}
      <div className="mt-3 flex items-center gap-2">
        {/* "Or…" phrasing only reads right when quick-pick options are rendered above. */}
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submitDraft();
          }}
          placeholder={options && options.length > 0 ? "Or type your own answer…" : "Type your answer…"}
          disabled={disabled}
          className="h-9 text-xs"
        />
        <Button
          size="sm"
          onClick={submitDraft}
          disabled={disabled || !draft.trim()}
          aria-label="Send answer"
        >
          <Send className="h-3.5 w-3.5" aria-hidden="true" />
        </Button>
      </div>
    </motion.div>
  );
}
