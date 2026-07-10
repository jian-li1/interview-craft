# Cloud services setup

Per-service instructions for every external service InterviewCraft can use, and exactly
which `.env` variable each credential goes into. Only three things are required to run
at all: a Google OAuth client, a Firebase/Firestore project (or the local emulator —
see [setup-local.md](setup-local.md)), and one LLM provider key (or a local
OpenAI-compatible server). Everything else is optional.

| Service | Required? | Free tier? | Goes into |
|---|---|---|---|
| Google OAuth 2.0 client | Yes | Yes | `backend/.env` `GOOGLE_OAUTH_CLIENT_ID`; `frontend/.env.local` `NEXT_PUBLIC_GOOGLE_CLIENT_ID` |
| Firebase / Firestore | Yes (or emulator) | Yes | `backend/.env` `FIREBASE_PROJECT_ID` + `GOOGLE_APPLICATION_CREDENTIALS` |
| OpenAI API | One LLM provider required | No | `backend/.env` `OPENAI_API_KEY` |
| Google Gemini API | Optional | Has a free tier | `backend/.env` `GEMINI_API_KEY` |
| DuckDuckGo search | No (default, keyless) | Yes | nothing to configure |
| Google Custom Search (CSE) | Optional | Yes, limited | `backend/.env` `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_ENGINE_ID` |
| Tavily | Optional | Yes, limited | `backend/.env` `TAVILY_API_KEY` |

## 1. Google OAuth 2.0 client (required)

This is the one credential used by *both* apps — the same client ID goes into
`backend/.env` (`GOOGLE_OAUTH_CLIENT_ID`, used server-side to verify the audience claim
of every Google ID token) and `frontend/.env.local`
(`NEXT_PUBLIC_GOOGLE_CLIENT_ID`, used client-side by Google Identity Services to render
the sign-in button and mint the ID token in the first place).

1. Go to [Google Cloud Console → APIs & Services →
   Credentials](https://console.cloud.google.com/apis/credentials). Create a project if
   you don't have one yet (top-left project picker → "New Project").
2. If prompted, configure the **OAuth consent screen** first: External user type is
   fine for development; App name = "InterviewCraft" (or anything); support email = your
   own; no scopes beyond the default `openid`/`email`/`profile` are needed; add your own
   Google account under "Test users" if the app stays in "Testing" publishing status.
3. Back on the Credentials page: **+ Create Credentials → OAuth client ID**.
4. Application type: **Web application**.
5. Name: anything, e.g. "InterviewCraft Web".
6. **Authorized JavaScript origins** — add:
   - `http://localhost:3000` (local frontend dev server)
   - your production frontend URL later, after your first Cloud Run deploy (see
     [deployment.md](deployment.md)'s post-deploy checklist) — you can always come back
     and add more origins to the same client.
7. **Authorized redirect URIs**: leave empty. This app uses Google Identity Services'
   token-based sign-in (a JS callback delivering an ID token directly), not the
   redirect-based OAuth authorization-code flow, so no redirect URI is needed.
8. Click **Create**. Copy the **Client ID** (looks like
   `123456789-abc...xyz.apps.googleusercontent.com`) — you do *not* need the client
   secret for this flow.
9. Put the same value in both places:
   - `backend/.env`: `GOOGLE_OAUTH_CLIENT_ID=<client-id>`
   - `frontend/.env.local`: `NEXT_PUBLIC_GOOGLE_CLIENT_ID=<client-id>`

Verified server-side by `backend/app/core/security.py:verify_google_id_token`, which
checks the token's audience against exactly this value.

## 2. Firebase / Firestore (required, or use the emulator)

Two paths — pick one. The emulator path (§2b) needs no Google account at all; see
[setup-local.md](setup-local.md) for the emulator's exact `docker compose`/`gcloud`
commands. This section covers the real-project path.

### 2a. Real Firebase project (console)

1. Go to the [Firebase Console](https://console.firebase.google.com/), **Add project**
   (or reuse the same GCP project your OAuth client lives in — Firebase projects *are*
   GCP projects under the hood, so this is often the simpler choice).
2. Once created, go to **Build → Firestore Database → Create database**. Choose
   **Native mode** (not Datastore mode) and a location (e.g. `us-central1`).
3. Get a service account key: **Project settings (gear icon) → Service accounts →
   Generate new private key**. This downloads a JSON file — save it as
   `backend/serviceAccountKey.json` (this exact path is what `docker-compose.yml`
   mounts, and what `.env.example` suggests by default; the file is gitignored).
4. `backend/.env`:
   ```
   FIREBASE_PROJECT_ID=<your-firebase-project-id>
   GOOGLE_APPLICATION_CREDENTIALS=./serviceAccountKey.json
   FIRESTORE_EMULATOR_HOST=
   ```

### 2b. Real Firebase project (gcloud CLI, no console)

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable firestore.googleapis.com
gcloud firestore databases create --location=us-central1
gcloud iam service-accounts create interviewcraft-dev \
  --display-name "InterviewCraft local dev"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member "serviceAccount:interviewcraft-dev@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role "roles/datastore.user"
gcloud iam service-accounts keys create backend/serviceAccountKey.json \
  --iam-account "interviewcraft-dev@YOUR_PROJECT_ID.iam.gserviceaccount.com"
```

Then set the same two `backend/.env` values as in §2a.

### 2c. Firestore emulator (no account, fully local)

See [setup-local.md](setup-local.md)'s emulator section for exact commands (both the
bare `gcloud emulators firestore start` path and the `docker compose up` path, which
runs a `google/cloud-sdk:slim` container per `docker-compose.yml`'s
`firestore-emulator` service). In this mode `backend/.env` sets
`FIRESTORE_EMULATOR_HOST=localhost:8686` and leaves `GOOGLE_APPLICATION_CREDENTIALS`
blank — `app/services/firestore.py` detects the emulator host and skips credential
verification entirely.

## 3. OpenAI API key (one LLM provider required, unless using a local OpenAI-compatible server)

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys), sign in,
   **Create new secret key**. Copy it immediately (shown once).
2. `backend/.env`:
   ```
   LLM_PROVIDER=openai
   OPENAI_API_KEY=sk-...
   OPENAI_MODEL=gpt-4o
   OPENAI_SMALL_MODEL=gpt-4o-mini
   ```
   `OPENAI_MODEL` is used for the main ReAct loop; `OPENAI_SMALL_MODEL` is used for
   compaction, profile synthesis, and anywhere `small=True` is passed to the provider
   (see [agent-system.md](agent-system.md) §6). Any two chat-completions-capable model
   names work — swap them for cheaper/faster or more capable models as needed.
3. This is a paid API — there is no free tier. For a free local alternative, see
   [setup-local.md](setup-local.md)'s local-inference section (`LLM_PROVIDER=openai` +
   `OPENAI_BASE_URL`).

## 4. Google Gemini API key (optional)

1. Go to [Google AI Studio](https://aistudio.google.com/apikey) (or Cloud Console →
   Vertex AI, for a GCP-billed alternative), **Create API key**.
2. `backend/.env`:
   ```
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=...
   GEMINI_MODEL=gemini-2.5-pro
   GEMINI_SMALL_MODEL=gemini-2.5-flash
   ```
3. Has a free tier with rate limits; check current quotas on the AI Studio dashboard.
   Implemented in `backend/app/services/llm/gemini_provider.py` via the `google-genai`
   SDK — same `LLMProvider` interface as OpenAI, so switching `LLM_PROVIDER` is the only
   change needed.
4. Per-user override: even with a server default of `openai`, an individual signed-in
   user can pick Gemini from **Settings → Preferences** if their account settings
   specify it (`users/{uid}.settings.llm_provider`) — see
   `app/services/llm/factory.py`'s override resolution.

## 5. DuckDuckGo search (default — nothing to configure)

`SEARCH_PROVIDER=duckduckgo` is the default in `backend/.env.example` and requires no
API key or account — it's the `ddgs` Python package (`backend/app/services/search/
duckduckgo.py`), which scrapes DuckDuckGo's public search results. It has no official
API, so it can occasionally rate-limit; the provider retries once with a 2-second
backoff before giving up and returning an empty result list (never raises). No setup
needed beyond leaving `SEARCH_PROVIDER` unset or explicitly `duckduckgo`.

## 6. Google Custom Search (CSE) (optional)

1. Create a Programmable Search Engine at
   [programmablesearchengine.google.com](https://programmablesearchengine.google.com/):
   **Add** → give it a name → under "What to search," choose **Search the entire web**
   (toggle it on — by default a new CSE is scoped to specific sites) → **Create**.
2. Open the new engine's **Setup/Overview** page and copy the **Search engine ID**
   (this is `cx` in the API, referred to as `GOOGLE_CSE_ENGINE_ID` here).
3. Get an API key for the Custom Search JSON API: Google Cloud Console → **APIs &
   Services → Library** → search "Custom Search API" → **Enable** → then **Credentials
   → Create Credentials → API key**. (You can reuse the same GCP project as your OAuth
   client and/or Firebase project.)
4. `backend/.env`:
   ```
   SEARCH_PROVIDER=google
   GOOGLE_CSE_API_KEY=<api-key>
   GOOGLE_CSE_ENGINE_ID=<search-engine-id>
   ```
5. Free tier: 100 queries/day; paid beyond that. Implemented in
   `backend/app/services/search/google_cse.py`, which caps results at Google's hard
   maximum of 10 per request regardless of the tool's requested `max_results`.

## 7. Tavily (optional)

1. Sign up at [tavily.com](https://tavily.com/), grab the API key from the dashboard
   (free tier available, credit-based).
2. `backend/.env`:
   ```
   SEARCH_PROVIDER=tavily
   TAVILY_API_KEY=tvly-...
   ```
3. Implemented in `backend/app/services/search/tavily.py` — a search API purpose-built
   for LLM/agent use cases; its `content` field is mapped to our `snippet` field.

## Related documents

- [setup-local.md](setup-local.md) — full local environment walkthrough (env var
  reference, running both apps, Docker Compose, local inference, troubleshooting).
- [deployment.md](deployment.md) — how these same credentials get provisioned as GCP
  Secret Manager secrets for production.
- [docs/specs/01-architecture-and-contracts.md](../specs/01-architecture-and-contracts.md)
  §4 — the canonical env var list this document maps credentials onto.
