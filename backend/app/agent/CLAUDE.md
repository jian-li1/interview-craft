# Agent core — AI context

See `/CLAUDE.md` and `backend/CLAUDE.md` first. Deep scoped context for
`backend/app/agent/`. Full walkthrough: `docs/guides/agent-system.md`. Contract:
`docs/specs/02-agent-system-spec.md`.

## Orchestrator control flow (`orchestrator.py`)

`Orchestrator.run_turn(...)` — one call per WS frame. Acquires a per-conversation
`asyncio.Lock` (one active run per conversation; concurrent calls get a recoverable
`error`). Loops up to `AGENT_MAX_ITERATIONS` times:
`build_context → chat_stream → route reasoning/text deltas → execute tool calls → check HITL
gate → loop or return`. Returns `DONE` (plain text), `PAUSED` (HITL gate fired),
`CANCELLED` (`stop` frame), or `ERROR`. Re-reads `phase` fresh from Firestore every
iteration — a `transition_phase` call takes effect next iteration, not next turn.

## Adding a new tool

1. Add a pydantic `Input` model + `Tool` subclass in the right
   `app/agent/tools/{research,curriculum,planning,control,user_memory}.py`.
2. Write a thorough LLM-facing `description` (this *is* the prompt for when to use
   it). `execute()` should return `{"error": ...}` or raise `ToolExecutionError`, never
   a bare exception (still caught, but logged as unexpected).
3. Register the instance in `ToolRegistry.__init__`'s `tool_instances` list, and add
   its name to every phase's list in `_PHASE_TOOLS` (or `_ALWAYS_AVAILABLE`).
4. HITL gate tools: add to `HITL_GATE_TOOLS` **and** return `_hitl_gate: True`; instruct
   the model to call it alone (no other tool calls batched the same step).
5. To emit an extra WS event, return `_ws_event`/`_ws_events` in the output dict — the
   orchestrator pops these before building the client-visible JSON preview.
6. Extend `tests/test_tool_registry.py` (phase filtering) and/or a dedicated test file.

## Adding or modifying a phase

1. Update `docs/specs/02-agent-system-spec.md` §2 first, and add the phase to
   `AgentPhase` in `app/models/curriculum.py`.
2. Add allowed transitions to `_VALID_TRANSITIONS` in `app/agent/tools/control.py`
   (`TransitionPhaseTool`) — unlisted transitions are rejected with an error observation.
3. Add `status_map`/`label_map` entries, a `_PHASE_TOOLS` entry (`registry.py`), and a
   `_PHASE_PROMPT_FILES` entry (`memory/manager.py`); write a new prompt file only if
   genuinely new instructions are needed.

## Memory / compaction invariants — do not break

- Layer order is fixed: static prompt → user memory → working memory → (optional)
  saved sources → (optional) summary → recent messages. `build_context` runs **every
  iteration** — keep it cheap.
- Saved research sources are injected as compact per-source entries (title + URL +
  agent-written ≤5-sentence summary, grouped by query, from `curricula/{id}/sources`) —
  NEVER the full page content (that blew up the system blocks in an earlier design).
  Full content re-enters context only via `fetch_url` on a saved URL; after any batch
  with a successful `fetch_url`, `strip_stale_fetch_url_outputs` keeps only the latest
  fetch of each URL in the conversation. Section content gets the same treatment: after
  any batch with a `write_section`/`update_section` call or a successful `read_section`,
  `strip_stale_section_content` keeps only the latest read/write/update occurrence of
  each `(module_id, section_id)` in the conversation.
- Working memory is always rebuilt fresh from the state doc — never cache it.
- Compaction triggers at `tokens_before > 0.8 * CONTEXT_TOKEN_LIMIT`
  (`COMPACTION_TRIGGER_FRACTION`), summarizing the older ~60%
  (`OLDER_FRACTION_TO_COMPACT`) via the small model. Changing these fractions requires
  updating `tests/test_memory.py`/`test_memory_manager_context.py`.
- Tool-output truncation (`RECENT_TOOL_EXCHANGES_KEPT_FULL = 20`) runs on every
  `build_context` call independent of compaction — full data still lives in Firestore.
- Token estimation (`memory/tokens.py`) uses `tiktoken` with a `chars/4` fallback —
  don't assume `tiktoken` is always available.

## Prompt-file editing rules — treat as code

- `app/agent/prompts/*.md` are loaded/cached once per process (`PromptLibrary`) and
  composed per phase (`_PHASE_PROMPT_FILES`, `build_static_system_prompt`).
- `base_system.md`, `citation_guidelines.md`, `visual_guidelines.md` are appended for
  **every** phase — changes here affect the whole agent.
- Be concrete and behavior-shaping, not vague — the model only sees these files, not
  the codebase. Code-level enforcement is minimal (mainly `write_section`'s
  citations check, the Mermaid syntax lint (`mermaid_lint.py`) shared by
  `write_section`/`update_section`, and `TransitionPhaseTool`'s transition validation).
- `profile_synthesis.md`/`compaction.md` are one-shot small-model tasks loaded
  directly by their call sites, not part of phase composition — their output is
  stored verbatim with no post-processing, so keep "return ONLY the output" intact.
- No automated eval exists — sanity-check prompt edits by running a real turn locally.

## HITL gate mechanics

`propose_task_plan`/`request_user_input` pause the loop via `_hitl_gate: True` (+
`HITL_GATE_TOOLS` as a registry backstop) — the orchestrator pauses if any call this
step was a successful gate call, even mid-`max_iterations`. Resumption is the next WS
frame: `plan_decision` is handled specially by `_apply_plan_decision` (approve →
materialize stubs, jump to `writing`; modify → record feedback and leave phase at
`awaiting_approval` — the agent itself picks `outline_planning` or `deep_research` via
`transition_phase`); a clarifying question emits `user_input_requested` and persists
`pending_user_input` on the state doc (replayed on WS reconnect so a refresh restores the
card; cleared the moment the next `user_message` frame arrives) — resumption is still an
ordinary `user_message` frame, no dedicated "answer" type.
