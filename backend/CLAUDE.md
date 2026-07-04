# Backend — AI context

See root `/CLAUDE.md` first. Scoped conventions for `backend/` only. Agent core:
`app/agent/CLAUDE.md`. Full docs: `docs/guides/backend.md`, `docs/guides/agent-system.md`.

## Module map

- `app/main.py` — app factory (`create_app`), CORS, router registration.
- `app/core/config.py` — `Settings` (pydantic-settings). `session_jwt_secret`/
  `google_oauth_client_id` have no default — fail fast at import.
- `app/core/security.py` — Google ID token verify, session JWT mint/decode.
- `app/core/deps.py` — `get_current_user`, `require_csrf_header`, `get_owned_*`
  (ownership checks), in-memory rate limiter.
- `app/core/logging.py` — structured JSON logging; never log secrets.
- `app/api/*.py` — REST routers: `auth`, `onboarding`, `curricula`, `conversations`,
  `settings`, `health`, each mounted with its own `prefix` in `main.py`.
- `app/ws/chat.py` — `/ws/chat/{conversation_id}`; spawns `orchestrator.run_turn` as a
  background task per frame.
- `app/agent/` — THE CORE. See `app/agent/CLAUDE.md`.
- `app/services/firestore.py` — Firestore repo functions. **No ownership checks here**
  — callers must check `owner_uid == current_user.uid` first.
- `app/services/llm/` — `base.py` (protocol), `openai_provider.py` (also serves
  llama.cpp via `OPENAI_BASE_URL`), `gemini_provider.py`, `factory.py`.
- `app/services/search/` — `duckduckgo.py` (default, keyless), `google_cse.py`,
  `tavily.py`, `factory.py`.
- `app/services/resume_parser.py` — in-memory pdf/docx/txt parsing, 5MB cap.
- `app/models/*.py` — pydantic schemas mirroring Firestore docs, subclass `ApiModel`.

## Conventions

- **Async everywhere**; blocking calls need `run_in_executor` (see `duckduckgo.py`).
- **Pydantic v2** (`model_dump()`/`model_validate()`). Tool input models live next to
  the tool class in `app/agent/tools/*.py`.
- **New REST route**: register `dependencies=[Depends(require_csrf_header)]` on every
  mutating route, use `get_owned_curriculum`/`get_owned_conversation` for id-scoped
  fetches, define a response model in `app/models/`.
- **New Firestore field/collection**: update `docs/specs/01-architecture-and-contracts.md`
  §5 first, then `app/services/firestore.py` + the matching model.
- **Tool errors never raise** — `ToolRegistry.execute` converts everything to
  `{"error": ...}`; see `app/agent/CLAUDE.md`.
- **Provider swapping**: `LLM_PROVIDER`/`SEARCH_PROVIDER` resolve via each package's
  `factory.py`, with a per-user override (`users/{uid}.settings.*`) beating the env
  default.

## Run / test

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000     # run
python -m pytest                              # test (92 tests, no credentials needed)
```

## Gotchas

- **Env fail-fast**: `SESSION_JWT_SECRET`/`GOOGLE_OAUTH_CLIENT_ID` have no default —
  importing `app.main` without them raises a `ValidationError` immediately.
  `tests/conftest.py` sets both via `os.environ.setdefault` before any `app.*` import.
- **Emulator vs. credentials**: set exactly one of `FIRESTORE_EMULATOR_HOST` or
  `GOOGLE_APPLICATION_CREDENTIALS`; neither set → falls back to Application Default
  Credentials (correct on Cloud Run, fails lazily on first Firestore call locally).
- **Mocked-test pattern**: `tests/conftest.py`'s `fake_fs` fixture monkeypatches every
  function in `app.services.firestore` onto an in-memory store. Adding a new
  `firestore.py` function used by a test requires a matching fake in `fake_functions`.
- **Module-level orchestrator state**: `_conversation_locks`/`_cancel_events` in
  `app/agent/orchestrator.py` are process-global, keyed by conversation id, with no
  cleanup — a fresh `Orchestrator(settings)` does NOT get its own lock/cancel state.
- **CSRF checked before auth**: `require_csrf_header` is a router-level dependency
  resolved before `get_current_user` — a request with neither gets 403, not 401
  (asserted by `tests/test_auth_and_csrf.py`; this ordering is intentional).
- **Prompt files are code**: `app/agent/prompts/*.md` are cached by `PromptLibrary` —
  edit with the same rigor as `.py` files (see `app/agent/CLAUDE.md`).
