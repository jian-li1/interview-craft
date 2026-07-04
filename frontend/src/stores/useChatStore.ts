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

/**
 * One entry in the live "what is the agent doing" activity feed, derived
 * from tool-call start/result WS events. Distinct from `ToolCallRecord`
 * (which lives per-message) — this is a flattened, most-recent-first stream
 * across the whole conversation, capped for bounded memory (see `activity`).
 */
export interface ActivityItem {
  id: string;
  label: string;
  detail: string;
  status: ToolCallStatus;
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
  /** Fills in the result (output preview, status, elapsed time) for a previously-started tool call, on both the message's `tool_calls` and the `activity` feed. */
  resolveToolCall: (
    messageId: string,
    toolCallId: string,
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

export const useChatStore = create<ChatState>((set, get) => ({
  conversationId: null,
  curriculumId: null,
  messages: [],
  phase: null,
  phaseLabel: null,
  progress: null,
  plan: null,
  planAwaitingDecision: false,
  agentRunning: false,
  activity: [],
  connectionState: "idle",

  setConversationId: (id) => set({ conversationId: id }),
  setCurriculumId: (id) => set({ curriculumId: id }),

  // Replaces the full message list with persisted history from
  // `conversationsApi.messages`, e.g. on initial load of an existing
  // conversation (as opposed to messages arriving live over the WebSocket).
  hydrateHistory: (messages) =>
    set({
      // System-role messages are internal bookkeeping (auto-continue nudges,
      // plan-approval records) and must never be rendered in the chat UI.
      messages: messages
        .filter(
          (m): m is MessageOut & { role: Exclude<MessageRole, "system"> } =>
            m.role !== "system"
        )
        .map(toChatMessage)
        .sort((a, b) => a.seq - b.seq),
    }),

  reset: () =>
    set({
      messages: [],
      phase: null,
      phaseLabel: null,
      progress: null,
      plan: null,
      planAwaitingDecision: false,
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
        messages: [
          ...s.messages,
          {
            id,
            role: "assistant",
            content: "",
            reasoning: null,
            reasoningStreaming: false,
            contentStreaming: true,
            tool_calls: [],
            created_at: new Date().toISOString(),
            seq: s.messages.length,
          },
        ],
        agentRunning: true,
      };
    }),

  appendReasoningDelta: (id, delta) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id
          ? { ...m, reasoning: (m.reasoning ?? "") + delta, reasoningStreaming: true }
          : m
      ),
    })),

  appendTextDelta: (id, delta) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id
          ? { ...m, content: m.content + delta, contentStreaming: true }
          : m
      ),
    })),

  endMessage: (id) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id
          ? { ...m, contentStreaming: false, reasoningStreaming: false }
          : m
      ),
      agentRunning: false,
    })),

  startToolCall: (messageId, toolCallId, name, input) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId
          ? {
              ...m,
              tool_calls: [
                ...m.tool_calls,
                { id: toolCallId, name, input, output_preview: "", status: "running" },
              ],
            }
          : m
      ),
      // Prepend so the feed reads newest-first, and cap at 30 entries so a
      // long-running agent session (potentially hundreds of tool calls)
      // doesn't grow this array — and the DOM list rendering it — unbounded.
      activity: [
        {
          id: toolCallId,
          label: name,
          detail: summarizeInput(input),
          status: "running",
          timestamp: Date.now(),
        } satisfies ActivityItem,
        ...s.activity,
      ].slice(0, 30),
    })),

  resolveToolCall: (messageId, toolCallId, outputPreview, status, elapsedMs) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId
          ? {
              ...m,
              tool_calls: m.tool_calls.map((tc) =>
                tc.id === toolCallId
                  ? { ...tc, output_preview: outputPreview, status, elapsed_ms: elapsedMs }
                  : tc
              ),
            }
          : m
      ),
      activity: s.activity.map((a) =>
        a.id === toolCallId ? { ...a, status, detail: outputPreview } : a
      ),
    })),

  setPhase: (phase, label) => set({ phase, phaseLabel: label }),
  setProgress: (completed, total, detail) => set({ progress: { completed, total, detail } }),
  proposePlan: (plan) => set({ plan, planAwaitingDecision: true }),
  resolvePlan: () => set({ planAwaitingDecision: false }),
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
