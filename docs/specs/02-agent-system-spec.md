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
  domain-specific specifics from the user prompt. For promising results it fetches pages and
  distills findings into **research notes** (tool: save_research_note). Target 12–25 quality
  notes. Every note keeps its source URL — this feeds citations later.
- **outline_planning**: Synthesize research notes into a curriculum outline (modules →
  sections) + a task plan (one task ≈ one section or overview). Personalize using the
  synthesized user profile. Call `propose_task_plan` → emits `plan_proposed` WS event,
  sets curriculum status=awaiting_approval, and **pauses the loop**.
- **awaiting_approval (HITL)**: Resumes on `plan_decision`. approve → materialize modules/
  sections stubs in Firestore, status=writing, go to writing. modify → feedback appended,
  return to outline_planning to revise (increment plan version).
- **writing**: Pop tasks from the queue one at a time. For each: search research notes for
  relevant material (`search_research_notes`), optionally do 1–2 targeted extra searches if
  a gap exists, then `write_section` with full rich markdown. Update progress after each
  task (WS `progress` + `curriculum_updated`). Persist task status so a crashed/resumed run
  continues where it left off.
- **review**: Verify every section has citations, diagrams where valuable, sample Q&A
  coverage; write the curriculum `overview`; status=ready.
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
                emit tool_call_result (preview truncated to ~1500 chars)
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
  For OpenAI, reasoning is simulated via a convention: the system prompt instructs the model
  to put its planning/thinking in a `<thinking>...</thinking>` block at the start of each
  response; the stream parser routes text inside the block to `reasoning_delta` and the rest
  to `text_delta`. (Works identically for Gemini and llama.cpp — provider-agnostic.)
- **Cancellation**: `stop` frame sets a cancel event checked between iterations and during
  streaming; persist state before exiting so the run is resumable.
- **Tool errors never crash the loop**: return `{"error": "..."}` as the observation so the
  agent can adapt (retry different query, skip source, etc.).
- Concurrency guard: one active run per conversation (asyncio lock keyed by conv id).

## 4. Tool catalog (`agent/tools/`)

Each tool = a class/module with: `name`, `description` (thorough, written for the LLM),
pydantic input model (→ JSON schema for the provider), async `execute(input, ctx)`.
A `ToolRegistry` exposes provider-formatted specs filtered by phase (research tools hidden
during writing-only refinements, etc. — keep filtering simple: a phase→allowed-tools map).

**Research tools**
- `web_search(query, max_results=8)` → list of {title, url, snippet} via search provider.
- `fetch_url(url)` → cleaned page text (httpx + readability-style extraction, truncate ~8k tokens; strip scripts; handle errors/timeouts gracefully; block private/internal IPs — SSRF guard).
- `save_research_note(query, url, title, summary, key_facts[], relevance)` → note id. Summary must be a dense distillation, not raw copy.
- `search_research_notes(keywords)` → ranked matching notes (simple keyword/substring scoring over summary+key_facts+relevance is fine).
- `list_research_notes()` → compact listing (id, title, url, relevance) for orientation.

**User-memory tools**
- `get_user_profile()` → synthesized_profile + structured fields (target roles, experience level, learning style, timeline).

**Planning tools**
- `propose_task_plan(outline_markdown, tasks[])` → HITL GATE: saves plan, sets status awaiting_approval, emits `plan_proposed`, pauses loop.
- `get_task_plan()` → current plan + task statuses.

**Curriculum tools**
- `list_curriculum_structure()` → modules/sections tree with statuses (compact).
- `write_section(module_id, section_id, title, content_markdown, citations[])` → writes content; validates citations non-empty for research-based content; marks task done; emits `curriculum_updated` + `progress`.
- `read_section(module_id, section_id)` → full content (for explanation/refinement).
- `update_section(module_id, section_id, content_markdown, citations[], change_note)` → for refinement phase.
- `write_curriculum_overview(overview_markdown, emoji, tags[])` → sets curriculum overview/metadata.
- `set_module_status / internal helpers` as needed.

**Control tools**
- `request_user_input(question, options[]?)` → HITL gate for clarifying questions (pauses loop, question rendered as chat card).
- `update_scratchpad(content)` → overwrite agent scratchpad in state doc (agent's own working notes: what's done, what's next, open questions).
- `complete_phase(next_phase, reason)` → validated transition; updates state + curriculum status; emits `phase_change`.

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
- Tool outputs older than the last 6 exchanges are also truncated to short previews in the
  rebuilt context (full data lives in Firestore research notes / sections anyway).

## 6. Prompt files (`agent/prompts/*.md`) — write these THOROUGHLY

These are loaded from disk (cached) and composed per phase. Each must be a genuinely
detailed, high-quality instruction document (not a stub). Required files:

- `base_system.md` — Identity ("InterviewCraft Agent"), mission, ReAct behavioral rules
  (think in `<thinking>` block first: assess state → decide next action; one coherent
  batch of tool calls per step; adapt on tool errors), tone, honesty about sources,
  personalization mandate (always ground advice in the user profile), safety rules
  (no fabricated citations — every factual claim traceable to a research note).
- `research_phase.md` — Deep-research methodology: query diversification strategy (the 6
  coverage areas in §2), source quality heuristics (prefer official docs, well-known prep
  sites, recent content), when to fetch vs. skip, note-taking standards, stop criteria
  (coverage checklist met, 12–25 notes), anti-patterns (don't save duplicate notes,
  don't fetch paywalled/JS-only pages repeatedly).
- `planning_phase.md` — Outline design principles: beginner→interview-ready arc,
  module sequencing (foundations → core skills → question drills → mock/strategy),
  every module must include sample-questions-with-model-answers sections, sizing guidance
  (typically 4–8 modules × 3–6 sections), task plan format, how to incorporate `modify`
  feedback on revision.
- `writing_phase.md` — Section authoring standards: rich GitHub-flavored Markdown; use
  Mermaid diagrams (flowchart/sequence/mindmap) wherever a process/relationship is
  explained; tables for comparisons; callout blockquotes; concrete examples; sample
  interview questions with STRONG model answers personalized to the user's background
  (use their actual experience level/target roles); inline citation markers `[^n]`
  with a footnote list matching the citations array; length guidance (800–2000 words/section);
  ground every section in research notes retrieved first.
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
