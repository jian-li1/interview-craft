import { create } from "zustand";
import type {
  MessageOut,
  MessageRole,
  PlanTask,
  ToolCallRecord,
  ToolCallStatus,
} from "@/lib/types";

/**
 * Concern boundary: ONE ACTIVE CONVERSATION.
 *
 * A `ChatMessage` is the UI-side representation of a message in the current
 * chat thread — either a persisted `MessageOut` from history (via
 * `hydrateHistory`) or one being streamed live over the WebSocket (via
 * `startMessage`/`appendReasoningDelta`/`appendTextDelta`/`endMessage`).
 * System-role messages are never represented here (see `hydrateHistory`).
 */
export interface ChatMessage {
  id: string;
  role: Exclude<MessageRole, "system">;
  content: string;
  reasoning: string | null;
  /** True while reasoning text is actively streaming in — drives the "shimmer"/cursor UI on the reasoning block; cleared by `endMessage`. */
  reasoningStreaming: boolean;
  /** True while the assistant's visible content is actively streaming in — drives the typing-cursor UI; cleared by `endMessage`. */
  contentStreaming: boolean;
  tool_calls: ToolCallRecord[];
  created_at: string;
  seq: number;
  /** Total wall-clock duration of the agentic run this message concluded — present only on each run's final assistant message. */
  runElapsedMs?: number;
}

/** The task plan currently proposed by the agent, awaiting a user approve/modify decision (HITL flow). */
export interface ProposedPlan {
  outline_markdown: string;
  tasks: PlanTask[];
  version: number;
}

/** A clarifying question posed by the agent's `request_user_input` tool, awaiting an answer (HITL flow). */
export interface PendingQuestion {
  question: string;
  /** Quick-pick choices, or null when only free-text is offered. */
  options: string[] | null;
}

/**
 * One inline compaction chip rendered in the transcript — either "running" (spinner,
 * shown as soon as `compaction_start` arrives) or "done" (resolved with token counts
 * and an expandable full-summary dropdown, from `compaction`). Survives reconnect/reload
 * via the WS snapshot replay (see `finishCompaction`'s dedupe branch below).
 */
export interface CompactionItem {
  id: string;
  status: "running" | "done";
  /** Full rolling summary text (untruncated), shown in the chip's scrollable dropdown. */
  summary: string | null;
  tokensBefore: number | null;
  tokensAfter: number | null;
  /** Id of the message this chip renders after; null renders it before the first message. */
  afterMessageId: string | null;
  /** Id of the last message folded into the summary (from the `compaction` event) — the dedupe key against reconnect-snapshot replays, since a live chip's `afterMessageId` anchor differs from it. */
  compactedThrough: string | null;
}

/**
 * One entry in the live "what is the agent doing" activity feed, derived
 * from tool-call start/result WS events. Distinct from `ToolCallRecord`
 * (which lives per-message) — this is a flattened, most-recent-first stream
 * across the whole conversation, capped for bounded memory (see `activity`).
 *
 * Carries the full tool-call info (not just a label) so `ActivityFeed` can
 * render the same expandable disclosure UI as `ToolCallCard` — raw input,
 * server-truncated output preview, and elapsed time — rather than just a
 * one-line summary.
 */
export interface ActivityItem {
  id: string;
  /** Raw tool name as sent by the backend, e.g. "web_search" — mapped to a friendly label at render time (see ActivityFeed's tool-name map). */
  name: string;
  /** Collapsed subtitle summarizing the call's input (from `summarizeInput`), e.g. a search query or URL. */
  detail: string;
  /** Full tool input, shown in the expandable "Input" panel. */
  input: Record<string, unknown>;
  /** Server-truncated output preview, filled in by `resolveToolCall` once the call finishes; empty while still running. */
  output_preview: string;
  status: ToolCallStatus;
  elapsed_ms?: number;
  timestamp: number;
}

interface ChatState {
  conversationId: string | null;
  curriculumId: string | null;
  messages: ChatMessage[];
  phase: string | null;
  phaseLabel: string | null;
  progress: { completed: number; total: number; detail: string } | null;
  plan: ProposedPlan | null;
  planAwaitingDecision: boolean;
  /** Set while a `request_user_input` HITL gate is awaiting an answer; null otherwise. */
  pendingQuestion: PendingQuestion | null;
  agentRunning: boolean;
  /** Epoch-ms when the in-flight run started (user send / plan decision), null when idle. */
  runStartedAt: number | null;
  /** Most-recent-first feed of tool-call activity, capped at 30 entries — see `startToolCall`/`pushActivity` for why. */
  activity: ActivityItem[];
  connectionState: "idle" | "connecting" | "open" | "reconnecting" | "closed";
  /** Inline compaction chips interleaved into the transcript (see `CompactionItem`). */
  compactions: CompactionItem[];
  /** Latest context-token usage estimate, or null before the first `context_usage` event. */
  contextUsage: { tokens: number; limit: number; threshold: number } | null;

  setConversationId: (id: string | null) => void;
  setCurriculumId: (id: string | null) => void;
  /** Replaces `messages` with persisted history, dropping system-role entries and sorting by `seq`. */
  hydrateHistory: (messages: MessageOut[]) => void;
  /** Clears all per-conversation UI state (messages, plan, progress, activity, etc.) but leaves `conversationId`/`curriculumId`/`connectionState` untouched. */
  reset: () => void;

  /** Appends a new empty assistant `ChatMessage` (content/reasoning-streaming both start true/false per stream) and marks the agent as running. No-ops if a message with this id already exists (guards against duplicate `message_start` events). */
  startMessage: (id: string) => void;
  /** Appends a reasoning-text delta to the message and sets `reasoningStreaming: true`. */
  appendReasoningDelta: (id: string, delta: string) => void;
  /** Appends a visible-content delta to the message and sets `contentStreaming: true`. */
  appendTextDelta: (id: string, delta: string) => void;
  /** Marks a message's streaming flags false (both reasoning and content) — called on the `message_end` WS event. Does NOT clear `agentRunning`: `message_end` fires between ReAct iterations mid-run, so `agent_done` (guaranteed on every terminal path) is the sole authority for that. */
  endMessage: (id: string) => void;
  /** Optimistically appends a locally-authored user message (synthetic id/timestamp) before the server round-trip confirms it. */
  addUserMessage: (content: string) => void;
  /** Marks the start of a new agentic run (idempotent — never overwrites an already-set `runStartedAt`). */
  markRunStart: () => void;
  /** Freezes the elapsed run time onto the run's final assistant message and clears `runStartedAt`. Uses the server-measured `elapsedMs` (from `agent_done`) when given — overwriting any local/legacy value, since the server value is authoritative — else falls back to the local `runStartedAt` diff (matches prior no-arg behavior, e.g. the non-recoverable `error` path). No-op if no run is in flight AND no `elapsedMs` given. */
  finishRunTiming: (elapsedMs?: number) => void;

  /** Appends a new `running` tool call to the target message and pushes a matching entry onto `activity`. */
  startToolCall: (
    messageId: string,
    toolCallId: string,
    name: string,
    input: Record<string, unknown>
  ) => void;
  /** Fills in the result (full output + preview, status, elapsed time) for a previously-started tool call, on both the message's `tool_calls` and the `activity` feed. */
  resolveToolCall: (
    messageId: string,
    toolCallId: string,
    outputFull: string,
    outputPreview: string,
    status: "ok" | "error",
    elapsedMs: number
  ) => void;

  setPhase: (phase: string, label: string) => void;
  setProgress: (completed: number, total: number, detail: string) => void;
  /** Records a newly-proposed plan and flips `planAwaitingDecision` so the UI shows the approval card. */
  proposePlan: (plan: ProposedPlan) => void;
  /** Clears `planAwaitingDecision` once the user has sent an approve/modify decision. */
  resolvePlan: () => void;
  /** Records a newly-asked clarifying question so the UI shows the question card. */
  askQuestion: (question: string, options: string[] | null) => void;
  /** Clears `pendingQuestion` once the user has answered (option click or free text). */
  resolveQuestion: () => void;
  setAgentRunning: (running: boolean) => void;
  setConnectionState: (state: ChatState["connectionState"]) => void;
  /** Directly pushes an activity entry (prepended, capped at 30) without touching any message's tool_calls — used for activity not tied to a specific message. */
  pushActivity: (item: ActivityItem) => void;

  /** Appends a new "running" compaction chip anchored after the latest message. No-op if one is already running (guards duplicate `compaction_start` events). */
  startCompaction: () => void;
  /**
   * Resolves the in-flight "running" chip in place (if any) with the final full
   * summary/token counts, keeping its live anchor but recording `compactedThrough` as
   * the dedupe key. If no running chip exists — this is a WS reconnect snapshot replay —
   * dedupes against any existing "done" chip with the same `compactedThrough` before
   * appending a new resolved chip anchored at that fold point.
   */
  finishCompaction: (
    summary: string,
    tokensBefore: number,
    tokensAfter: number,
    compactedThrough: string | null
  ) => void;
  /** Records the latest context-token usage estimate for the composer's warning card. */
  setContextUsage: (tokens: number, limit: number, threshold: number) => void;
}

/** Converts a persisted `MessageOut` (non-system role) into the UI-side `ChatMessage` shape, with both streaming flags initialized to false since history is never "in flight". */
function toChatMessage(m: MessageOut & { role: Exclude<MessageRole, "system"> }): ChatMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    reasoning: m.reasoning,
    reasoningStreaming: false,
    contentStreaming: false,
    tool_calls: m.tool_calls,
    created_at: m.created_at,
    seq: m.seq,
    // Persisted server measurement, when present (new runs); undefined on pre-feature
    // history, where hydrateHistory's timestamp-derivation fallback fills the gap.
    runElapsedMs: m.run_elapsed_ms ?? undefined,
  };
}

/**
 * Builds a brand-new, empty streaming assistant `ChatMessage` for the given id — the
 * same shape `startMessage` normally creates on `message_start`. Factored out so
 * `startToolCall`/`appendReasoningDelta`/`appendTextDelta` can all synthesize this stub
 * on demand (see their doc comments) when a WS event arrives for a message id the store
 * doesn't know about yet — which happens after a reconnect, since `message_start` for
 * the in-flight turn was only ever sent to the *previous* socket (see the live-socket
 * registry in `backend/app/ws/chat.py`), never to this one.
 */
function stubAssistantMessage(id: string, seq: number): ChatMessage {
  return {
    id,
    role: "assistant",
    content: "",
    reasoning: null,
    reasoningStreaming: false,
    contentStreaming: true,
    tool_calls: [],
    created_at: new Date().toISOString(),
    seq,
  };
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversationId: null,
  curriculumId: null,
  messages: [],
  phase: null,
  phaseLabel: null,
  progress: null,
  plan: null,
  planAwaitingDecision: false,
  pendingQuestion: null,
  agentRunning: false,
  runStartedAt: null,
  activity: [],
  connectionState: "idle",
  compactions: [],
  contextUsage: null,

  setConversationId: (id) => set({ conversationId: id }),
  setCurriculumId: (id) => set({ curriculumId: id }),

  // Hydrate full history from persisted messages; also rebuilds activity feed so
  // the Live Activity panel isn't empty after a refresh.
  hydrateHistory: (messages) =>
    set(() => {
      // LEGACY FALLBACK ONLY: persisted `run_elapsed_ms` (stamped by the backend on
      // every run since this field was added) is now the preferred source — see
      // toChatMessage — and covers all new runs directly from the message doc. This
      // timestamp-derivation block only fills the gap for conversations from before
      // the field existed, where messages carry no run_elapsed_ms at all. Must run
      // BEFORE filtering out system messages: the user message (or system-role
      // plan-decision record) is persisted at run START, and each assistant message
      // at the END of its ReAct iteration, so a run's final assistant message's
      // created_at ~= run end, and the most recent preceding user/system message's
      // created_at ~= run start.
      const raw = [...messages].sort((a, b) => a.seq - b.seq);
      const elapsedById = new Map<string, number>();
      let runStartMs: number | null = null;
      raw.forEach((m, i) => {
        if (m.role === "user" || m.role === "system") {
          runStartMs = Date.parse(m.created_at);
          return;
        }
        // Assistant message: it's a run's tail if the next raw message starts a
        // new run (user/system) or there is no next message at all.
        const next = raw[i + 1];
        const isRunTail = !next || next.role === "user" || next.role === "system";
        if (isRunTail && runStartMs !== null) {
          const elapsed = Date.parse(m.created_at) - runStartMs;
          if (Number.isFinite(elapsed) && elapsed > 0) {
            elapsedById.set(m.id, elapsed);
          }
        }
      });

      // System-role messages are internal bookkeeping (auto-continue nudges,
      // plan-approval records) and must never be rendered in the chat UI.
      const chatMessages = messages
        .filter(
          (m): m is MessageOut & { role: Exclude<MessageRole, "system"> } =>
            m.role !== "system"
        )
        .map(toChatMessage)
        .sort((a, b) => a.seq - b.seq)
        // Prefer the persisted server value (already set by toChatMessage); only fall
        // back to the derived-from-timestamps estimate for pre-feature history.
        .map((m) => ({ ...m, runElapsedMs: m.runElapsedMs ?? elapsedById.get(m.id) }));

      // Flatten tool_calls into ActivityItems (newest-first, capped at 30).
      const flattened: ActivityItem[] = chatMessages.flatMap((m) =>
        m.tool_calls.map((tc) => ({
          id: tc.id,
          name: tc.name,
          detail: summarizeInput(tc.input),
          input: tc.input,
          output_preview: tc.output_preview,
          // Persisted "running" means turn ended before call resolved; surface as error.
          status: tc.status === "running" ? "error" : tc.status,
          elapsed_ms: tc.elapsed_ms,
          timestamp: Date.parse(m.created_at),
        }))
      );

      return {
        messages: chatMessages,
        activity: flattened.reverse().slice(0, 30),
      };
    }),

  reset: () =>
    set({
      messages: [],
      phase: null,
      phaseLabel: null,
      progress: null,
      plan: null,
      planAwaitingDecision: false,
      pendingQuestion: null,
      agentRunning: false,
      runStartedAt: null,
      activity: [],
      compactions: [],
      contextUsage: null,
    }),

  addUserMessage: (content) =>
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id: `local-${Date.now()}-${Math.random().toString(36).slice(2)}`,
          role: "user",
          content,
          reasoning: null,
          reasoningStreaming: false,
          contentStreaming: false,
          tool_calls: [],
          created_at: new Date().toISOString(),
          seq: s.messages.length,
        },
      ],
      // Send time = run start; covers both composer sends and question-card answers.
      runStartedAt: Date.now(),
    })),

  startMessage: (id) =>
    set((s) => {
      if (s.messages.some((m) => m.id === id)) return s;
      return {
        messages: [...s.messages, stubAssistantMessage(id, s.messages.length)],
        agentRunning: true,
        // Fallback in case the send moment wasn't captured (e.g. plan-decision resume).
        runStartedAt: s.runStartedAt ?? Date.now(),
      };
    }),

  // Reconnect-resilient: synthesize stub message if id is unknown (message_start
  // was only sent to the previous socket).
  appendReasoningDelta: (id, delta) =>
    set((s) => {
      const exists = s.messages.some((m) => m.id === id);
      const base = exists ? s.messages : [...s.messages, stubAssistantMessage(id, s.messages.length)];
      return {
        messages: base.map((m) =>
          m.id === id
            ? { ...m, reasoning: (m.reasoning ?? "") + delta, reasoningStreaming: true }
            : m
        ),
        // Fallback so the timer still runs after a reconnect that skipped message_start.
        runStartedAt: s.runStartedAt ?? Date.now(),
      };
    }),

  // Reconnect-resilient: same rationale as appendReasoningDelta.
  appendTextDelta: (id, delta) =>
    set((s) => {
      const exists = s.messages.some((m) => m.id === id);
      const base = exists ? s.messages : [...s.messages, stubAssistantMessage(id, s.messages.length)];
      return {
        messages: base.map((m) =>
          m.id === id ? { ...m, content: m.content + delta, contentStreaming: true } : m
        ),
        // Fallback so the timer still runs after a reconnect that skipped message_start.
        runStartedAt: s.runStartedAt ?? Date.now(),
      };
    }),

  endMessage: (id) =>
    // `agent_done` is now guaranteed on every terminal path (including errors) and is
    // the sole authority for clearing `agentRunning`; `message_end` fires between
    // ReAct iterations mid-run, so clearing it here made the Stop button and the live
    // run timer flicker between iterations. Only the streaming flags clear here.
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id
          ? { ...m, contentStreaming: false, reasoningStreaming: false }
          : m
      ),
    })),

  // Reconnect-resilient: synthesize stub if messageId is unknown.
  startToolCall: (messageId, toolCallId, name, input) =>
    set((s) => {
      const exists = s.messages.some((m) => m.id === messageId);
      const base = exists
        ? s.messages
        : [...s.messages, stubAssistantMessage(messageId, s.messages.length)];
      return {
        messages: base.map((m) =>
          m.id === messageId
            ? {
                ...m,
                tool_calls: [
                  ...m.tool_calls,
                  { id: toolCallId, name, input, output_full: "", output_preview: "", status: "running" },
                ],
              }
            : m
        ),
        // Prepend (newest-first), capped at 30 to bound memory growth.
        activity: [
          {
            id: toolCallId,
            name,
            detail: summarizeInput(input),
            input,
            output_preview: "",
            status: "running",
            timestamp: Date.now(),
          } satisfies ActivityItem,
          ...s.activity,
        ].slice(0, 30),
        // Fallback so the timer still runs after a reconnect that skipped message_start.
        runStartedAt: s.runStartedAt ?? Date.now(),
      };
    }),

  resolveToolCall: (messageId, toolCallId, outputFull, outputPreview, status, elapsedMs) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId
          ? {
              ...m,
              tool_calls: m.tool_calls.map((tc) =>
                tc.id === toolCallId
                  ? { ...tc, output_full: outputFull, output_preview: outputPreview, status, elapsed_ms: elapsedMs }
                  : tc
              ),
            }
          : m
      ),
      // detail (subtitle) left untouched — only result fields updated, so subtitle
      // keeps showing "what was asked" rather than the output preview.
      activity: s.activity.map((a) =>
        a.id === toolCallId ? { ...a, status, output_preview: outputPreview, elapsed_ms: elapsedMs } : a
      ),
    })),

  setPhase: (phase, label) => set({ phase, phaseLabel: label }),
  setProgress: (completed, total, detail) => set({ progress: { completed, total, detail } }),
  proposePlan: (plan) => set({ plan, planAwaitingDecision: true }),
  resolvePlan: () => set({ planAwaitingDecision: false }),
  askQuestion: (question, options) => set({ pendingQuestion: { question, options } }),
  resolveQuestion: () => set({ pendingQuestion: null }),
  // Idempotent: never overwrites an already-set runStartedAt, so a late fallback
  // call (e.g. from startMessage after a reconnect) never clobbers the true send time.
  markRunStart: () => set((s) => ({ runStartedAt: s.runStartedAt ?? Date.now() })),

  finishRunTiming: (elapsedMs) =>
    set((s) => {
      // Find the last assistant message (the run's tail) from the end — needed by
      // both branches below.
      let lastAssistantIdx = -1;
      for (let i = s.messages.length - 1; i >= 0; i--) {
        if (s.messages[i].role === "assistant") {
          lastAssistantIdx = i;
          break;
        }
      }

      if (elapsedMs !== undefined) {
        // Authoritative server-measured value (from agent_done): stamp it on the tail
        // message, OVERWRITING any locally/legacy-derived value — the server wins.
        // Always clear runStartedAt regardless of whether a tail message was found.
        if (lastAssistantIdx === -1) return { runStartedAt: null };
        const tail = s.messages[lastAssistantIdx];
        // A run that failed before producing any assistant message (e.g. an internal
        // error at run start) must not clobber the PREVIOUS run's stamp: only overwrite
        // an already-stamped tail if it was created during this run (1s slack covers
        // the stub whose created_at lands the same tick as the runStartedAt fallback).
        const belongsToRun =
          s.runStartedAt === null || Date.parse(tail.created_at) >= s.runStartedAt - 1000;
        if (tail.runElapsedMs !== undefined && !belongsToRun) return { runStartedAt: null };
        const messages = [...s.messages];
        messages[lastAssistantIdx] = { ...messages[lastAssistantIdx], runElapsedMs: elapsedMs };
        return { messages, runStartedAt: null };
      }

      // No server value given (e.g. the non-recoverable `error` path): fall back to
      // the local runStartedAt diff, exactly as before this feature.
      if (s.runStartedAt === null) return s;
      const elapsed = Date.now() - s.runStartedAt;
      // Guard: a run that produced no assistant message (or already-stamped tail
      // from a previous run) must not restamp the wrong message.
      if (lastAssistantIdx === -1 || s.messages[lastAssistantIdx].runElapsedMs !== undefined) {
        return { runStartedAt: null };
      }
      const messages = [...s.messages];
      messages[lastAssistantIdx] = { ...messages[lastAssistantIdx], runElapsedMs: elapsed };
      return { messages, runStartedAt: null };
    }),

  setAgentRunning: (running) => set({ agentRunning: running }),
  setConnectionState: (connectionState) => set({ connectionState }),
  pushActivity: (item) =>
    // Same cap/ordering rationale as in `startToolCall` above.
    set((s) => ({ activity: [item, ...s.activity].slice(0, 30) })),

  // No-op if a running chip already exists — guards a duplicate compaction_start
  // (shouldn't happen, but keeps the transcript from ever showing two spinners).
  startCompaction: () =>
    set((s) => {
      if (s.compactions.some((c) => c.status === "running")) return s;
      const lastMessage = s.messages[s.messages.length - 1];
      return {
        compactions: [
          ...s.compactions,
          {
            id: `compaction-${Date.now()}-${Math.random().toString(36).slice(2)}`,
            status: "running",
            summary: null,
            tokensBefore: null,
            tokensAfter: null,
            afterMessageId: lastMessage?.id ?? null,
            // Unknown until the `compaction` event resolves this chip (see finishCompaction).
            compactedThrough: null,
          },
        ],
      };
    }),

  finishCompaction: (summary, tokensBefore, tokensAfter, compactedThrough) =>
    set((s) => {
      const runningIdx = s.compactions.findIndex((c) => c.status === "running");
      if (runningIdx !== -1) {
        // Resolve the in-flight chip in place, keeping its LIVE anchor (the message it
        // was rendered after when compaction started) rather than snapping to
        // compactedThrough — the live anchor is what the user was actually looking at.
        const updated = [...s.compactions];
        updated[runningIdx] = {
          ...updated[runningIdx],
          status: "done",
          summary,
          tokensBefore,
          tokensAfter,
          // Record the fold point so a later reconnect-snapshot replay of this same
          // compaction dedupes against this chip (its render anchor stays the live one).
          compactedThrough,
        };
        return { compactions: updated };
      }
      // No running chip: this is a WS reconnect snapshot replay. Dedupe on the fold
      // point (compactedThrough), NOT the render anchor — a chip resolved live keeps
      // its live anchor, which differs from compactedThrough, so an anchor comparison
      // would duplicate it on every reconnect.
      const alreadyReplayed = s.compactions.some(
        (c) => c.status === "done" && c.compactedThrough === compactedThrough
      );
      if (alreadyReplayed) return s;
      return {
        compactions: [
          ...s.compactions,
          {
            id: `compaction-${Date.now()}-${Math.random().toString(36).slice(2)}`,
            status: "done",
            summary,
            tokensBefore,
            tokensAfter,
            // Replayed chips anchor at the fold point itself — the most meaningful
            // position when the live anchor is unknown (this socket never saw the run).
            afterMessageId: compactedThrough,
            compactedThrough,
          },
        ],
      };
    }),

  setContextUsage: (tokens, limit, threshold) => set({ contextUsage: { tokens, limit, threshold } }),
}));

/**
 * Produces a short human-readable summary of a tool call's input for the
 * activity feed, preferring an obvious "what is this call about" field
 * (`query`/`url`/`q`) over dumping the raw arguments. Falls back to a
 * truncated JSON stringification of the whole input object, or "" if that
 * throws (e.g. circular structures, which shouldn't occur here but this
 * keeps the feed from breaking if one does).
 */
function summarizeInput(input: Record<string, unknown>): string {
  const query = input.query ?? input.url ?? input.q;
  if (typeof query === "string") return query;
  try {
    return JSON.stringify(input).slice(0, 120);
  } catch {
    return "";
  }
}
