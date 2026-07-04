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
  const userScrolledUp = useRef(false);

  useEffect(() => {
    if (prefillText) {
      setDraft((prev) => (prev ? `${prev}\n${prefillText}` : prefillText));
      onPrefillConsumed?.();
    }
  }, [prefillText, onPrefillConsumed]);

  useEffect(() => {
    if (!userScrolledUp.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
      setShowScrollPill(false);
    } else {
      setShowScrollPill(true);
    }
  }, [messages]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    userScrolledUp.current = !atBottom;
    if (atBottom) setShowScrollPill(false);
  }

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

  function handlePlanDecision(decision: "approve" | "modify", feedback: string | null) {
    socketRef.current?.sendPlanDecision(decision, feedback);
    resolvePlan();
  }

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
