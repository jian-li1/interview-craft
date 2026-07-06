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
  llm_provider: string | null;
  search_provider: string | null;
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
  emoji: string | null;
  status: CurriculumStatus;
  overview: string;
  progress: CurriculumProgress;
  conversation_id: string;
  module_count: number;
  section_count: number;
  tags: string[];
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
  summary: string;
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
  created_at: string;
  updated_at: string;
}

export interface ToolCallRecord {
  id: string;
  name: string;
  input: Record<string, unknown>;
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
}

// ---------------------------------------------------------------------------
// REST request/response helper shapes
// ---------------------------------------------------------------------------

export interface CreateConversationRequest {
  curriculum_prompt: string | null;
}

export interface CreateConversationResponse {
  conversation_id: string;
}

export interface OkResponse {
  ok: true;
}

export interface SettingsUpdateRequest {
  theme?: ThemePref;
  llm_provider?: string | null;
  search_provider?: string | null;
}

// ---------------------------------------------------------------------------
// WebSocket protocol — Client -> Server
// ---------------------------------------------------------------------------

/** Discriminated union (on `type`) of every frame the client may send over the chat WebSocket. */
export type ClientEvent =
  | { type: "user_message"; content: string }
  | { type: "plan_decision"; decision: "approve" | "modify"; feedback: string | null }
  | { type: "stop" }
  | { type: "ping" };

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

export interface CompactionEvent {
  type: "compaction";
  summary_preview: string;
  tokens_before: number;
  tokens_after: number;
}

export interface AgentDoneEvent {
  type: "agent_done";
  status: string;
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
  | CurriculumUpdatedEvent
  | CompactionEvent
  | AgentDoneEvent
  | ErrorEvent
  | PongEvent;

// ---------------------------------------------------------------------------
// API error shape
// ---------------------------------------------------------------------------

export interface ApiErrorBody {
  detail?: string | { msg: string; loc?: (string | number)[] }[];
  message?: string;
}
