# InterviewCraft — Agentic System Specification (THE CORE)

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
                                     ▲                    │ (modify + feedback)
                                     └────────────────────┘
```

- **intake**: Understand the user's request; read user profile memory; ask clarifying
  questions ONLY if the request is genuinely ambiguous (interview type unclear). Create the
  curriculum doc (status=researching) and transition.
- **deep_research**: Multi-query web research. The agent generates diverse search queries
  covering: (a) the interview type's format/stages/evaluation criteria, (b) foundational
  concepts and skills to learn, (c) REAL sample interview questions commonly asked,
  (d) strong sample answers / answer frameworks, (e) preparation roadmaps, (f) company- or
  domain-specific specifics from the user prompt. Search snippets are used ONLY for
  relevance triage (deciding what to fetch or skip); fetching (`fetch_url`) is mandatory
  for every source kept — the agent distills findings into **research notes** (tool:
  save_research_note) from the fetched full text, never from a snippet alone (the sole
  exception: a fetch fails, in which case the source is skipped entirely rather than
  noted from its snippet). There is no note-count target, upper or lower — the agent
  keeps researching, purely qualitatively, until every relevant coverage area has solid
  fetched-and-distilled notes and new searches hit diminishing returns. Every note keeps
  its source URL — this feeds citations later.
- **outline_planning**: Synthesize research notes into a curriculum outline (modules →
  sections) + a task plan — EXACTLY one task per planned section (never an overview
  task; the overview is written later in `review` via `write_curriculum_overview`).
  Personalize using the synthesized user profile. Call `propose_task_plan` → the tool
  first validates the plan server-side (task id format `m{X}-s{Y}`, `module_ref`
  prefix match, contiguous module/section numbering, and that `outline_markdown`'s
  `Section X.Y` labels match `tasks` 1:1) and returns an error observation with no
  writes performed on any violation. On success it emits `phase_change`
  (awaiting_approval), `progress` (task counts, if any tasks), and `plan_proposed` WS
  events (in that order), sets curriculum status=awaiting_approval and persists the
  progress blob, and **pauses the loop**.
- **awaiting_approval (HITL)**: Resumes on `plan_decision`. approve → materialize modules/
  sections stubs in Firestore (section doc id = task id minus its `m{X}-` module
  prefix, e.g. task `m1-s2` → section doc `s2` under module doc `m1`; legacy task ids
  without that prefix fall back to using the full id verbatim), status=writing, go to
  writing, emit live `phase_change` (writing) + `progress` WS events. modify → feedback
  appended, return to outline_planning to revise (increment plan version), emit a live
  `phase_change` (outline_planning) WS event.
- **writing**: Pop tasks from the queue one at a time. For each: search research notes for
  relevant material (`search_research_notes`), optionally do 1–2 targeted extra searches if
  a gap exists, then `write_section` with full rich markdown. `write_section` enforces a
  target guard first: in `writing`/`review` it only accepts module/section ids already
  materialized from the approved plan, rejecting any invented id with an error listing the
  existing ids. Update progress after each task (WS `progress` + `curriculum_updated`).
  Persist task status so a crashed/resumed run continues where it left off.
  `complete_phase("review")` is rejected while any plan task is still pending or any
  section doc is still `"planned"`.
- **review**: Curriculum status=reviewing. Verify every section has citations, diagrams
  where valuable, sample Q&A coverage; write the curriculum `overview`; then
  status=ready. `complete_phase("ready")` is
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
  completions (the DeepSeek/llama.cpp/vLLM convention; `reasoning` is read as a fallback for
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
  modify → a message stating the user's feedback text and instructing the model to revise
  and re-propose via `propose_task_plan`. Both branches also emit a live `phase_change`
  WS event (approve → `writing`, plus a `progress` event; modify → `outline_planning`) so
  the client's phase banner updates immediately rather than only on the next reconnect.

## 4. Tool catalog (`agent/tools/`)

Each tool = a class/module with: `name`, `description` (thorough, written for the LLM),
pydantic input model (→ JSON schema for the provider), async `execute(input, ctx)`.
A `ToolRegistry` exposes provider-formatted specs filtered by phase (research tools hidden
during writing-only refinements, etc. — keep filtering simple: a phase→allowed-tools map).

**Research tools**
- `web_search(query, max_results=8)` → list of {title, url, snippet} via search provider.
- `fetch_url(url)` → cleaned page text (httpx + readability-style extraction, full page returned untruncated with no byte cap; strip scripts; handle errors/timeouts gracefully; block private/internal IPs — SSRF guard).
- `save_research_note(query, url, title, summary, key_facts[], relevance)` → note id. Summary must be a dense distillation, not raw copy.
- `search_research_notes(keywords)` → ranked matching notes (simple keyword/substring scoring over summary+key_facts+relevance is fine).
- `list_research_notes()` → compact listing (id, title, url, relevance) for orientation.

**User-memory tools**
- `get_user_profile()` → synthesized_profile + structured fields (target roles, experience level, learning style, timeline).

**Planning tools**
- `propose_task_plan(outline_markdown, tasks[])` → HITL GATE: validates the plan first (task id `m{X}-s{Y}`, `module_ref` prefix match, contiguous module/section numbering, `outline_markdown`'s `Section X.Y` labels matching `tasks` 1:1) — error observation, no writes, if invalid; on success saves plan, sets status awaiting_approval, emits `phase_change` + `progress` + `plan_proposed`, pauses loop.
- `get_task_plan()` → current plan + task statuses.

**Curriculum tools**
- `list_curriculum_structure()` → modules/sections tree with statuses (compact).
- `write_section(module_id, section_id, title, content_markdown, citations[])` → target guard first: in `writing`/`review`, module_id/section_id must already exist (materialized from the approved plan) or the write is rejected with an error listing existing ids; in `ready`/`refinement`, a new module/section may be created but only at the next sequential id (`m{N+1}`/`s{K+1}`, auto-creating the module doc when applicable), otherwise rejected. Then validates citations non-empty for research-based content; syntax-lints any ```mermaid blocks and rejects the write with an error observation (no write performed) if a diagram is broken; marks task done (matching `module_id-section_id` or, for legacy docs, the section id alone); emits `curriculum_updated` + `progress`; also refreshes the parent module's derived status (planned→writing→complete, from its sections) and estimated_minutes (~200 wpm from written content).
- `read_section(module_id, section_id)` → full content (for explanation/refinement).
- `update_section(module_id, section_id, content_markdown, citations[], change_note)` → for refinement phase; also syntax-lints ```mermaid blocks and rejects with an error observation (no write) if broken; also refreshes the parent module's derived status/estimated_minutes.
- `write_curriculum_overview(overview_markdown, emoji, tags[])` → sets curriculum overview/metadata.
- `set_curriculum_title(title, emoji?)` → renames the curriculum (and the linked
  conversation's sidebar/dashboard title) away from the placeholder derived from the raw
  user prompt. Always available (not phase-restricted); the agent is instructed to call
  this as one of its first actions in `intake`. Emits `curriculum_updated` (scope
  `curriculum`), same shape as `write_curriculum_overview`'s event, so the frontend
  refetch path is unchanged.
- `set_module_status / internal helpers` as needed; emits `curriculum_updated` (scope `module`).

**Control tools**
- `request_user_input(question, options[]?)` → HITL gate for clarifying questions (pauses loop, question rendered as chat card).
- `update_scratchpad(content)` → overwrite agent scratchpad in state doc (agent's own working notes: what's done, what's next, open questions).
- `complete_phase(next_phase, reason)` → validated transition; updates state + curriculum status; emits `phase_change`. Two transitions carry an additional completeness gate (error observation, no transition applied, if unmet): `writing`→`review` requires every module_ref-bearing plan task `"done"` and no section doc left `"planned"`; `review`→`ready` requires every section `"complete"` and the curriculum `overview` non-empty.

## 5. Memory & context management (`agent/memory/`)

**Layered memory**, assembled by `MemoryManager.build_context()` on every iteration:

1. **Static system prompt**: base_system.md + current phase instruction file + citation +
   visual guidelines (see §6).
2. **User memory**: synthesized profile (injected as a system block: "About the user: ...").
3. **Working memory**: agent state doc — phase, task queue with statuses, scratchpad,
   plan version. Injected as a compact system block each turn (always fresh, never stale).
4. **Episodic memory**: conversation summary (if compaction has run) + recent messages +
   tool exchanges verbatim.
5. **Research memory**: NOT injected wholesale — accessed on demand via
   search_research_notes/list_research_notes tools. This keeps context lean.

**Auto-compaction** (`memory/compaction.py`):
- Track token estimate with tiktoken (fallback: chars/4) over the assembled context.
- When estimate > 0.8 × CONTEXT_TOKEN_LIMIT: take the older ~60% of messages, run the
  **small model** with `prompts/compaction.md` to produce a structured summary (key
  decisions, user preferences expressed, curriculum state, unresolved items), merge into
  `conversations/{id}.summary`, set `compacted_through`, and rebuild context as
  [system blocks] + [summary block] + [remaining recent messages]. Emit WS `compaction`.
- The model is replayed each tool call's full `output_full`; only outputs older than the
  last 6 exchanges are truncated to short previews in the rebuilt context (full data also
  lives in Firestore research notes / sections, retrievable via tools).

## 6. Prompt files (`agent/prompts/*.md`) — write these THOROUGHLY

These are loaded from disk (cached) and composed per phase. Each must be a genuinely
detailed, high-quality instruction document (not a stub). Required files:

- `base_system.md` — Identity ("InterviewCraft Agent"), mission, ReAct behavioral rules
  (reason internally first (native reasoning): assess state → decide next action; one
  coherent batch of tool calls per step; adapt on tool errors), tone, honesty about sources,
  personalization mandate (always ground advice in the user profile), safety rules
  (no fabricated citations — every factual claim traceable to a research note).
- `research_phase.md` — Deep-research methodology: query diversification strategy (the 6
  coverage areas in §2), source quality heuristics (prefer official docs, well-known prep
  sites, recent content), fetching is MANDATORY for every kept source (snippets are for
  relevance triage only — never write a note from a snippet alone; the only exception is
  a failed fetch, which means skip the source), note-taking standards (summary is a long,
  comprehensive, multi-paragraph distillation of the fetched full text — roughly
  150–500+ words for a substantial source, enough that the writing phase never needs to
  re-fetch), stop criteria (purely qualitative coverage checklist + diminishing returns,
  no numeric note-count target), anti-patterns (don't save duplicate notes, don't fetch
  paywalled/JS-only pages repeatedly, don't pad or artificially cap note count).
- `planning_phase.md` — Outline design principles: beginner→interview-ready arc,
  module sequencing (foundations → core skills → question drills → mock/strategy),
  every module must include sample-questions-with-model-answers sections, no fixed
  module/section count limit (scope driven by researched material and user goals, with
  timeline respected via priority ordering rather than capping count), task plan format,
  how to incorporate `modify` feedback on revision.
- `writing_phase.md` — Section authoring standards: rich GitHub-flavored Markdown; use
  Mermaid diagrams (flowchart/sequence/mindmap) wherever a process/relationship is
  explained; tables for comparisons; callout blockquotes; concrete examples; sample
  interview questions with STRONG model answers personalized to the user's background
  (use their actual experience level/target roles); inline citation markers `[^n]`
  with a footnote list matching the citations array; length guidance (800–2000 words/section);
  ground every section in research notes retrieved first.
- `review_phase.md` — Structured quality pass over the whole draft curriculum: a
  per-section checklist (citations, diagrams, sample-Q&A coverage, 800-2000 word length,
  coherence); fix failures directly via `write_section` overwrite (never a fragment);
  `search_research_notes` against the existing note base only (no broad re-research);
  after all modules pass, `write_curriculum_overview`; exit via `complete_phase("ready")`.
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
- `profile_synthesis.md` — (Used by onboarding synthesize endpoint, small model) Transform
  raw bio/background/resume text into a dense 200–350 word third-person profile: background,
  strengths, gaps relative to target roles, learning style, personalization hooks.
- `compaction.md` — (Small model) Summarization contract: preserve decisions, user
  preferences/corrections, curriculum/plan state, open threads; drop pleasantries and
  superseded tool details; output structured markdown under fixed headings.

## 7. LLM provider abstraction (`services/llm/`)

```python
class LLMProvider(Protocol):
    async def chat_stream(self, messages, tools=None, small=False) -> AsyncIterator[LLMEvent]
    async def complete(self, messages, small=False) -> str   # non-streaming helper
# LLMEvent = TextDelta | ToolCallDelta(complete tool calls assembled by provider impl) | Done(usage)
```
- `openai_provider.py`: openai SDK, honors OPENAI_BASE_URL (→ llama.cpp compatibility;
  when base_url set and no api key, use "not-needed" placeholder). Tools via native
  function-calling. `small=True` → OPENAI_SMALL_MODEL.
- `gemini_provider.py`: google-genai SDK, translate tool schemas, same event interface.
- `factory.py`: returns provider from settings; per-user override from user settings allowed.

## 8. Search provider abstraction (`services/search/`)

`SearchProvider.search(query, max_results) -> list[SearchResult{title,url,snippet}]`
- `duckduckgo.py`: `ddgs` package (free, keyless). Handle rate-limit exceptions with
  backoff + one retry.
- `google_cse.py`: Custom Search JSON API via httpx.
- `tavily.py`: Tavily REST API (its `content` field maps to snippet; include raw_content
  support for fetch shortcut if trivial).
- `factory.py` per settings, per-user override allowed.
