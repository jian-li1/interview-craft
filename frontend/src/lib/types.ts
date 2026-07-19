/**
 * TypeScript mirrors of every contract shape defined in
 * docs/specs/01-architecture-and-contracts.md. Keep these in exact sync with the backend.
 */

// ---------------------------------------------------------------------------
// Shared / enum-like unions
// ---------------------------------------------------------------------------

export type ThemePref = "system" | "light" | "dark";

export type ExperienceLevel =
  | "student"
  | "entry"
  | "mid"
  | "senior"
  | "career_change";

export type CurriculumStatus =
  | "researching"
  | "planning"
  | "awaiting_approval"
  | "writing"
  | "reviewing"
  | "ready"
  | "error";

export type ModuleStatus = "planned" | "writing" | "complete";
export type SectionStatus = "planned" | "writing" | "complete";
export type PlanStatus = "proposed" | "approved" | "revising";
export type TaskStatus = "pending" | "in_progress" | "done";
export type ToolCallStatus = "ok" | "error" | "running";
export type MessageRole = "user" | "assistant" | "system";

// ---------------------------------------------------------------------------
// Users / auth / settings
// ---------------------------------------------------------------------------

export interface UserSettings {
  theme: ThemePref;
}

/**
 * One selectable model option for the composer's model chip — the union of
 * OPENAI_MODEL/GEMINI_MODEL configured server-side (Gemini entries only present
 * when GEMINI_API_KEY is set). `provider` is shown as a muted badge per option.
 */
export interface ModelOption {
  id: string;
  provider: "openai" | "gemini";
}

export interface UserOut {
  uid: string;
  email: string;
  name: string;
  picture: string | null;
  settings: UserSettings;
  onboarding_completed: boolean;
}

// ---------------------------------------------------------------------------
// Onboarding / profile
// ---------------------------------------------------------------------------

export interface ProfileIn {
  bio: string;
  background: string;
  target_roles: string[];
  experience_level: ExperienceLevel;
  skills: string[];
  goals: string;
  learning_style: string;
  timeline: string;
  onboarding_completed?: boolean;
}

export interface ProfileOut extends ProfileIn {
  resume_filename: string | null;
  resume_text: string | null;
  synthesized_profile: string | null;
  onboarding_completed: boolean;
  updated_at: string;
}

export interface ResumeUploadResponse {
  resume_filename: string;
  resume_text: string;
}

export interface SynthesizeResponse {
  synthesized_profile: string;
}

// ---------------------------------------------------------------------------
// Curricula
// ---------------------------------------------------------------------------

/** Snapshot of agent progress for a curriculum; mirrors the last `progress` WS event received. */
export interface CurriculumProgress {
  phase: string;
  completed_tasks: number;
  total_tasks: number;
  detail: string;
}

export interface CurriculumSummary {
  id: string;
  owner_uid: string;
  title: string;
  user_prompt: string;
  /** Agent-written 1-2 sentence description, set on first plan proposal; "" before that. */
  description: string;
  emoji: string | null;
  status: CurriculumStatus;
  overview: string;
  progress: CurriculumProgress;
  conversation_id: string;
  module_count: number;
  section_count: number;
  tags: string[];
  /** User-set dashboard favorite flag. */
  favorite: boolean;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  id: number;
  url: string;
  title: string;
  accessed_at: string;
}

export interface SectionOut {
  id: string;
  order: number;
  title: string;
  content_markdown: string;
  citations: Citation[];
  status: SectionStatus;
}

export interface ModuleOut {
  id: string;
  order: number;
  title: string;
  /** Agent-written 1-2 sentence description of the module's content. */
  description: string;
  objectives: string[];
  status: ModuleStatus;
  estimated_minutes: number;
  sections: SectionOut[];
}

export interface CurriculumFull extends CurriculumSummary {
  modules: ModuleOut[];
}

export interface PlanTask {
  id: string;
  title: string;
  description: string;
  module_ref: string | null;
  status: TaskStatus;
}

/**
 * The HITL task plan. Lifecycle of `status`: `proposed` (agent paused,
 * awaiting user decision) -> `approved` (user accepted; agent resumes
 * writing) or `revising` (user requested changes; `user_feedback` grows and
 * a new `proposed` version is generated).
 */
export interface PlanOut {
  version: number;
  outline_markdown: string;
  tasks: PlanTask[];
  status: PlanStatus;
  user_feedback: string[];
}

// ---------------------------------------------------------------------------
// Conversations / messages
// ---------------------------------------------------------------------------

export interface ConversationSummary {
  id: string;
  owner_uid: string;
  curriculum_id: string | null;
  title: string;
  summary: string | null;
  compacted_through: string | null;
  token_estimate: number;
  /** Most recent compaction checkpoint (before/after token counts), or null if never compacted. */
  last_compaction: { tokens_before: number; tokens_after: number } | null;
  created_at: string;
  updated_at: string;
}

export interface ToolCallRecord {
  id: string;
  name: string;
  input: Record<string, unknown>;
  /** Complete tool output — same text the model saw. Prefer this for expandable views. */
  output_full: string;
  output_preview: string;
  status: ToolCallStatus;
  /** Present only for tool calls resolved live over WS (not in persisted history). */
  elapsed_ms?: number;
}

export interface MessageOut {
  id: string;
  role: MessageRole;
  content: string;
  reasoning: string | null;
  tool_calls: ToolCallRecord[];
  created_at: string;
  seq: number;
  /** Server-measured duration (ms) of the run this message concluded; only present on
   * run-tail assistant messages, absent on pre-feature history. */
  run_elapsed_ms?: number | null;
  /** Composer's "current section" chip snapshot; present only on user messages sent
   * with the chip on and validated against the curriculum. */
  section_context?: { module_id: string; section_id: string; label: string } | null;
}

// ---------------------------------------------------------------------------
// REST request/response helper shapes
// ---------------------------------------------------------------------------

export interface CreateConversationRequest {
  curriculum_prompt: string | null;
  /** Dashboard prompt box's chip selections (see `modelsApi.get`); omitted/null leaves the doc's fields null. */
  selected_model?: string | null;
  search_provider?: string | null;
}

export interface CreateConversationResponse {
  conversation_id: string;
}

/** Response shape for `GET /api/models` — backs the dashboard prompt box's chips
 * (the studio composer instead hydrates from the WS `session_ready` event). */
export interface ModelOptionsResponse {
  models: ModelOption[];
  default_model: string;
  search_providers: string[];
  default_search_provider: string;
}

export interface OkResponse {
  ok: true;
}

export interface SettingsUpdateRequest {
  theme?: ThemePref;
}

// ---------------------------------------------------------------------------
// WebSocket protocol — Client -> Server
// ---------------------------------------------------------------------------

/**
 * Discriminated union (on `type`) of every frame the client may send over the chat
 * WebSocket. `user_message`/`plan_decision`/`compact` carry optional `model`/
 * `search_provider` — the composer's chip selections, forwarded to the backend for
 * resolution/persistence (see `Orchestrator.run_turn`/`compact_now`). `user_message` also
 * carries an optional `section_context` — the composer's "current section" toggle chip
 * (visible only in the Reader on an already-written section, phase writing-or-later) — so
 * the backend can inject a system note nudging the agent to `read_section` if relevant.
 */
export type ClientEvent =
  | {
      type: "user_message";
      content: string;
      model?: string;
      search_provider?: string;
      section_context?: { module_id: string; section_id: string };
    }
  | {
      type: "plan_decision";
      decision: "approve" | "modify";
      feedback: string | null;
      model?: string;
      search_provider?: string;
    }
  | { type: "stop" }
  | { type: "ping" }
  // Manual "Compact now" request from the composer's context-usage warning card.
  | { type: "compact"; model?: string; search_provider?: string };

// ---------------------------------------------------------------------------
// WebSocket protocol — Server -> Client
// ---------------------------------------------------------------------------

export interface SessionReadyEvent {
  type: "session_ready";
  conversation_id: string;
  curriculum_id: string | null;
  /**
   * True if an agent turn for this conversation is still running (the
   * per-conversation orchestrator lock is held) at the moment this socket
   * connected — lets a freshly (re)connected client immediately show the
   * Stop button / running state instead of waiting for the next streamed
   * event to imply it.
   */
  agent_running: boolean;
  /** Every model the composer's model chip may offer (union of OPENAI_MODEL/GEMINI_MODEL). */
  available_models: ModelOption[];
  /** The conversation's persisted model selection, resolved/validated server-side (never a stale/unavailable id). */
  selected_model: string;
  /** Every search provider name the composer's search chip may offer. */
  search_providers: string[];
  /** The conversation's persisted search provider selection, resolved/validated server-side. */
  search_provider: string;
}

export interface MessageStartEvent {
  type: "message_start";
  message_id: string;
  role: "assistant";
}

export interface ReasoningDeltaEvent {
  type: "reasoning_delta";
  message_id: string;
  delta: string;
}

export interface TextDeltaEvent {
  type: "text_delta";
  message_id: string;
  delta: string;
}

export interface ToolCallStartEvent {
  type: "tool_call_start";
  message_id: string;
  tool_call_id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolCallResultEvent {
  type: "tool_call_result";
  message_id: string;
  tool_call_id: string;
  name: string;
  output_full: string;
  output_preview: string;
  status: "ok" | "error";
  elapsed_ms: number;
}

export interface MessageEndEvent {
  type: "message_end";
  message_id: string;
}

export interface PhaseChangeEvent {
  type: "phase_change";
  phase: string;
  label: string;
}

export interface ProgressEvent {
  type: "progress";
  completed: number;
  total: number;
  detail: string;
}

export interface PlanProposedEvent {
  type: "plan_proposed";
  plan: {
    outline_markdown: string;
    tasks: PlanTask[];
    version: number;
  };
}

/**
 * Signals that `curriculaApi.get` should be refetched. `scope` narrows what
 * changed (whole-curriculum overview vs. a single module vs. a single
 * section vs. curriculum-level metadata like title/emoji); `module_id`/
 * `section_id` are set accordingly so a scoped refetch can target just the
 * changed node if the store supports it.
 */
export interface CurriculumUpdatedEvent {
  type: "curriculum_updated";
  curriculum_id: string;
  // "curriculum" — emitted by set_curriculum_title (title/emoji rename); no module/section id.
  scope: "overview" | "module" | "section" | "curriculum";
  module_id?: string;
  section_id?: string;
}

/**
 * Emitted by the `request_user_input` HITL gate tool (via its `_ws_event`) and
 * replayed in the reconnect snapshot when the agent state doc has a truthy
 * `pending_user_input`. `options` is null/empty when only free-text is offered.
 */
export interface UserInputRequestedEvent {
  type: "user_input_requested";
  question: string;
  options: string[] | null;
}

export interface CompactionEvent {
  type: "compaction";
  /** Full rolling summary text (untruncated) — rendered in the chip's scrollable dropdown. */
  summary: string;
  tokens_before: number;
  tokens_after: number;
  /** Id of the last message folded into the summary — anchors the chip in the transcript. */
  compacted_through: string | null;
}

/** Emitted right before the (potentially slow) small-model summarization call starts. */
export interface CompactionStartEvent {
  type: "compaction_start";
  tokens_before: number;
}

/** Current context-token usage estimate, emitted at the end of every build_context call. */
export interface ContextUsageEvent {
  type: "context_usage";
  tokens: number;
  limit: number;
  /** Fraction of `limit` at which auto-compaction fires (COMPACTION_TRIGGER_FRACTION, 0.8). */
  threshold: number;
}

export interface AgentDoneEvent {
  type: "agent_done";
  status: string;
  /** Authoritative server-measured run duration (ms), for the whole run just ended. */
  elapsed_ms: number;
}

export interface ErrorEvent {
  type: "error";
  message: string;
  recoverable: boolean;
}

export interface PongEvent {
  type: "pong";
}

/**
 * Discriminated union (on `type`) of every frame the server may send over
 * the chat WebSocket. See `frontend/CLAUDE.md` "How WS events map to store
 * actions" for the dispatch table in `useChatSocket.ts`.
 */
export type ServerEvent =
  | SessionReadyEvent
  | MessageStartEvent
  | ReasoningDeltaEvent
  | TextDeltaEvent
  | ToolCallStartEvent
  | ToolCallResultEvent
  | MessageEndEvent
  | PhaseChangeEvent
  | ProgressEvent
  | PlanProposedEvent
  | UserInputRequestedEvent
  | CurriculumUpdatedEvent
  | CompactionEvent
  | CompactionStartEvent
  | ContextUsageEvent
  | AgentDoneEvent
  | ErrorEvent
  | PongEvent;

// ---------------------------------------------------------------------------
// WebSocket protocol — /ws/dashboard (push-based replacement for the
// dashboard's old 8s curriculaApi.list() polling; see spec 01 §7b)
// ---------------------------------------------------------------------------

/** The only client frame `DashboardSocket` sends beyond the inherited keepalive ping. */
export type DashboardClientEvent = { type: "ping" };

/** A curriculum was created or updated; carries the full up-to-date summary to upsert. */
export interface DashboardCurriculumUpdatedEvent {
  type: "curriculum_updated";
  curriculum: CurriculumSummary;
}

/** A curriculum was deleted; the client should remove it from the grid by id. */
export interface DashboardCurriculumDeletedEvent {
  type: "curriculum_deleted";
  curriculum_id: string;
}

/**
 * Discriminated union (on `type`) of every frame the server may send over the dashboard
 * WebSocket. Note `"curriculum_updated"` here is a DIFFERENT shape from the chat WS's
 * `CurriculumUpdatedEvent` above (that one carries a refetch-scope hint; this one
 * carries the full summary directly) — the two protocols are never mixed on the same
 * socket, so the same discriminant string is safe to reuse.
 */
export type DashboardServerEvent =
  | DashboardCurriculumUpdatedEvent
  | DashboardCurriculumDeletedEvent
  | PongEvent;

// ---------------------------------------------------------------------------
// API error shape
// ---------------------------------------------------------------------------

export interface ApiErrorBody {
  detail?: string | { msg: string; loc?: (string | number)[] }[];
  message?: string;
}
