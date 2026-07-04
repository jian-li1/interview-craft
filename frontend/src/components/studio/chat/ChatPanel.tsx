"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { Loader2, MessageCircle, WifiOff } from "lucide-react";
import { MessageBubble } from "@/components/studio/chat/MessageBubble";
import { PhaseBanner } from "@/components/studio/chat/PhaseBanner";
import { PlanApprovalCard } from "@/components/studio/chat/PlanApprovalCard";
import { Composer } from "@/components/studio/chat/Composer";
import { ScrollToBottomPill } from "@/components/studio/chat/ScrollToBottomPill";
import { EmptyState } from "@/components/ui/EmptyState";
import { useChatStore } from "@/stores/useChatStore";
import type { ChatSocket } from "@/lib/ws";

interface ChatPanelProps {
  conversationId: string;
  socketRef: React.RefObject<ChatSocket | null>;
  historyLoading: boolean;
  historyError: string | null;
  prefillText?: string;
  onPrefillConsumed?: () => void;
}

/**
 * The main chat surface for one conversation/studio session. Reads all
 * message/phase/plan/progress state from `useChatStore` (populated via WS
 * events dispatched in `useChatSocket.ts` — see that hook's doc comment for
 * the full event -> store-action mapping) and composes the pieces that make
 * up the transcript:
 *  - `PhaseBanner` — sticky header showing the current agent phase/label/progress.
 *  - `MessageBubble` (one per message) — which itself nests `ReasoningBlock`
 *    (the `<thinking>` stream) and `ToolCallGroup`/`ToolCallCard`.
 *  - `PlanApprovalCard` — rendered inline in the transcript when a HITL plan
 *    is awaiting approve/modify.
 *  - `ScrollToBottomPill` — floating affordance shown once the user has
 *    scrolled away from the bottom while new messages keep arriving.
 *  - `Composer` — the input box pinned to the bottom.
 *
 * `conversationId` is accepted for future use (keying/analytics) even though
 * this component currently reads its data purely from the store rather than
 * fetching by id itself; the socket lifecycle for a given conversation is
 * owned by the caller via `socketRef`.
 */
export function ChatPanel({
  conversationId,
  socketRef,
  historyLoading,
  historyError,
  prefillText,
  onPrefillConsumed,
}: ChatPanelProps) {
  const messages = useChatStore((s) => s.messages);
  const phase = useChatStore((s) => s.phase);
  const phaseLabel = useChatStore((s) => s.phaseLabel);
  const progress = useChatStore((s) => s.progress);
  const plan = useChatStore((s) => s.plan);
  const planAwaitingDecision = useChatStore((s) => s.planAwaitingDecision);
  const agentRunning = useChatStore((s) => s.agentRunning);
  const connectionState = useChatStore((s) => s.connectionState);
  const addUserMessage = useChatStore((s) => s.addUserMessage);
  const resolvePlan = useChatStore((s) => s.resolvePlan);
  const setAgentRunning = useChatStore((s) => s.setAgentRunning);

  const [draft, setDraft] = useState("");
  const [showScrollPill, setShowScrollPill] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Tracks whether the user has manually scrolled away from the bottom of
  // the transcript. Stored in a ref (not state) because it's read/written
  // from the scroll handler on every scroll event and must not trigger
  // re-renders itself — only `showScrollPill` (derived from it) does.
  const userScrolledUp = useRef(false);

  // Explain-a-section prefill: when the reader view's "explain this" button
  // fires (via CurriculumPanel -> onExplain), the parent passes the prompt
  // text down as `prefillText`; drop it into the draft and notify the parent
  // so it can clear the prop and avoid re-appending on every render.
  useEffect(() => {
    if (prefillText) {
      setDraft((prev) => (prev ? `${prev}\n${prefillText}` : prefillText));
      onPrefillConsumed?.();
    }
  }, [prefillText, onPrefillConsumed]);

  // Scroll-pinning: auto-scroll to the newest message whenever `messages`
  // changes (new message added, or streaming deltas append to the last one),
  // UNLESS the user has deliberately scrolled up to read earlier context. In
  // that case, don't yank them back down — instead surface the
  // ScrollToBottomPill so they can opt back in.
  useEffect(() => {
    if (!userScrolledUp.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
      setShowScrollPill(false);
    } else {
      setShowScrollPill(true);
    }
  }, [messages]);

  // Recompute the "am I scrolled up" flag on every scroll. A small threshold
  // (80px) counts as "at bottom" so minor rendering jitter / scrollbar
  // rounding doesn't spuriously flip the pill on and off.
  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    userScrolledUp.current = !atBottom;
    if (atBottom) setShowScrollPill(false);
  }

  // Explicit "jump to bottom" action from the pill: re-arms auto-scroll and
  // animates down immediately.
  function scrollToBottom() {
    userScrolledUp.current = false;
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  function handleSend() {
    const content = draft.trim();
    if (!content) return;
    addUserMessage(content);
    setAgentRunning(true);
    socketRef.current?.sendUserMessage(content);
    setDraft("");
  }

  function handleStop() {
    socketRef.current?.sendStop();
  }

  // Forwards the user's approve/modify decision on the WS socket (see
  // ChatSocket.sendPlanDecision) and immediately clears the awaiting-decision
  // flag locally so the PlanApprovalCard disappears without waiting on a
  // round-trip from the server.
  function handlePlanDecision(decision: "approve" | "modify", feedback: string | null) {
    socketRef.current?.sendPlanDecision(decision, feedback);
    resolvePlan();
  }

  // The composer is disabled while a plan decision is pending (the user must
  // resolve the plan card first) or while the socket isn't open (nothing to
  // send to).
  const composerDisabled = planAwaitingDecision || connectionState !== "open";

  return (
    <div className="flex h-full min-h-0 flex-col">
      {phase && phaseLabel && <PhaseBanner phase={phase} label={phaseLabel} progress={progress} />}

      {connectionState === "reconnecting" && (
        <div className="flex items-center justify-center gap-2 bg-warning/10 px-3 py-1.5 text-xs font-medium text-warning">
          <WifiOff className="h-3.5 w-3.5" aria-hidden="true" />
          Reconnecting…
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-full space-y-4 overflow-y-auto px-4 py-4 scrollbar-thin"
        >
          {historyLoading ? (
            <div className="flex h-full items-center justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-label="Loading conversation" />
            </div>
          ) : historyError ? (
            <EmptyState title="Couldn't load this conversation" description={historyError} />
          ) : messages.length === 0 ? (
            <EmptyState
              icon={MessageCircle}
              title="Say hello to get started"
              description="Ask the agent to build a curriculum, or refine one already in progress."
            />
          ) : (
            <AnimatePresence initial={false}>
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
            </AnimatePresence>
          )}

          {plan && planAwaitingDecision && (
            <PlanApprovalCard plan={plan} disabled={false} onDecision={handlePlanDecision} />
          )}

          <div ref={bottomRef} />
        </div>

        <AnimatePresence>
          {showScrollPill && <ScrollToBottomPill onClick={scrollToBottom} />}
        </AnimatePresence>
      </div>

      <Composer
        value={draft}
        onChange={setDraft}
        onSend={handleSend}
        onStop={handleStop}
        disabled={composerDisabled}
        running={agentRunning}
      />
    </div>
  );
}
