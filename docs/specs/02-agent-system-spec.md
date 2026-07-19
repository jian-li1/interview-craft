# InterviewBlueprint — Agentic System Specification (THE CORE)

This is the most important part of the application. Implement it carefully and completely.
Lives in `backend/app/agent/`.

## 1. Overview

A single **Orchestrator** agent runs a Planning & Reasoning **ReAct loop**
(Reason → Act(tool) → Observe → repeat) over a phase state machine. Phase-specific
instruction files (markdown, in `agent/prompts/`) are composed into the system prompt.
The agent streams everything (reasoning, text, tool calls/results) to the client via the
WS event protocol in spec 01 §7. Human-in-the-loop gates pause the loop for user decisions.

## 2. Phase state machine

```
intake ──► deep_research ──► outline_planning ──► awaiting_approval ──► writing ──► review ──► ready ──► refinement (steady state)
              ▲       │              ▲                     │
              └───────┘              └── modify + feedback ┘  (agent picks outline_planning or
           (gap found mid-revision)                            deep_research via transition_phase)
```

- **intake**: Understand the user's request; read user profile memory; ask clarifying
  questions ONLY if the request is genuinely ambiguous (interview type unclear). Create the
  curriculum doc (status=researching) and transition.
- **deep_research**: Multi-query web research. The agent generates diverse search queries
  covering: (a) the interview type's format/stages/evaluation criteria, (b) foundational
  concepts and skills to learn, (c) REAL sample interview questions commonly asked,
  (d) strong sample answers / answer frameworks, (e) preparation roadmaps, (f) company- or
  domain-specific specifics from the user prompt. `web_search` returns `{title, url,
  snippet}` results; snippets are for RELEVANCE TRIAGE ONLY. Every source worth keeping
  is fetched with `fetch_url` (full page as Markdown) and READ; the agent then calls
  **`save_sources(query, sources: [{url, summary}])`** with its own ≤5-sentence summary
  per kept URL — the summary (never the full page) is pinned into the agent's working
  memory (system prompt), grouped under the query that surfaced it, while the full
  Markdown is persisted on the source doc as citation evidence. To re-read a saved
  page, the agent re-fetches its URL; whenever the same URL is fetched again, all
  earlier `fetch_url` outputs for that URL are stripped from the conversation (only the
  latest fetch keeps its content), so full page content never appears twice.
  `save_sources` enforces read-before-save: a URL not fetched during the current run is
  rejected with `not_fetched`. Duplicate URLs are never saved twice (URL-hash doc ids).
  There is no source-count target, upper or lower — the agent keeps researching, purely
  qualitatively, until every relevant coverage area has solid saved sources and new
  searches hit diminishing returns. Every saved source keeps its URL — this feeds
  citations later.
- **outline_planning**: Synthesize the saved sources (visible in working memory) into a curriculum outline (modules →
  sections) + a task plan — EXACTLY one task per planned section (never an overview
  task; the overview is written later in `review` via `write_curriculum_overview`).
  Personalize using the synthesized user profile. Call `propose_task_plan` → the tool
  first validates the plan server-side (task id format `m{X}-s{Y}`, `module_ref`
  prefix match, contiguous module/section numbering, that `modules[]` ids exactly cover
  the tasks' module set with a real non-empty title per module (<=100 chars, though the
  error text quotes the tighter 80-char prompt target), and that
  `outline_markdown`'s `Section X.Y` labels match `tasks` 1:1) and returns an error
  observation with no writes performed on any violation. On success it emits `phase_change`
  (awaiting_approval), `progress` (task counts, if any tasks), and `plan_proposed` WS
  events (in that order), sets curriculum status=awaiting_approval and persists the
  progress blob (including `modules` on the plan doc), and **pauses the loop**.
- **awaiting_approval (HITL)**: Resumes on `plan_decision`. approve → materialize modules/
  sections stubs in Firestore (module doc title comes from the plan's structured
  `modules[]` entry for that module_ref — legacy plans lacking a matching entry fall
  back to deriving the title from the module's first task title; section doc id = task
  id minus its `m{X}-` module prefix, e.g. task `m1-s2` → section doc `s2` under module
  doc `m1`; legacy task ids without that prefix fall back to using the full id
  verbatim), status=writing, go to writing, emit live `phase_change` (writing) +
  `progress` WS events. modify → feedback
  appended, plan status set to `revising`; the orchestrator does NOT force a phase — it
  stays `awaiting_approval` and the agent itself calls `transition_phase` to choose
  `outline_planning` (revise directly from saved sources) or `deep_research` (gather
  more sources first, when the feedback needs topics/depth not already covered); no
  orchestrator-emitted `phase_change` on modify — `transition_phase` emits its own once
  the agent transitions.
- **writing**: Pop tasks from the queue one at a time. For each: scan the saved-source
  summaries in working memory, `fetch_url` the relevant saved URLs to pull full content
  back into context, and — explicitly encouraged when saved coverage is thin for the
  section — run further targeted `web_search` → `fetch_url` → `save_sources` rounds
  before writing; then `write_section` with full rich markdown. `write_section` enforces a
  target guard first: in `writing`/`review` it only accepts module/section ids already
  materialized from the approved plan, rejecting any invented id with an error listing the
  existing ids. Update progress after each task (WS `progress` + `curriculum_updated`).
  Persist task status so a crashed/resumed run continues where it left off.
  `transition_phase("review")` is rejected while any plan task is still pending or any
  section doc is still `"planned"`.
- **review**: Curriculum status=reviewing. Verify every section has citations, diagrams
  where valuable, sample Q&A coverage; write the curriculum `overview`; then
  status=ready. `transition_phase("ready")` is
  rejected server-side if any section isn't `"complete"` or the overview is still empty.
- **refinement**: Steady conversational state. User asks for modifications
  (`update_section`), explanations ("explain X from module 2" → read section, explain in
  chat, do NOT modify unless asked), additions, or new deep-dives (may trigger targeted
  research).

Phase transitions persist to `curricula/{id}/state/main` so runs are resumable.

## 3. ReAct loop implementation (`orchestrator.py`)

```python
async def run_turn(ctx: AgentContext, user_message: str | PlanDecision):
    memory.append_user_message(...)
    for i in range(MAX_ITERATIONS):
        messages = await memory.build_context(ctx)      # see §5 — includes compaction
        stream = llm.chat_stream(messages, tools=registry.specs_for_phase(ctx.phase))
        # stream reasoning/text deltas to WS as they arrive
        result = await consume(stream, ws_emitter)
        if result.tool_calls:
            for tc in result.tool_calls:
                emit tool_call_start
                output = await registry.execute(tc, ctx)   # errors → structured error output, loop continues
                emit tool_call_result (output_full = complete result; output_preview ≈ 1500-char slice)
                memory.append_tool_exchange(tc, output)
            if a HITL tool (propose_task_plan / request_user_input) was called:
                persist state; return PAUSED               # loop exits; resumes on next client frame
        else:
            memory.append_assistant_message(result)
            return DONE                                    # plain text answer ends the turn
    emit error("max iterations")
```

Key requirements:
- **Streaming**: use the provider's native streaming; forward text deltas immediately.
  Reasoning comes from the provider's own native reasoning stream, not a prompt convention:
  OpenAI-compatible endpoints expose a `reasoning_content` delta field on streaming chat
  completions (the DeepSeek/vLLM convention; `reasoning` is read as a fallback for
  OpenRouter-style gateways; first-party OpenAI models expose neither field, so no reasoning
  events are emitted for them), and Gemini exposes thought-summary parts (`part.thought ==
  true`) when `thinking_config.include_thoughts` is set on the request. Providers emit these
  as `ReasoningDelta` events (vs. `TextDelta` for answer text), which the orchestrator
  forwards 1:1 as `reasoning_delta`/`text_delta` WS events.
- **Cancellation**: `stop` frame sets a cancel event checked between iterations, during
  streaming, and between/during tool calls — the check is a race (via a small
  `_wait_cancellable` helper) against whatever the loop is currently awaiting, so a
  `stop` interrupts a stalled LLM stream read or an in-flight tool call (e.g. a slow
  `fetch_url`) immediately rather than only at the next coarse checkpoint; persist
  state before exiting so the run is resumable.
- **Tool errors never crash the loop**: return `{"error": "..."}` as the observation so the
  agent can adapt (retry different query, skip source, etc.).
- Concurrency guard: one active run per conversation (asyncio lock keyed by conv id).
- **Synthetic system messages on `plan_decision`**: `_apply_plan_decision` appends a
  `{"role": "system", ...}` message via `fs.append_message` in both branches so the
  resumed model can see the decision already happened instead of re-asking the user:
  approve → a message stating the plan was APPROVED, stubs materialized, phase is now
  `writing`, and to begin the first task immediately without asking for confirmation;
  modify → a message stating the user's feedback text and instructing the model it is
  still in `awaiting_approval` and MUST choose its next phase via `transition_phase`
  (`deep_research` if the feedback needs uncovered topics/depth, else
  `outline_planning`), then revise and re-propose via `propose_task_plan`. The approve
  branch also emits a live `phase_change` (`writing`) + `progress` WS event so the
  client's phase banner updates immediately rather than only on the next reconnect; the
  modify branch emits no `phase_change` — `transition_phase` emits its own once the agent
  picks a target phase.
- **Synthetic system message for the reader's "current section" chip**: when a
  `user_message` frame carries a valid `section_context` (spec 01 §7 — the composer's
  section-context toggle chip; ids re-validated against the curriculum, section must not
  be `"planned"`), `_run_turn_inner` appends a `{"role": "system", ...}` note ahead of
  the user's own message naming the module/section the user is reading and instructing
  the agent to call `read_section` on it if the upcoming message relates to it. On the
  same successful validation, the resolved `{module_id, section_id, label}` snapshot is
  also stamped onto the persisted user message doc (spec 01 §5) for the frontend's
  inline "context included" bubble chip.

## 4. Tool catalog (`agent/tools/`)

Each tool = a class/module with: `name`, `description` (thorough, written for the LLM),
pydantic input model (→ JSON schema for the provider), async `execute(input, ctx)`.
A `ToolRegistry` exposes provider-formatted specs filtered by phase (research tools hidden
during writing-only refinements, etc. — keep filtering simple: a phase→allowed-tools map).

**Research tools**
- `web_search(query, max_results=8)` → list of {title, url, snippet} via search
  provider. Snippets are relevance triage only — no page fetching happens here.
- `fetch_url(url)` → the page's `<title>` plus full content converted to Markdown
  (httpx; SSRF guard blocking private/internal IPs; scripts/styles/svg stripped via
  BeautifulSoup, then markdownify; graceful `{"error": ...}` on failure). Per-page
  content is capped only defensively (200k chars, flagged `content_truncated`) to
  respect Firestore's 1 MiB doc limit. Successful fetches populate an in-run page cache
  (`ctx.page_cache`) that `save_sources` reads from. After any batch containing a
  successful `fetch_url`, the orchestrator runs `strip_stale_fetch_url_outputs`: for
  every URL fetched more than once in the conversation, only the LATEST fetch keeps its
  content — earlier ones are rewritten to `{url, note}` so the same page never occupies
  context twice.
- `save_sources(query, sources: [{url, summary}])` → persists each non-duplicate,
  already-fetched URL to `curricula/{id}/sources` (doc id = URL hash → dedup) with the
  agent's ≤5-sentence `summary` (max 1500 chars, the only part later injected into
  working memory) plus the cached full `content_markdown` as citation evidence. Strictly
  enforces read-before-save: a URL absent from the in-run page cache is rejected with
  status `not_fetched` (no silent re-fetch). Returns per-URL statuses
  (saved / duplicate_skipped / not_fetched).

**User-memory tools**
- `get_user_profile()` → synthesized_profile + structured fields (target roles, experience level, learning style, timeline).

**Planning tools**
- `propose_task_plan(outline_markdown, description, tasks[], modules[])` → HITL GATE: validates the plan first (task id `m{X}-s{Y}`, `module_ref` prefix match, contiguous module/section numbering, `modules[]` ids exactly covering the tasks' module set with a non-empty title and description per module, `outline_markdown`'s `Section X.Y` labels matching `tasks` 1:1, and a non-empty curriculum-level `description` — real hard caps are 100/500 chars (title/description), looser than the 80/300-char figures the error text quotes, so a model slightly overshooting the prompt target isn't forced into a retry) — error observation, no writes, if invalid; on success saves plan (including `modules` and `description`), sets status awaiting_approval, writes `description` onto the curriculum doc (so the dashboard card can render it immediately — re-proposals overwrite it, latest wins), emits `phase_change` + `progress` + `plan_proposed` (unchanged payload — `modules`/`description` are not mirrored into it), pauses loop.
- `get_task_plan()` → current plan + task statuses.

**Curriculum tools**
- `list_curriculum_structure()` → modules/sections tree with statuses (compact).
- `write_section(module_id, section_id, title, content_markdown, citations[])` → target guard first: in `writing`/`review`, module_id/section_id must already exist (materialized from the approved plan) or the write is rejected with an error listing existing ids; in `ready`/`refinement`, the module must already exist (write_section never creates modules — error directs the model to `create_module`, naming the next sequential module id), and only a brand-new section at the next sequential id (`s{K+1}`) may be created — an already-existing section id is rejected too (error directs the model to `update_section`), and any other new id is rejected naming the expected `s{K+1}`. Then validates citations non-empty for research-based content; marks task done (matching `module_id-section_id` or, for legacy docs, the section id alone); emits `curriculum_updated` + `progress`; also refreshes the parent module's derived status (planned→writing→complete, from its sections) and estimated_minutes (~200 wpm from written content).
- `read_section(module_id, section_id)` → full content (available from `writing` onward: continuity re-reads while writing, explanation/refinement later).
- `update_section(module_id, section_id, content_markdown, citations[], change_note)` → for refinement phase; also refreshes the parent module's derived status/estimated_minutes.
- `create_module(module_id, title, description)` → `ready`/`refinement` only. Creates a brand-new module. `module_id` must be exactly the next sequential id `m{N+1}` (N = current highest numbered module id) or the call is rejected naming the expected id; an already-existing `module_id` is rejected too (error directs the model to `update_module`). `title`/`description` non-empty (same bounds as `propose_task_plan`'s per-module validation: real hard caps 100/500 chars, error text quotes the tighter 80/300-char prompt targets) — both checked at runtime, error observation on failure, no write. On success, creates the module doc (`order` = current module count, `objectives: []`, `status: "planned"`, `estimated_minutes: 0`), refreshes the curriculum's cached `module_count`, and emits `curriculum_updated` (scope `module`).
- `update_module(module_id, title?, description?)` → `ready`/`refinement` only. Updates an existing module's `title` and/or `description` in place (sections/status/ordering untouched). Errors if the module doesn't exist (lists existing ids) or if neither field is provided; whichever field is provided is bounds-validated with the same rules as `create_module`. Emits `curriculum_updated` (scope `module`) on success.
- After any batch containing a `write_section`/`update_section` call or a successful
  `read_section` call, the orchestrator runs `strip_stale_section_content`: for each
  (module_id, section_id), only the latest content-bearing occurrence keeps its markdown —
  earlier `read_section` outputs are rewritten to `{module_id, section_id, note}` and
  earlier `write_section`/`update_section` inputs have `content_markdown` replaced with a
  note (their outputs, small status dicts, are kept), so a section's content never
  occupies context twice.
- `write_curriculum_overview(overview_markdown, emoji, tags[])` → sets curriculum overview/metadata.
- `set_curriculum_title(title, emoji?)` → renames the curriculum (and the linked
  conversation's sidebar/dashboard title) away from the placeholder derived from the raw
  user prompt. Always available (not phase-restricted); the agent is instructed to call
  this as one of its first actions in `intake`. Emits `curriculum_updated` (scope
  `curriculum`), same shape as `write_curriculum_overview`'s event, so the frontend
  refetch path is unchanged.
- `set_module_status / internal helpers` as needed; emits `curriculum_updated` (scope `module`).

**Control tools**
- `request_user_input(question, options[]?)` → HITL gate for clarifying questions: persists `pending_user_input` on the state doc, emits `user_input_requested` (question rendered as an interactive chat card, quick-pick options plus always-present free text), pauses loop. Replayed on WS reconnect if still pending; cleared on the next `user_message` frame (the ordinary reply, no dedicated "answer" frame type).
- `update_scratchpad(content)` → overwrite agent scratchpad in state doc (agent's own working notes: what's done, what's next, open questions).
- `transition_phase(next_phase, reason)` → validated transition; updates state + curriculum status; emits `phase_change`. Two transitions carry an additional completeness gate (error observation, no transition applied, if unmet): `writing`→`review` requires every module_ref-bearing plan task `"done"` and no section doc left `"planned"`; `review`→`ready` requires every section `"complete"` and the curriculum `overview` non-empty.

## 5. Memory & context management (`agent/memory/`)

**Layered memory**, assembled by `MemoryManager.build_context()` on every iteration:

1. **Static system prompt**: base_system.md + current phase instruction file + citation +
   visual guidelines (see §6).
2. **User memory**: synthesized profile (injected as a system block: "About the user: ...").
3. **Working memory**: agent state doc — phase, task queue with statuses, scratchpad,
   plan version. Injected as a compact system block each turn (always fresh, never stale).
4. **Saved research sources**: one compact entry per source saved via `save_sources` —
   title, URL, and the agent's own ≤5-sentence summary — grouped by the query that
   surfaced it, injected as a system block (after the working-memory block, before the
   summary block), every iteration, in every phase. Full page content is deliberately
   NOT injected (that blew up context in an earlier design): it lives on the source doc
   as evidence, and the agent re-fetches a saved URL when it needs the full text —
   duplicate fetches of the same URL are stripped from the conversation, keeping only
   the latest.
5. **Episodic memory**: conversation summary (if compaction has run) + recent messages +
   tool exchanges verbatim.

**Auto-compaction** (`memory/compaction.py`):
- Track token estimate with tiktoken (fallback: chars/4) over the assembled context.
- When estimate > 0.8 × CONTEXT_TOKEN_LIMIT: take the older ~60% of messages, run
  `compaction_llm` — the conversation's currently-selected model; there is no separate
  "small model" anymore — with `prompts/compaction.md` to produce a structured summary
  (key decisions, user preferences expressed, curriculum state, unresolved items), merge
  into `conversations/{id}.summary`, set `compacted_through`, and rebuild context as
  [system blocks] + [summary block] + [remaining recent messages]. Emit WS `compaction`.
- The model is replayed each tool call's full `output_full`; only outputs older than the
  last 20 exchanges (`RECENT_TOOL_EXCHANGES_KEPT_FULL`) are truncated to short previews in
  the rebuilt context (full data also lives in Firestore saved sources / sections).
- `build_context` also accepts `on_compaction_start(tokens_before)` — fired right before
  the summarization call, so the client can render an in-progress chip ahead of the
  (potentially slow) LLM round-trip — and `on_context_usage(tokens)` — fired at the end
  of every call, in both the compaction and no-compaction branches, with the final token
  estimate of the returned context, driving the composer's context-usage warning card.
  `token_estimate` on the conversation doc always reflects this same CURRENT
  (post-compaction, if any ran this call) estimate, and a compaction pass also persists
  `last_compaction: {tokens_before, tokens_after}` as a checkpoint for the WS reconnect
  snapshot to replay a resolved chip.

**Manual compaction** (`Orchestrator.compact_now`): the client's "Compact now" button
(context-usage warning card, shown at >=70% of `CONTEXT_TOKEN_LIMIT`) sends a `compact`
WS frame (optionally carrying `model`, the composer's model-chip selection), handled by
`app/ws/chat.py` spawning `compact_now` as a background task — mirroring `run_turn`'s
one-run-per-conversation lock (a `compact` frame while a turn is active gets a
recoverable busy error, not queued). `compact_now` resolves the effective model (frame
value → the conversation doc's persisted `selected_model` → `Settings.default_model`,
via `resolve_model`; no more per-user settings lookup), persists it onto the
conversation doc if it changed, loads that model's LLM provider (no search provider —
compaction never calls tools), and calls `build_context(..., force_compact=True)`,
which runs compaction even below the 0.8x token threshold as long as there are enough
candidate messages (`len(candidate_messages) > 2`) to fold meaningfully; the assembled
message list is discarded since the point of this call is purely the persisted-summary
side effect. It streams the same `compaction_start` → `compaction` → `context_usage` WS
events as auto-compaction; if `build_context` skipped compaction anyway (too few
messages), `compact_now` emits a recoverable "not enough conversation history" error
instead of silently no-op'ing.

## 6. Prompt files (`agent/prompts/*.md`) — write these THOROUGHLY

These are loaded from disk (cached) and composed per phase. Each must be a genuinely
detailed, high-quality instruction document (not a stub). Required files:

- `base_system.md` — Identity ("InterviewBlueprint Agent"), mission, ReAct behavioral rules
  (reason internally first (native reasoning): assess state → decide next action; one
  coherent batch of tool calls per step; adapt on tool errors), tone, honesty about sources,
  personalization mandate (always ground advice in the user profile), safety rules
  (no fabricated citations — every factual claim traceable to a saved source).
- `research_phase.md` — Deep-research methodology: the search→fetch→read→save rhythm
  (`web_search` snippets are triage only; `fetch_url` is the mandatory reading step for
  every kept source; `save_sources` pins a ≤5-sentence agent-written summary per keeper
  into working memory, with full content re-fetchable on demand), summary-writing
  standards (name the page's concrete assets, not vague praise — the summary is the
  coverage ledger entry), query diversification strategy (the 6 coverage areas in §2),
  source quality heuristics (prefer official docs, well-known prep sites, recent
  content; judge by the FETCHED content, not the snippet), stop criteria (purely
  qualitative coverage checklist + diminishing returns, no numeric source-count
  target), anti-patterns (never save unfetched URLs, no vague summaries, don't retry
  failed fetches, don't re-search covered topics), and guidance for re-entering the
  phase after a plan-modify decision (targeted queries only for the feedback gap, not a
  full re-sweep, then `transition_phase("outline_planning")`).
- `planning_phase.md` — Outline design principles: beginner→interview-ready arc,
  module sequencing (foundations → core skills → question drills → mock/strategy),
  every module must include sample-questions-with-model-answers sections, no fixed
  module/section count limit (scope driven by researched material and user goals, with
  timeline respected via priority ordering rather than capping count), task plan format,
  how to incorporate `modify` feedback on revision (choosing `outline_planning` vs.
  `deep_research` via `transition_phase` before revising).
- `writing_phase.md` — Section authoring standards: rich GitHub-flavored Markdown; use
  Mermaid diagrams (flowchart/sequence/mindmap) wherever a process/relationship is
  explained; tables for comparisons; callout blockquotes; concrete examples; sample
  interview questions with STRONG model answers personalized to the user's background
  (use their actual experience level/target roles); inline citation markers `[^n]`
  with a footnote list matching the citations array; length guidance (800–2000 words/section);
  ground every section in saved sources: scan their summaries in working memory,
  `fetch_url` the relevant saved URLs for full content, and run further targeted
  `web_search` → `fetch_url` → `save_sources` top-ups (encouraged, not exceptional)
  when saved coverage is thin for the section.
- `review_phase.md` — Structured quality pass over the whole draft curriculum: a
  per-section checklist (citations, diagrams, sample-Q&A coverage, 800-2000 word length,
  coherence); fix failures directly via `write_section` overwrite (never a fragment);
  sources come only from the already-saved source pool (re-read via `fetch_url` on a
  saved URL; no new searching);
  after all modules pass, `write_curriculum_overview`; exit via `transition_phase("ready")`.
- `refinement_phase.md` — How to handle edits (read before update, minimal targeted
  changes, preserve citations, describe what changed), explanations (teach in chat with
  analogies matched to user profile; don't modify content unless asked), additions
  (may require targeted research first).
- `citation_guidelines.md` — Citation format contract: `[^n]` markers, footnote section
  `## Sources` at the end of each section's markdown, citations array must mirror the
  footnotes, no fabricated URLs, every non-obvious factual claim cited.
- `visual_guidelines.md` — Mermaid syntax guardrails (quote node labels, avoid parentheses-in-labels
  pitfalls, keep diagrams <25 nodes), when to use which diagram type, color usage via
  Mermaid themes/classDefs, emoji usage in headings.
- `intake_phase.md` — When to ask clarifying questions vs. proceed; how to name the curriculum.
- `profile_synthesis.md` — (Used by the onboarding synthesize endpoint, on the server
  default model — first `OPENAI_MODEL` entry) Transform raw bio/background/resume text
  into a dense 200–350 word third-person profile: background, strengths, gaps relative
  to target roles, learning style, personalization hooks.
- `compaction.md` — (Run on the conversation's selected model — no separate "small
  model") Summarization contract: preserve decisions, user preferences/corrections,
  curriculum/plan state, open threads; drop pleasantries and superseded tool details;
  output structured markdown under fixed headings.
- `dashboard_suggestions.md` — (Used by `app.services.prompt_suggestions`, fired
  asynchronously when `PUT /api/onboarding` completes onboarding, on the server default
  model) Generate personalized dashboard PromptBox content from the user's
  `synthesized_profile` + raw target_roles/skills/experience_level/timeline: exactly 5
  short (<~60 char) example-prompt chips varying in angle (role-specific, skill-focus,
  format-focus — adapted to the user's actual field, not defaulted to software
  engineering), plus one fuller (~15-25 word) textarea placeholder sentence not prefixed
  with "e.g." (the frontend adds that). Output is STRICT JSON only:
  `{"suggestions": [...5 strings...], "placeholder": "..."}` — no markdown fences, no
  prose; the caller tolerantly strips a fence if the model adds one anyway.

## 7. LLM provider abstraction (`services/llm/`)

```python
class LLMProvider(Protocol):
    async def chat_stream(self, messages, tools=None) -> AsyncIterator[LLMEvent]
    async def complete(self, messages) -> str   # non-streaming helper
# LLMEvent = TextDelta | ToolCallDelta(complete tool calls assembled by provider impl) | Done(usage)
```
Each provider INSTANCE serves exactly one model (bound at construction) — there is no
`small` flag/parameter and no "small model" concept anymore; compaction and profile
synthesis just use a normal provider instance for whichever model applies.
- `openai_provider.py`: openai SDK, honors OPENAI_BASE_URL (→ any OpenAI-compatible endpoint;
  when base_url set and no api key, use "not-needed" placeholder). Tools via native
  function-calling.
- `gemini_provider.py`: google-genai SDK, translate tool schemas, same event interface.
- `factory.py`: `resolve_model(model, settings) -> (provider_name, model_id)` — searches
  `settings.openai_models` then `settings.gemini_models` (Gemini only if
  `gemini_api_key` set), falling back to `(provider-of-default, settings.default_model)`
  for None/unknown/unavailable requests. `available_models(settings)` lists the
  composer's model-chip options (ordered, deduped). `get_llm_provider(model, settings)`
  resolves then returns a cached instance, keyed `(provider_name, model_id)` — model
  selection is per-conversation (composer chip), not a per-user override anymore.

## 8. Search provider abstraction (`services/search/`)

`SearchProvider.search(query, max_results) -> list[SearchResult{title,url,snippet}]`
- `duckduckgo.py`: `ddgs` package (free, keyless). Handle rate-limit exceptions with
  backoff + one retry.
- `google_cse.py`: Custom Search JSON API via httpx.
- `tavily.py`: Tavily REST API (its `content` field maps to snippet; include raw_content
  support for fetch shortcut if trivial).
- `factory.py`: `DEFAULT_SEARCH_PROVIDER = "duckduckgo"`; `resolve_search_provider(name,
  settings)` validates against `available_search_providers(settings)` (duckduckgo
  always, google/tavily only when their keys are set), falling back to the default for
  None/unknown/unavailable requests. `get_search_provider(name, settings)` resolves then
  returns a cached instance — selection is per-conversation (composer chip), not a
  per-user override anymore.
