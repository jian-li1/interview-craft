"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { Loader2, MessageCircle, WifiOff } from "lucide-react";
import { MessageBubble } from "@/components/studio/chat/MessageBubble";
import { CompactionChip } from "@/components/studio/chat/CompactionChip";
import { PhaseBanner } from "@/components/studio/chat/PhaseBanner";
import { PlanApprovalCard } from "@/components/studio/chat/PlanApprovalCard";
import { QuestionCard } from "@/components/studio/chat/QuestionCard";
import { Composer } from "@/components/studio/chat/Composer";
import { ScrollToBottomPill } from "@/components/studio/chat/ScrollToBottomPill";
import { EmptyState } from "@/components/ui/EmptyState";
import { useChatStore, type CompactionItem } from "@/stores/useChatStore";
import { useCurriculumStore } from "@/stores/useCurriculumStore";
import { flattenCurriculum, resolveActiveIndex } from "@/lib/reader";
import type { ChatSocket } from "@/lib/ws";

// Phases at which the reader-section chip may appear — before "writing" there's nothing
// written yet to attach as context (mirrors the backend's own guard in orchestrator.py).
const SECTION_CONTEXT_PHASES = new Set(["writing", "review", "ready", "refinement"]);

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
 *    (the native reasoning stream) and `ToolCallGroup`/`ToolCallCard`.
 *  - `PlanApprovalCard` — rendered inline in the transcript when a HITL plan
 *    is awaiting approve/modify.
 *  - `QuestionCard` — rendered inline in the transcript when a
 *    `request_user_input` HITL gate is awaiting an answer.
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
  const pendingQuestion = useChatStore((s) => s.pendingQuestion);
  const agentRunning = useChatStore((s) => s.agentRunning);
  const connectionState = useChatStore((s) => s.connectionState);
  const addUserMessage = useChatStore((s) => s.addUserMessage);
  const markRunStart = useChatStore((s) => s.markRunStart);
  const resolvePlan = useChatStore((s) => s.resolvePlan);
  const resolveQuestion = useChatStore((s) => s.resolveQuestion);
  const setAgentRunning = useChatStore((s) => s.setAgentRunning);
  const compactions = useChatStore((s) => s.compactions);
  const contextUsage = useChatStore((s) => s.contextUsage);
  const availableModels = useChatStore((s) => s.availableModels);
  const selectedModel = useChatStore((s) => s.selectedModel);
  const setSelectedModel = useChatStore((s) => s.setSelectedModel);
  const searchProviders = useChatStore((s) => s.searchProviders);
  const selectedSearchProvider = useChatStore((s) => s.selectedSearchProvider);
  const setSelectedSearchProvider = useChatStore((s) => s.setSelectedSearchProvider);
  // Derived: true whenever any compaction chip is still in the "running" state — drives
  // the composer's "Compacting…" button label.
  const compacting = compactions.some((c) => c.status === "running");

  // Curriculum panel state, read here (not passed as props) so the section-context chip
  // can be derived independently of whatever prop-drilling CurriculumPanel already does.
  const curriculum = useCurriculumStore((s) => s.curriculum);
  const curriculumView = useCurriculumStore((s) => s.view);
  const activeSelection = useCurriculumStore((s) => s.activeSelection);

  // The composer's "current section" chip target: the Reader's active (module, section)
  // pair, but only once it's actually written content the agent could usefully re-read —
  // null hides the chip entirely (see Composer's `sectionContext !== null` render guard).
  const sectionContext = useMemo(() => {
    if (!phase || !SECTION_CONTEXT_PHASES.has(phase)) return null;
    if (curriculumView !== "reader" || !curriculum) return null;
    const flat = flattenCurriculum(curriculum);
    const idx = resolveActiveIndex(flat, activeSelection);
    const entry = flat[idx];
    if (!entry || !entry.section || entry.section.status === "planned") return null;
    return {
      moduleId: entry.module.id,
      sectionId: entry.section.id,
      // order fields are 0-based in Firestore; display 1-based, matching Reader/TOC labels.
      label: `${entry.module.order + 1}.${entry.section.order + 1} ${entry.section.title}`,
    };
  }, [phase, curriculumView, curriculum, activeSelection]);

  // Sticky for the session (not per-section, never auto-reset) — defaults to included.
  const [sectionContextOn, setSectionContextOn] = useState(true);

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
  // Also depends on `compactions`: the inline CompactionChip lives in a
  // separate store slice from `messages`, so its start/finish transitions
  // grow the transcript's height too and must re-trigger the same scroll.
  useEffect(() => {
    if (!userScrolledUp.current) {
      // Instant (not smooth) scroll: a smooth scroll restarted on every
      // streaming delta emits intermediate scroll events mid-animation, which
      // handleScroll reads as "not at bottom" and spuriously sets
      // userScrolledUp — disabling auto-scroll and popping the pill.
      bottomRef.current?.scrollIntoView({ block: "end" });
      setShowScrollPill(false);
    } else {
      setShowScrollPill(true);
    }
  }, [messages, compactions]);

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
    // Optimistic bubble chip mirrors what's actually being sent (chip visible + toggled on).
    addUserMessage(content, sectionContext && sectionContextOn ? { label: sectionContext.label } : undefined);
    setAgentRunning(true);
    // Forward the composer chips' current selections (omitted when null so the
    // backend falls through to the conversation's persisted selection / default).
    // section_context is only attached when the chip is visible AND toggled on — the
    // backend silently ignores it for plan-decision/HITL-answer resumptions, since
    // those go through separate socket calls that never pass it (see handlePlanDecision/
    // handleQuestionAnswer below).
    socketRef.current?.sendUserMessage(
      content,
      selectedModel ?? undefined,
      selectedSearchProvider ?? undefined,
      sectionContext && sectionContextOn
        ? { module_id: sectionContext.moduleId, section_id: sectionContext.sectionId }
        : undefined
    );
    setDraft("");
  }

  function handleStop() {
    socketRef.current?.sendStop();
  }

  // Manual "Compact now" request from the composer's context-usage warning card.
  function handleCompact() {
    socketRef.current?.sendCompact(selectedModel ?? undefined, selectedSearchProvider ?? undefined);
  }

  // Forwards the user's approve/modify decision on the WS socket (see
  // ChatSocket.sendPlanDecision) and immediately clears the awaiting-decision
  // flag locally so the PlanApprovalCard disappears without waiting on a
  // round-trip from the server.
  function handlePlanDecision(decision: "approve" | "modify", feedback: string | null) {
    socketRef.current?.sendPlanDecision(decision, feedback, selectedModel ?? undefined, selectedSearchProvider ?? undefined);
    resolvePlan();
    // A plan decision starts a new run but adds no local user message, so
    // addUserMessage's timestamping never fires here — mark run start explicitly.
    markRunStart();
  }

  // Answers a pending request_user_input question via the exact same path as a
  // normal composer message — there is no dedicated "answer" WS frame type, the
  // orchestrator just treats the next user_message as the reply (see backend
  // app/agent/CLAUDE.md "HITL gate mechanics"). Clears the card immediately
  // rather than waiting on a round-trip, mirroring handlePlanDecision.
  function handleQuestionAnswer(text: string) {
    addUserMessage(text);
    setAgentRunning(true);
    socketRef.current?.sendUserMessage(text, selectedModel ?? undefined, selectedSearchProvider ?? undefined);
    resolveQuestion();
  }

  // The composer is disabled while a compaction is in flight (sending mid-fold would
  // race the summary checkpoint), while a plan decision or a clarifying question is
  // pending (the user must resolve the inline card first), or while the socket
  // isn't open (nothing to send to).
  const composerDisabled =
    compacting || planAwaitingDecision || pendingQuestion !== null || connectionState !== "open";

  // Name the actual blocker in the disabled composer's placeholder — checked in the
  // same precedence order as composerDisabled's clauses above.
  const composerDisabledPlaceholder = compacting
    ? "Auto-compacting conversation…"
    : planAwaitingDecision
      ? "Waiting on plan approval…"
      : pendingQuestion !== null
        ? "Answer the question above…"
        : "Connecting…";

  // Groups compaction chips by which message they render after, so they can be
  // interleaved into the transcript below. A chip's afterMessageId anchors it to a
  // specific message id UNLESS that id isn't (or isn't yet) present in `messages` —
  // e.g. a reconnect-replayed chip anchored to a message from before hydrateHistory
  // loaded — in which case it falls back to the "before the first message" bucket
  // (keyed by null) rather than silently disappearing.
  // Id of the newest assistant message — the live-timer target while a run is in flight.
  const lastAssistantId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return messages[i].id;
    }
    return null;
  }, [messages]);

  const messageIds = useMemo(() => new Set(messages.map((m) => m.id)), [messages]);
  const chipsByAnchor = useMemo(() => {
    const map = new Map<string | null, CompactionItem[]>();
    for (const c of compactions) {
      const key = c.afterMessageId !== null && messageIds.has(c.afterMessageId) ? c.afterMessageId : null;
      map.set(key, [...(map.get(key) ?? []), c]);
    }
    return map;
  }, [compactions, messageIds]);

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
              {/* Chips anchored before the first message (null anchor, or a stale/
                  not-yet-hydrated anchor id) render first. */}
              {(chipsByAnchor.get(null) ?? []).map((c) => (
                <CompactionChip key={c.id} item={c} />
              ))}
              {messages.map((m) => (
                <Fragment key={m.id}>
                  {/* isRunTail: newest assistant message of an in-flight run -> live ticking timer */}
                  <MessageBubble message={m} isRunTail={agentRunning && m.id === lastAssistantId} />
                  {(chipsByAnchor.get(m.id) ?? []).map((c) => (
                    <CompactionChip key={c.id} item={c} />
                  ))}
                </Fragment>
              ))}
            </AnimatePresence>
          )}

          {plan && planAwaitingDecision && (
            <PlanApprovalCard plan={plan} disabled={false} onDecision={handlePlanDecision} />
          )}

          {/* Only shown when no plan card is up — the two HITL gates never overlap
              (propose_task_plan and request_user_input can't both be pending at once). */}
          {!planAwaitingDecision && pendingQuestion && (
            <QuestionCard
              question={pendingQuestion.question}
              options={pendingQuestion.options}
              disabled={false}
              onAnswer={handleQuestionAnswer}
            />
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
        // Cause-specific placeholder (compacting/plan/question/connecting) — without
        // this prop Composer silently falls back to a generic "Waiting…".
        disabledPlaceholder={composerDisabledPlaceholder}
        running={agentRunning}
        contextUsage={contextUsage}
        onCompact={handleCompact}
        compacting={compacting}
        availableModels={availableModels}
        selectedModel={selectedModel}
        onModelChange={setSelectedModel}
        searchProviders={searchProviders}
        selectedSearchProvider={selectedSearchProvider}
        onSearchProviderChange={setSelectedSearchProvider}
        sectionContext={sectionContext}
        sectionContextOn={sectionContextOn}
        onToggleSectionContext={() => setSectionContextOn((on) => !on)}
      />
    </div>
  );
}
