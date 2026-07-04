import { create } from "zustand";
import type {
  MessageOut,
  MessageRole,
  PlanTask,
  ToolCallRecord,
  ToolCallStatus,
} from "@/lib/types";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  reasoning: string | null;
  reasoningStreaming: boolean;
  contentStreaming: boolean;
  tool_calls: ToolCallRecord[];
  created_at: string;
  seq: number;
}

export interface ProposedPlan {
  outline_markdown: string;
  tasks: PlanTask[];
  version: number;
}

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
  activity: ActivityItem[];
  connectionState: "idle" | "connecting" | "open" | "reconnecting" | "closed";

  setConversationId: (id: string | null) => void;
  setCurriculumId: (id: string | null) => void;
  hydrateHistory: (messages: MessageOut[]) => void;
  reset: () => void;

  startMessage: (id: string) => void;
  appendReasoningDelta: (id: string, delta: string) => void;
  appendTextDelta: (id: string, delta: string) => void;
  endMessage: (id: string) => void;
  addUserMessage: (content: string) => void;

  startToolCall: (
    messageId: string,
    toolCallId: string,
    name: string,
    input: Record<string, unknown>
  ) => void;
  resolveToolCall: (
    messageId: string,
    toolCallId: string,
    outputPreview: string,
    status: "ok" | "error",
    elapsedMs: number
  ) => void;

  setPhase: (phase: string, label: string) => void;
  setProgress: (completed: number, total: number, detail: string) => void;
  proposePlan: (plan: ProposedPlan) => void;
  resolvePlan: () => void;
  setAgentRunning: (running: boolean) => void;
  setConnectionState: (state: ChatState["connectionState"]) => void;
  pushActivity: (item: ActivityItem) => void;
}

function toChatMessage(m: MessageOut): ChatMessage {
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

  hydrateHistory: (messages) =>
    set({ messages: messages.map(toChatMessage).sort((a, b) => a.seq - b.seq) }),

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
    set((s) => ({ activity: [item, ...s.activity].slice(0, 30) })),
}));

function summarizeInput(input: Record<string, unknown>): string {
  const query = input.query ?? input.url ?? input.q;
  if (typeof query === "string") return query;
  try {
    return JSON.stringify(input).slice(0, 120);
  } catch {
    return "";
  }
}
