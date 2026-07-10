# Local setup

Complete step-by-step instructions for running InterviewCraft locally: bare-metal
(venv + npm) and Docker Compose paths, every environment variable explained, and a
troubleshooting section for the errors you're most likely to hit.

## Prerequisites

- **Python 3.12+** (the venv in this repo, `backend/.venv`, targets **3.13**
  specifically — `backend/Dockerfile` uses `python:3.13-slim`).
- **Node 20+** (matches `frontend/Dockerfile`'s `node:20-slim` base).
- A **Google OAuth 2.0 client ID** — see
  [setup-cloud-services.md](setup-cloud-services.md) §1 for exact console steps
  (**Authorized JavaScript origins**: `http://localhost:3000`).
- Either a **Firebase/Firestore project + service account key**, or the **Firestore
  emulator** (no Google account needed) — §3 below.
- Either an **OpenAI API key** (or Gemini), or a **local OpenAI-compatible model
  server** — §5/§6 below.
- Optional: Docker + Docker Compose, if you'd rather run everything in containers (§7).

## 1. Clone and orient

```bash
cd interview-craft
```

Repo layout you'll be working with: `backend/` (FastAPI), `frontend/` (Next.js),
`docs/` (specs + these guides), `deploy/` (Cloud Run only — not needed locally).

## 2. Google OAuth client

Follow [setup-cloud-services.md](setup-cloud-services.md) §1 exactly. You'll end up
with one Client ID string that goes into **both** `backend/.env`
(`GOOGLE_OAUTH_CLIENT_ID`) and `frontend/.env.local`
(`NEXT_PUBLIC_GOOGLE_CLIENT_ID`) — same value, two places, because the frontend needs
it client-side (to render the Google Sign-In button and obtain an ID token) and the
backend needs it server-side (to verify that ID token's audience claim).

## 3. Firestore: real project or emulator

**Path A — real Firebase project.** Follow
[setup-cloud-services.md](setup-cloud-services.md) §2a/§2b. You'll end up with
`backend/serviceAccountKey.json` and a `FIREBASE_PROJECT_ID`.

**Path B — Firestore emulator (no Google account, fully offline).**

Bare `gcloud` CLI (requires the Google Cloud SDK installed, but no login/project/billing
is needed to *run* the emulator once the SDK is present):

```bash
gcloud components install cloud-firestore-emulator   # one-time
gcloud emulators firestore start --host-port=localhost:8686
```

Leave that running in its own terminal. Then in `backend/.env`:

```
FIREBASE_PROJECT_ID=interviewcraft-dev
GOOGLE_APPLICATION_CREDENTIALS=
FIRESTORE_EMULATOR_HOST=localhost:8686
```

`app/services/firestore.py:get_firestore_client()` detects `FIRESTORE_EMULATOR_HOST`
and skips credential verification entirely — any `FIREBASE_PROJECT_ID` string works
since the emulator doesn't check it against a real project.

Data in the emulator is **in-memory and lost when you stop it** (no `--project` flag
persists anything to disk by default) — fine for local dev/testing, not for anything
you want to keep across restarts. If you want persistence, add
`--host-port=localhost:8686` plus your own export/import flags per the `gcloud
emulators firestore start --help` output.

## 4. Backend: venv + `.env` walkthrough

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate     # zsh/bash; on fish: source .venv/bin/activate.fish
pip install -r requirements.txt
cp .env.example .env
```

Now edit `backend/.env`. Every variable, what it does, and whether it's required:

```
APP_ENV=development                  # development | production. Controls log level (DEBUG vs INFO)
                                      # and whether the session cookie gets Secure=true.
PORT=8000                            # uvicorn listens here; Cloud Run overrides this itself in prod.
FRONTEND_ORIGIN=http://localhost:3000  # CORS allow-origin AND must match where the frontend runs.

SESSION_JWT_SECRET=<random 64 hex>   # REQUIRED, no default. Generate: openssl rand -hex 32
SESSION_JWT_EXPIRES_MIN=10080        # session cookie lifetime in minutes (7 days default).
GOOGLE_OAUTH_CLIENT_ID=<...>.apps.googleusercontent.com   # REQUIRED, no default. From step 2.

# --- Firestore: fill in exactly one of the two paths from step 3 ---
FIREBASE_PROJECT_ID=interviewcraft-dev
GOOGLE_APPLICATION_CREDENTIALS=./serviceAccountKey.json   # path A only; blank for emulator
FIRESTORE_EMULATOR_HOST=                                   # path B only, e.g. localhost:8686

# --- LLM: pick one provider ---
LLM_PROVIDER=openai                  # openai | gemini
OPENAI_API_KEY=sk-...                # required if LLM_PROVIDER=openai
OPENAI_MODEL=gpt-4o                  # main model, used for the ReAct loop
OPENAI_SMALL_MODEL=gpt-4o-mini       # used for compaction, profile synthesis (cheaper/faster)
OPENAI_BASE_URL=                     # set for a local OpenAI-compatible server — see §6 below
GEMINI_API_KEY=                      # required if LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.5-pro
GEMINI_SMALL_MODEL=gemini-2.5-flash

# --- Search: duckduckgo needs nothing; others need a key ---
SEARCH_PROVIDER=duckduckgo           # duckduckgo | google | tavily
GOOGLE_CSE_API_KEY=
GOOGLE_CSE_ENGINE_ID=
TAVILY_API_KEY=

# --- Agent behavior ---
AGENT_MAX_ITERATIONS=60              # hard cap on ReAct iterations per turn before giving up
CONTEXT_TOKEN_LIMIT=100000           # compaction triggers at 80% of this (see agent-system.md)
```

`SESSION_JWT_SECRET` and `GOOGLE_OAUTH_CLIENT_ID` are the only two fields with **no
default** in `app/core/config.py:Settings` — leaving either blank makes the app fail to
start (see Troubleshooting below). Everything else has a working default matching what's
shown above.

Run it:

```bash
uvicorn app.main:app --reload --port 8000
```

Visit `http://localhost:8000/api/healthz` — you should get `{"status": "ok"}` with no
auth required. Interactive API docs are auto-served at `http://localhost:8000/docs`
(FastAPI's default Swagger UI).

## 5. Frontend: `.env.local` walkthrough

In a **new terminal** (leave the backend running):

```bash
cd frontend
npm install
cp .env.example .env.local
```

Edit `frontend/.env.local`:

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000   # backend REST base
NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8000      # backend WS base (note: ws://, not http://)
NEXT_PUBLIC_GOOGLE_CLIENT_ID=<same client id as backend's GOOGLE_OAUTH_CLIENT_ID>
```

All three are `NEXT_PUBLIC_*` — the only kind of variable ever exposed to the browser
(see `frontend/.env.example`'s own warning comment). Never put a secret here.

```bash
npm run dev
```

Visit `http://localhost:3000`. You should see the landing page; clicking through to
`/login` should render a working Google Sign-In button (if it instead shows a warning
box, see Troubleshooting).

## 6. Local OpenAI-compatible inference (free, fully offline LLM option)

Skip both OpenAI and Gemini entirely and run any local server that exposes an
OpenAI-compatible `/v1` chat-completions API instead — e.g. vLLM, Ollama, or LM Studio.

Then in `backend/.env`:

```
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:8080/v1   # or wherever your server listens
OPENAI_API_KEY=                      # leave blank — see below
OPENAI_MODEL=<whatever your server reports as its model name, often ignored by local servers>
OPENAI_SMALL_MODEL=<same, or a second/smaller local model if you're running two servers>
```

There is no separate provider value for this — the `openai` provider itself, pointed at
`OPENAI_BASE_URL`, is what serves any OpenAI-compatible endpoint. When no
`OPENAI_API_KEY` is set but a `base_url` is present, `app/services/llm/openai_provider.py`
substitutes the literal placeholder string `"not-needed"` — local servers don't validate
the key, so this just satisfies the OpenAI SDK's requirement that *some* key string be
passed.

Note: search still needs a provider (DuckDuckGo works with zero config) — a local LLM
only replaces the *LLM*, not web search.

## 7. Running both together

Two terminals, as above:

```bash
# Terminal 1
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev
```

Then: sign in at `http://localhost:3000/login` → complete onboarding → submit a prompt
on the dashboard → watch the agent stream in the Studio.

## 8. Docker Compose alternative

From the repo root:

```bash
cp backend/.env.example backend/.env       # fill in the same values as §4
cp frontend/.env.example frontend/.env.local
export NEXT_PUBLIC_GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com
docker compose up --build
```

`docker-compose.yml` defines three services:
- **`backend`** — builds `backend/Dockerfile`, exposes `8000:8000`, reads
  `backend/.env` via `env_file`, and mounts `./backend/serviceAccountKey.json` read-only
  into the container (harmless if that file doesn't exist and you're using the
  emulator instead — just don't reference it from `.env` in that case).
- **`frontend`** — builds `frontend/Dockerfile` with the three `NEXT_PUBLIC_*` values
  passed as Docker **build args** (baked into the client bundle at build time, since
  Next.js inlines them — this is why they're `args:` under `build:`, not `environment:`),
  exposes `3000:3000`.
- **`firestore-emulator`** — `google/cloud-sdk:slim` running `gcloud emulators
  firestore start --host-port=0.0.0.0:8686 --project=interviewcraft-dev`, exposed on
  `8686:8686`.

To actually use the bundled emulator, set in `backend/.env`:
```
FIRESTORE_EMULATOR_HOST=firestore-emulator:8686
```
(note: the *hostname* is the Compose service name `firestore-emulator`, not
`localhost`, since the backend container reaches it over the Compose network — this
differs from the bare `gcloud emulators` command in §3, where `localhost:8686` is
correct because everything runs on your host directly).

## 9. Running the backend test suite

```bash
cd backend && source .venv/bin/activate
python -m pytest
```

All 92 tests run with **no credentials, no network, no Firestore/emulator** — they
mock Firestore (`tests/conftest.py`'s `fake_fs` fixture) and script fake LLM/search
providers per test. See [backend.md](backend.md) §11 for how this works.

## 10. Verifying the frontend build

```bash
cd frontend && npm run build
```

Must complete with **zero TypeScript errors** — this is the frontend's equivalent
correctness gate to the backend's test suite (per the root and frontend `CLAUDE.md`).

## Troubleshooting

**Backend won't start: `pydantic_core.ValidationError` mentioning
`session_jwt_secret` or `google_oauth_client_id`.** These two env vars have no default
and fail fast at import time (`app/core/config.py:Settings`) — the app literally cannot
construct its settings object without them. Double-check `backend/.env` exists (not
just `.env.example`) and both keys are set to non-empty values. Generate a secret with
`openssl rand -hex 32`.

**Backend won't start / crashes on Firestore calls: can't find credentials.** If you
set neither `GOOGLE_APPLICATION_CREDENTIALS` nor `FIRESTORE_EMULATOR_HOST`,
`get_firestore_client()` falls back to Application Default Credentials, which won't
exist on a fresh local machine outside Cloud Run — you'll get an auth error the first
time any Firestore call actually runs (this fails lazily on first use, not at startup,
since the client is built with `@lru_cache` on first call). Fix by choosing exactly one
of the two paths in §3.

**CORS errors in the browser console** (`has been blocked by CORS policy`). Almost
always `FRONTEND_ORIGIN` in `backend/.env` doesn't exactly match the origin the
frontend is actually served from (scheme + host + port, no trailing slash) —
`app/main.py`'s `CORSMiddleware` only allows exactly `[settings.frontend_origin]`, not
a wildcard. If you changed the frontend's port, update `FRONTEND_ORIGIN` and restart
the backend (env vars are read once at process start).

**Signed in, but immediately logged out / cookie not being set.** Check: (1) the
frontend's `NEXT_PUBLIC_API_BASE_URL` points at the actual running backend; (2) you're
accessing the frontend at `http://localhost:3000` — if you instead use `127.0.0.1:3000`
or a different hostname, the cookie's implicit domain may not match what subsequent
requests send, and `SameSite=Lax` cross-origin behavior gets stricter; (3) look at the
Network tab for the `POST /api/auth/google` response's `Set-Cookie` header — if it's
missing entirely, check the backend logs for a Google ID token verification failure
(usually an audience mismatch, meaning the two `GOOGLE_OAUTH_CLIENT_ID`/
`NEXT_PUBLIC_GOOGLE_CLIENT_ID` values don't actually match, or the frontend's origin
isn't in the OAuth client's Authorized JavaScript origins).

**Google Sign-In button shows a warning box instead of rendering.**
`GoogleSignInButton.tsx` renders this when `env.googleClientId` (i.e.
`NEXT_PUBLIC_GOOGLE_CLIENT_ID`) is empty — confirm `frontend/.env.local` has it set and
restart `npm run dev` (Next.js only reads `.env.local` at process start, not on hot
reload).

**403 on every login/logout/settings-update/etc. request.** Every mutating REST route
requires the `X-Requested-With: XMLHttpRequest` header (`require_csrf_header` in
`app/core/deps.py`) — this is set automatically by the frontend's `apiFetch` wrapper
(`frontend/src/lib/api.ts`), so seeing this from the actual app usually means you're
testing the API directly (curl/Postman) without that header, which is expected
behavior, not a bug.

**WebSocket connects then immediately closes with code 4401 or 4403.** `4401` = no
valid session cookie was presented on the WS upgrade (check you're logged in and the
cookie exists); `4403` = you're logged in but don't own the conversation id in the URL
(e.g. you're testing with someone else's conversation id, or a stale id from a deleted
curriculum).

**Emulator connection refused.** Confirm the emulator process/container is actually
running and listening on the port your `.env`'s `FIRESTORE_EMULATOR_HOST` names. Remember
the hostname differs between the bare-CLI path (`localhost:8686`, §3 Path B) and the
Docker Compose path (`firestore-emulator:8686`, §8) — using the wrong one for your
setup gives a connection-refused error that looks identical either way.

**DuckDuckGo search returns nothing / rate-limited.** `ddgs` has no official API and
occasionally rate-limits; `DuckDuckGoSearchProvider` retries once after a 2-second
backoff and then gives up silently (returns `[]`, not an error) — the agent will notice
via `web_search`'s `count: 0` result and should adapt its query, per
`base_system.md`'s tool-error-adaptation rules. If it's persistent, switch
`SEARCH_PROVIDER` to `google` or `tavily` temporarily (see
[setup-cloud-services.md](setup-cloud-services.md) §6/§7).

## Related documents

- [setup-cloud-services.md](setup-cloud-services.md) — detailed per-service credential
  setup referenced throughout this doc.
- [backend.md](backend.md) — what every env var actually configures in code.
- [agent-system.md](agent-system.md) — what `CONTEXT_TOKEN_LIMIT`/`AGENT_MAX_ITERATIONS`
  actually control.
- [deployment.md](deployment.md) — moving from this local setup to GCP Cloud Run.
