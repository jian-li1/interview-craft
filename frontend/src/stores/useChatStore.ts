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
  /** Most-recent-first feed of tool-call activity, capped at 30 entries — see `startToolCall`/`pushActivity` for why. */
  activity: ActivityItem[];
  connectionState: "idle" | "connecting" | "open" | "reconnecting" | "closed";

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
  /** Marks a message's streaming flags false (both reasoning and content) and clears `agentRunning` — called on the `message_end` WS event. */
  endMessage: (id: string) => void;
  /** Optimistically appends a locally-authored user message (synthetic id/timestamp) before the server round-trip confirms it. */
  addUserMessage: (content: string) => void;

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
  activity: [],
  connectionState: "idle",

  setConversationId: (id) => set({ conversationId: id }),
  setCurriculumId: (id) => set({ curriculumId: id }),

  // Hydrate full history from persisted messages; also rebuilds activity feed so
  // the Live Activity panel isn't empty after a refresh.
  hydrateHistory: (messages) =>
    set(() => {
      // System-role messages are internal bookkeeping (auto-continue nudges,
      // plan-approval records) and must never be rendered in the chat UI.
      const chatMessages = messages
        .filter(
          (m): m is MessageOut & { role: Exclude<MessageRole, "system"> } =>
            m.role !== "system"
        )
        .map(toChatMessage)
        .sort((a, b) => a.seq - b.seq);

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
      activity: [],
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
    })),

  startMessage: (id) =>
    set((s) => {
      if (s.messages.some((m) => m.id === id)) return s;
      return {
        messages: [...s.messages, stubAssistantMessage(id, s.messages.length)],
        agentRunning: true,
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
      };
    }),

  endMessage: (id) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id
          ? { ...m, contentStreaming: false, reasoningStreaming: false }
          : m
      ),
      agentRunning: false,
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
  setAgentRunning: (running) => set({ agentRunning: running }),
  setConnectionState: (connectionState) => set({ connectionState }),
  pushActivity: (item) =>
    // Same cap/ordering rationale as in `startToolCall` above.
    set((s) => ({ activity: [item, ...s.activity].slice(0, 30) })),
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
