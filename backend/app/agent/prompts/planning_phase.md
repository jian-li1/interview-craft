# Phase: outline_planning

## Goal

Synthesize the research notes gathered in `deep_research` into a curriculum outline
(modules → sections) and a matching task plan, personalized to the user's profile, then
propose it to the user via the `propose_task_plan` HITL gate.

## Outline design principles

### The beginner → interview-ready arc

Structure the curriculum so a learner starting from the user's actual current level (per
their profile's `experience_level`) ends up genuinely interview-ready. A good arc
typically moves through, in order:
1. **Foundations** — orientation to the interview type/format, core vocabulary and
   mental models, what evaluators actually look for.
2. **Core skills** — the substantive knowledge/technique the domain requires (technical
   fundamentals, frameworks, methodologies — whatever `research_phase` area (b) surfaced).
3. **Question drills** — organized practice by question category/topic, each with real
   sample questions and strong model answers.
4. **Mock interview & strategy** — full-loop simulation guidance, timing/pacing
   strategy, common pitfalls, last-mile checklist, follow-up etiquette.

Adjust proportions to the user's profile: a senior candidate needs less foundations and
more nuanced strategy; a student/entry-level candidate needs more foundational scaffolding.
Respect `timeline` — a tight timeline should trim breadth and front-load the
highest-leverage modules, not just compress every module equally.

### Module sequencing

- Typically **4-8 modules**, each with **3-6 sections**.
- Each module should have a clear, single-sentence objective and 2-4 concrete
  `objectives` (learnable outcomes, not just topics).
- Every module must include at least one section dedicated to **sample questions with
  model answers** relevant to that module's topic — don't push all Q&A into a single
  "questions" module; distribute it so practice is interleaved with learning.
- Order sections within a module from conceptual → applied → practiced.

### Sizing guidance

Estimate `estimated_minutes` per module realistically (how long a focused learner would
spend), typically 30-90 minutes per module depending on depth. Use this to sanity-check
scope against the user's stated timeline.

## Task plan format

Each task in `propose_task_plan`'s `tasks` list should map to roughly one section (or,
for the initial overview, one task for `write_curriculum_overview`). Fields:
- `id`: short stable slug (e.g. `m1-s2`), unique within the plan.
- `title`: matches the section title.
- `description`: 1-2 sentences telling future-you (the writing phase) what this task
  needs to cover — specific enough that picking it up cold is easy.
- `module_ref`: the module id/slug this task belongs to (null for whole-curriculum tasks
  like the overview).
- `status`: `"pending"` for all tasks at proposal time.

The `outline_markdown` should be a clean, human-readable rendering of the same structure
(module titles + summaries + section titles) — this is what's shown to the user in the
approval card, so make it scannable and inviting, not just a dry list.

## Calling propose_task_plan

This call is a HITL gate: it saves the plan, sets curriculum status to
`awaiting_approval`, emits `plan_proposed`, and pauses your loop. Call it alone (no other
tool calls in the same batch). After calling it, write a short, friendly chat message
introducing the proposed outline at a high level and inviting the user to approve or
request changes — don't repeat the entire outline in chat since it renders in the UI
panel already.

## Incorporating `modify` feedback on revision

If the user chooses `modify`, you'll be re-entered into `outline_planning` with
accumulated `user_feedback` entries visible in the plan/working memory. Before proposing
again:
- Read ALL feedback entries, not just the latest.
- Make targeted changes that address the feedback — don't regenerate the whole outline
  from scratch unless the feedback effectively asks for that.
- Increment the plan version (handled by `propose_task_plan` automatically via the tool
  implementation — just call it again with the revised outline/tasks).
- If feedback implies a research gap (e.g. "I also want AWS-specific system design
  content" and you have no notes on that), do a couple of targeted `web_search` +
  `save_research_note` calls before re-proposing, rather than fabricating content to
  match the request.

## Exit criteria

This phase ends when the user approves the plan (handled by the orchestrator, which
transitions to `writing` and materializes module/section stubs) — you do not call
`complete_phase` yourself for the approve path. You only actively loop within this phase
when revising after a `modify` decision.
