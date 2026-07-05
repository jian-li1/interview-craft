# InterviewCraft — Architecture & System Contracts (Source of Truth)

This document defines the binding contracts between the frontend and backend. Both
implementations MUST conform exactly to the shapes defined here.

## 1. Product summary

InterviewCraft is an agentic AI platform that generates comprehensive, end-to-end,
beginner-friendly interview-preparation curricula from a single user prompt. The agent
performs deep web research, proposes an outline + task plan (human-in-the-loop approval),
then writes the curriculum module-by-module with rich Markdown, Mermaid diagrams,
personalized sample Q&A, and full source citations. Users chat with the agent to refine,
clarify, or explain any part of the curriculum.

## 2. Tech stack

- **Frontend**: Next.js 15 (App Router, TypeScript), Tailwind CSS v4, Zustand,
  react-markdown (+remark-gfm, rehype-highlight), Mermaid, @xyflow/react (React Flow),
  Framer Motion, next-themes, lucide-react.
- **Backend**: FastAPI (Python 3.13), uvicorn, pydantic v2, firebase-admin (Firestore),
  google-auth (OAuth verification), PyJWT, httpx, openai SDK, google-genai SDK,
  ddgs (DuckDuckGo search), pypdf + python-docx (resume parsing), tiktoken (token counting).
- **Auth**: Google Sign-In (Google Identity Services) on the frontend → ID token POSTed to
  backend → verified server-side → backend issues its own session JWT in an httpOnly cookie.
- **DB**: Firestore (via firebase-admin server-side ONLY; frontend never talks to Firestore).
- **Local dev**: docker-compose with a Firestore emulator option; both apps also run bare.
- **Deploy target**: GCP Cloud Run (Dockerfile per app + cloudbuild.yaml in `deploy/`).

## 3. Repository layout

```
interview-craft/
├── README.md, CLAUDE.md, .gitignore, docker-compose.yml, .env.example
├── docs/
│   ├── specs/        # These spec files (contracts)
│   └── guides/       # Human documentation (setup, walkthroughs, deployment)
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app factory, CORS, routers, WS
│   │   ├── core/                 # config.py (pydantic-settings), security.py (JWT), deps.py
│   │   ├── api/                  # REST routers: auth, onboarding, curricula, conversations, settings
│   │   ├── ws/                   # WebSocket chat endpoint + event serialization
│   │   ├── agent/                # THE AGENTIC CORE (see spec 02)
│   │   │   ├── orchestrator.py   # ReAct loop
│   │   │   ├── tools/            # Tool implementations + registry
│   │   │   ├── memory/           # Memory manager, compaction
│   │   │   └── prompts/          # *.md system prompt / instruction files
│   │   ├── services/
│   │   │   ├── firestore.py      # Firestore client + repositories
│   │   │   ├── llm/              # base.py, openai_provider.py, gemini_provider.py, factory.py
│   │   │   └── search/           # base.py, duckduckgo.py, google_cse.py, tavily.py, factory.py
│   │   └── models/               # Pydantic schemas (mirror Firestore + API shapes)
│   ├── tests/
│   ├── requirements.txt, Dockerfile, .env.example
├── frontend/
│   ├── src/app/                  # App Router pages
│   ├── src/components/           # UI components
│   ├── src/lib/                  # api client, ws client, stores, types
│   ├── package.json, Dockerfile, .env.example
└── deploy/                       # cloudbuild-backend.yaml, cloudbuild-frontend.yaml, deploy.sh, README
```

## 4. Environment variables

### Backend (`backend/.env`)
```
APP_ENV=development                  # development | production
PORT=8000
FRONTEND_ORIGIN=http://localhost:3000
SESSION_JWT_SECRET=<random 64 hex>   # REQUIRED
SESSION_JWT_EXPIRES_MIN=10080        # 7 days
GOOGLE_OAUTH_CLIENT_ID=<...>.apps.googleusercontent.com   # REQUIRED

# Firestore: either emulator or service account
FIREBASE_PROJECT_ID=interviewcraft-dev
GOOGLE_APPLICATION_CREDENTIALS=./serviceAccountKey.json   # omit when using emulator
FIRESTORE_EMULATOR_HOST=                                   # e.g. localhost:8686 for emulator

# LLM
LLM_PROVIDER=openai                  # openai | gemini | llamacpp
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
OPENAI_SMALL_MODEL=gpt-4o-mini       # used for compaction/summarization/profile synthesis
OPENAI_BASE_URL=                     # set to e.g. http://localhost:8080/v1 for llama.cpp
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-pro
GEMINI_SMALL_MODEL=gemini-2.5-flash

# Search
SEARCH_PROVIDER=duckduckgo           # duckduckgo | google | tavily
GOOGLE_CSE_API_KEY=
GOOGLE_CSE_ENGINE_ID=
TAVILY_API_KEY=

# Agent behavior
AGENT_MAX_ITERATIONS=60
CONTEXT_TOKEN_LIMIT=100000           # trigger compaction above ~80% of this

# LLM request shape / resilience
LLM_MAX_OUTPUT_TOKENS=8192           # hard cap on generated tokens per call (all providers)
LLM_REQUEST_TIMEOUT_SECONDS=120      # inter-chunk timeout for streaming; also applies to non-streaming calls
```

### Frontend (`frontend/.env.local`)
```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8000
NEXT_PUBLIC_GOOGLE_CLIENT_ID=<same client id>
```

## 5. Firestore schema

All access is server-side via firebase-admin. Every route MUST verify
`owner_uid == current_user.uid` before returning/mutating any document.

```
users/{uid}
  email, name, picture, google_sub, created_at, last_login_at
  settings: { theme: "system"|"light"|"dark", llm_provider: str|null,
              search_provider: str|null }        # null = use server default

users/{uid}/profile/main
  bio: str                      # user-written bio
  background: str               # education/work history free text
  target_roles: [str]
  experience_level: "student"|"entry"|"mid"|"senior"|"career_change"
  skills: [str]
  goals: str
  learning_style: str           # e.g. "visual", free text
  timeline: str                 # e.g. "interview in 3 weeks"
  resume_filename: str|null
  resume_text: str|null         # extracted text
  synthesized_profile: str|null # AI-generated descriptive profile = agent's user memory
  onboarding_completed: bool
  updated_at

curricula/{curriculumId}
  owner_uid, title, user_prompt, emoji: str|null
  status: "researching"|"planning"|"awaiting_approval"|"writing"|"ready"|"error"
  overview: str                 # markdown overview of whole curriculum
  progress: { phase: str, completed_tasks: int, total_tasks: int, detail: str }
  conversation_id: str
  module_count: int, section_count: int, tags: [str]
  created_at, updated_at

curricula/{id}/modules/{moduleId}
  order: int, title, summary, objectives: [str]
  status: "planned"|"writing"|"complete"
  estimated_minutes: int

curricula/{id}/modules/{mid}/sections/{sectionId}
  order: int, title
  content_markdown: str         # rich markdown incl. mermaid blocks, [^n] citation markers
  citations: [{ id: int, url, title, accessed_at }]
  status: "planned"|"writing"|"complete"

curricula/{id}/plan/main
  version: int
  outline_markdown: str         # human-readable outline
  tasks: [{ id: str, title: str, description: str, module_ref: str|null,
            status: "pending"|"in_progress"|"done" }]
  status: "proposed"|"approved"|"revising"
  user_feedback: [str]

curricula/{id}/research/{noteId}
  query: str, url: str, title: str
  summary: str                  # distilled findings
  key_facts: [str]
  relevance: str                # which outline topics this supports
  created_at

curricula/{id}/state/main       # agent working memory (see spec 02)
  phase, task_queue, current_task_id, scratchpad, iteration_count, updated_at

conversations/{convId}
  owner_uid, curriculum_id: str|null, title
  summary: str|null             # rolling compaction summary
  compacted_through: str|null   # last message id folded into summary
  token_estimate: int
  created_at, updated_at

conversations/{convId}/messages/{msgId}
  role: "user"|"assistant"|"system"
  content: str
  reasoning: str|null                       # assistant thinking text
  tool_calls: [{ id, name, input: obj, output_preview: str, status }]
  created_at
  seq: int                                  # monotonic ordering
  # role:"system" — internal agent-control records synthesized by the orchestrator itself
  # (not typed by the user or the LLM), e.g. plan_decision confirmations. They are
  # persisted so they flow through the same context-rebuild path as any other message,
  # but the frontend hides/filters them out of the rendered chat.
```

## 6. REST API (all under `/api`, JSON, session cookie auth)

Auth uses an httpOnly cookie `ic_session` (JWT: {sub: uid, exp}). CORS: allow
FRONTEND_ORIGIN with credentials. All mutating routes require header
`X-Requested-With: XMLHttpRequest` (CSRF mitigation alongside SameSite=Lax).

| Method | Path | Body → Response |
|---|---|---|
| POST | /api/auth/google | `{id_token}` → sets cookie, returns `UserOut` |
| POST | /api/auth/logout | clears cookie → `{ok: true}` |
| GET  | /api/auth/me | → `UserOut` (401 if not logged in) |
| GET  | /api/onboarding | → `ProfileOut` |
| PUT  | /api/onboarding | `ProfileIn` → `ProfileOut` |
| POST | /api/onboarding/resume | multipart file (pdf/docx/txt, ≤5MB) → `{resume_filename, resume_text}` |
| POST | /api/onboarding/synthesize | → `{synthesized_profile}` (runs LLM profile synthesis, saves) |
| GET  | /api/curricula | → `[CurriculumSummary]` |
| GET  | /api/curricula/{id} | → `CurriculumFull` (with modules + sections nested) |
| DELETE | /api/curricula/{id} | → `{ok: true}` — cascades: also deletes the curriculum's linked conversation doc and its `messages` subcollection (a curriculum:conversation is 1:1, so no orphaned conversation is left behind) |
| GET  | /api/curricula/{id}/plan | → plan doc |
| GET  | /api/conversations | → `[ConversationSummary]` |
| POST | /api/conversations | `{curriculum_prompt: str|null}` → `{conversation_id}` (new chat) |
| GET  | /api/conversations/{id}/messages | → `[MessageOut]` (full history for rendering) |
| GET  | /api/settings | → settings obj |
| PUT  | /api/settings | partial settings → settings obj |
| GET  | /api/healthz | → `{status: "ok"}` (no auth) |

`UserOut = {uid, email, name, picture, settings, onboarding_completed}`

## 7. WebSocket chat protocol

Endpoint: `GET /ws/chat/{conversation_id}` — authenticated via the `ic_session` cookie
(browser sends it on same-site WS upgrade in dev via CORS-allowed origin; also accept
`?token=` fallback containing the same JWT). Reject 4401 if invalid, 4403 if not owner.

All frames are JSON: `{ "type": string, ...payload }`.

### Client → Server
```
{type:"user_message", content: str}
{type:"plan_decision", decision:"approve"|"modify", feedback: str|null}
{type:"stop"}                      # cancel of current agent run — see below, takes effect promptly
{type:"ping"}
```

`stop` aborts promptly rather than only at the next iteration boundary: it interrupts
both a pending LLM stream read (the wait on the next streamed chunk, including a long
prefill stall) and any tool call already in flight (e.g. a slow `fetch_url`), not just
the gaps between them. See §7's server-event replay note below for what a client sees
immediately after reconnecting to a still-running turn.

### Server → Client (streaming event stream)
```
{type:"session_ready", conversation_id, curriculum_id, agent_running: bool}
{type:"message_start", message_id, role:"assistant"}
{type:"reasoning_delta", message_id, delta: str}         # thinking-chain text
{type:"text_delta", message_id, delta: str}              # user-facing answer text
{type:"tool_call_start", message_id, tool_call_id, name, input: obj}
{type:"tool_call_result", message_id, tool_call_id, name, output_preview: str,
      status:"ok"|"error", elapsed_ms: int}
{type:"message_end", message_id}
{type:"phase_change", phase, label: str}                 # e.g. "deep_research" → "Researching"
{type:"progress", completed: int, total: int, detail: str}
{type:"plan_proposed", plan: {outline_markdown, tasks:[...], version}}  # HITL gate
{type:"curriculum_updated", curriculum_id, scope:"overview"|"module"|"section"|"curriculum",
      module_id?: str, section_id?: str}                 # frontend refetches affected part
      # scope:"curriculum" — emitted by set_curriculum_title (title/emoji rename); refetch
      # the curriculum summary (dashboard/sidebar title) rather than a specific sub-part.
{type:"compaction", summary_preview: str, tokens_before: int, tokens_after: int}
{type:"agent_done", status}
{type:"error", message: str, recoverable: bool}
{type:"pong"}
```

On connect, immediately after `session_ready` (whose `agent_running` flag reflects
whether the per-conversation orchestrator lock is currently held), the server replays a
state snapshot so a freshly (re)connected client can rebuild its UI without waiting for
new agent activity: a `phase_change` for the current persisted phase (skipped if the
phase is still `"intake"`, i.e. nothing has happened yet), a `progress` event derived
from the plan's task counts (only if a plan exists and has at least one task), and a
`plan_proposed` event replaying the current plan (only if the plan's `status` is still
`"proposed"`, i.e. still awaiting a `plan_decision`) — this restores the HITL approval
card after a page refresh or navigation away and back. Also note that only the most
recently connected socket per conversation ("live-socket registry") receives streamed
events; if a client reconnects while a turn is still running (e.g. the user navigated
away and back), the in-flight run keeps streaming to the new connection rather than the
old, now-dead one.

Frontend behavior: on `plan_proposed`, render an interactive approval card in the chat and
the plan in the right panel; agent run pauses until `plan_decision` arrives (HITL). On
`curriculum_updated`, refetch that scope via REST and animate it into the right panel.

Handling `plan_decision`: in addition to mutating the plan/state/curriculum docs
(materializing module/section stubs on approve, or recording feedback on modify), the
orchestrator appends a synthetic `role:"system"` message to the conversation confirming
the decision (see §5) before resuming the ReAct loop — this lets the model see, on the
very next iteration, that the approval/feedback already happened instead of re-asking the
user to confirm.

## 8. Security requirements

- Verify Google ID tokens server-side with `google.oauth2.id_token.verify_oauth2_token`,
  checking audience == GOOGLE_OAUTH_CLIENT_ID and issuer.
- Session cookie: httpOnly, SameSite=Lax, Secure when APP_ENV=production.
- Never expose Firestore or any API key to the frontend; only NEXT_PUBLIC_* vars there.
- Ownership check on EVERY document access. Pydantic validation on every input.
- Resume upload: enforce content-type + 5MB limit; parse in-memory; never execute/store raw file on disk.
- Basic per-user rate limiting on agent-triggering endpoints (in-memory token bucket is fine).
- Structured logging; never log secrets, tokens, or full resume text.
