# InterviewCraft

**AI-powered agentic platform that generates comprehensive, personalized, fully-cited
interview-preparation curricula from a single prompt.**

Tell InterviewCraft what interview you're preparing for — "Google SWE system design",
"consulting case interviews at McKinsey", "ICU nursing interviews" — and an agentic AI
system deep-researches the web, proposes a curriculum plan for your approval, then writes a
complete beginner-to-ready curriculum: structured modules and sections with rich Markdown,
colorful Mermaid diagrams, realistic sample interview questions with model answers
personalized to *your* background, and citations for every claim.

## Highlights

- **Agentic ReAct core** — a Planning & Reasoning loop with real tools (web search, page
  fetching, source saving, curriculum writing) and a phase state machine:
  *research → plan → human approval → write → review → refine*.
- **Human-in-the-loop** — the agent pauses with a proposed outline + task plan; you approve
  or request changes before anything is written. Clarifying questions pause the loop too.
- **Deep research with citations** — the agent triages search results, reads full pages
  as Markdown, and pins its own summaries of the kept sources into working memory;
  every curriculum section carries `[^n]` footnotes linked to real sources.
- **Personalization memory** — onboarding (bio, background, target roles, resume upload)
  is synthesized by AI into a durable user profile the agent consults on every run.
- **Sophisticated context management** — layered memory (system / user profile / working
  state / saved sources / conversation) with automatic conversation compaction before the
  LLM context window fills up.
- **Transparent streaming UI** — Claude/ChatGPT-style chat with token streaming over
  WebSockets, visible reasoning chains, and expandable tool-call cards (inputs + outputs).
- **Visual curriculum** — n8n-style workflow canvas of modules (React Flow) plus a Reader
  view with rendered Markdown, Mermaid diagrams, and source cards. Light/dark themes,
  smooth animations.
- **Pluggable providers** — LLM: OpenAI / Google Gemini / llama.cpp (OpenAI-compatible,
  local). Search: DuckDuckGo (free, keyless) / Google Custom Search / Tavily.

## Architecture

```
┌────────────────────┐   REST (JSON, cookie auth)   ┌─────────────────────────────┐
│  Next.js frontend  │ ───────────────────────────► │       FastAPI backend       │
│  (App Router, TW)  │ ◄─────────────────────────── │                             │
│                    │   WebSocket /ws/chat/{id}    │  ┌───────────────────────┐  │
│  • Landing/Login   │   (streamed agent events)    │  │   Agent Orchestrator  │  │
│  • Onboarding      │                              │  │   ReAct loop + phases │  │
│  • Dashboard       │                              │  │   Tools · Memory ·    │  │
│  • Studio          │                              │  │   Prompts · HITL      │  │
│    (chat+canvas)   │                              │  └──────────┬────────────┘  │
└────────────────────┘                              │      ┌──────┴───────┐       │
        Google Sign-In → ID token → session JWT     │   LLM providers  Search     │
                                                    │  (OpenAI/Gemini/ (DDG/CSE/  │
                                                    │   llama.cpp)      Tavily)   │
                                                    └───────────┬─────────────────┘
                                                                ▼
                                                       Firestore (users, profiles,
                                                       curricula, modules/sections,
                                                       saved sources, conversations,
                                                       agent state)
```

## Project structure

```
├── backend/            FastAPI server — the agentic system lives here
│   └── app/
│       ├── agent/      Orchestrator (ReAct loop), tools/, memory/, prompts/*.md
│       ├── api/        REST routers (auth, onboarding, curricula, conversations, settings)
│       ├── ws/         WebSocket chat endpoint + event protocol
│       ├── services/   Firestore repos, LLM providers, search providers
│       ├── core/       Config, security (JWT), dependencies
│       └── models/     Pydantic schemas
├── frontend/           Next.js 15 app (Tailwind v4, Zustand, React Flow, Mermaid)
├── docs/
│   ├── specs/          Binding system contracts (API, WS protocol, DB schema, agent spec)
│   └── guides/         Human documentation — full walkthroughs of every part
├── deploy/             GCP Cloud Run deployment (one script + Cloud Build config)
└── docker-compose.yml  Local stack incl. Firestore emulator
```

## Quick start (local)

Prereqs: Python 3.12+, Node 20+, a Google OAuth client ID, an OpenAI API key
(or a running llama.cpp server). Full step-by-step guide: [docs/guides/setup-local.md](docs/guides/setup-local.md).

```bash
# 1. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in GOOGLE_OAUTH_CLIENT_ID, SESSION_JWT_SECRET, OPENAI_API_KEY,
                              # and either Firebase credentials or FIRESTORE_EMULATOR_HOST
uvicorn app.main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
cp .env.example .env.local    # set NEXT_PUBLIC_GOOGLE_CLIENT_ID
npm run dev                   # http://localhost:3000
```

Or run everything (including a Firestore emulator) with Docker:

```bash
docker compose up --build
```

## Cloud services you need

| Service | Used for | Free tier? |
|---|---|---|
| Google OAuth 2.0 client | Sign-in | Yes |
| Firebase / Firestore | All data | Yes (or local emulator, no account) |
| OpenAI API | Agent LLM | No (or llama.cpp locally, free) |
| DuckDuckGo search | Web research | Yes, keyless (Gemini/Tavily/Google CSE optional) |

Setup instructions for each: [docs/guides/setup-cloud-services.md](docs/guides/setup-cloud-services.md).

## Deployment (GCP)

Two Cloud Run services + Firestore. One-time setup then a single script:

```bash
export NEXT_PUBLIC_GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
./deploy/deploy.sh YOUR_PROJECT_ID us-central1
```

See [deploy/README.md](deploy/README.md).

## Documentation map

- [docs/specs/](docs/specs/) — system contracts: architecture, API + WS protocol,
  Firestore schema, and the full agent-system specification.
- [docs/guides/](docs/guides/) — human walkthroughs: local setup, cloud-service setup,
  backend deep-dive, agent-system deep-dive, frontend deep-dive, deployment.
- `CLAUDE.md` files — root + per-directory context for AI-assisted development sessions.

## Security notes

Google ID tokens are verified server-side; sessions are httpOnly SameSite cookies; the
frontend never holds API keys or talks to Firestore; every document access is
ownership-checked; resume uploads are size/type-limited and parsed in memory; `fetch_url`
has SSRF guards. Details in [docs/guides/backend.md](docs/guides/backend.md).
