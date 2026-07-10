# InterviewCraft — Project Context

Agentic AI platform generating personalized, fully-cited interview-prep curricula.
Monorepo: FastAPI backend (the agentic system) + Next.js 15 frontend + Firestore.

## The one rule that matters

**`docs/specs/` is the binding source of truth.** Spec 01 defines the REST API, the
WebSocket event protocol, the Firestore schema, and env vars; spec 02 defines the agent
system; spec 03 the frontend UX. If you change a contract (API shape, WS event, schema
field), update the spec file AND both sides that consume it. Never let code drift from the
specs silently.

## Layout

- `backend/` — FastAPI, Python 3.13, venv at `backend/.venv`. See `backend/CLAUDE.md`.
  - `app/agent/` — THE CORE: ReAct orchestrator, tools, layered memory + auto-compaction,
    and `prompts/*.md` (11 instruction files — treat these as code; they define agent behavior).
  - Run: `source .venv/bin/activate && uvicorn app.main:app --reload --port 8000`
  - Test: `python -m pytest` (mocked Firestore/LLM; no credentials needed)
- `frontend/` — Next.js 15 App Router, TS strict, Tailwind v4. See `frontend/CLAUDE.md`.
  - Run: `npm run dev`. Verify: `npm run build` must pass with zero type errors.
- `deploy/` — Cloud Run deploy script + Cloud Build config. Keep it simple (user requirement).
- `docs/guides/` — human documentation; keep in sync when behavior changes.

## Key architectural decisions (don't re-litigate casually)

- Frontend NEVER touches Firestore or holds API keys — all data flows through the backend
  (firebase-admin). Ownership check (`owner_uid == current user`) on every doc access.
- Auth: Google Identity Services ID token → verified server-side (google-auth) → backend's
  own JWT in httpOnly SameSite=Lax cookie `ic_session`. Mutating routes require
  `X-Requested-With: XMLHttpRequest`.
- Agent streaming surfaces provider-native reasoning (OpenAI-compatible `reasoning_content`
  stream field; Gemini thought-summary parts via `include_thoughts`); the WS layer emits
  `reasoning_delta` vs `text_delta`.
- HITL: `propose_task_plan` and `request_user_input` tools PAUSE the ReAct loop (state
  persisted to `curricula/{id}/state/main`); loop resumes on the next client WS frame.
  Runs are resumable/cancellable; one active run per conversation (asyncio lock).
- Memory layers: static prompts → synthesized user profile → working state doc →
  saved research sources (agent-written ≤5-sentence summaries from save_sources, grouped
  by search query — full page content stays on the source doc; the agent re-fetches a
  saved URL via fetch_url, and duplicate fetches of a URL are stripped from the
  conversation keeping only the latest — likewise, duplicate reads/writes of a curriculum
  section's content are stripped keeping only the latest) → conversation (with rolling
  compaction summary at 0.8× CONTEXT_TOKEN_LIMIT via the small model).
- Providers are swappable via env/user settings: LLM_PROVIDER (openai | gemini — the
  openai provider serves any OpenAI-compatible endpoint via OPENAI_BASE_URL),
  SEARCH_PROVIDER (duckduckgo | google | tavily). DuckDuckGo uses the `ddgs` package (keyless).
- Citations are non-negotiable: web_search (snippet triage) → fetch_url (full page as
  Markdown, mandatory read) → save_sources pins URL + agent summary into working memory →
  sections cite `[^n]` footnotes mirrored in a `citations` array. No fabricated sources.

## Working on this repo

- User (Jiancheng) runs locally for now; production target is GCP Cloud Run — keep both
  paths working (Firestore emulator support matters).
- User is a visual learner and cares about UI polish: dark/light themes, Framer Motion,
  Mermaid diagrams, n8n-style React Flow canvas. Don't strip visual richness to simplify.
- Prompt files in `backend/app/agent/prompts/` are a primary deliverable — thorough,
  multi-file, carefully engineered. Edit them with the same care as code.

## Code Documentation

**Always add inline comments to every piece of code you add or edit.** This is
a strict requirement — not optional. Keep inline comments concise; do not write bloated inline comments.

### Editing existing code

When you edit existing code that lacks comments, **add comments to every part you touch**
and to any closely related code in the same scope. Do not leave uncommented code
adjacent to newly commented code.
