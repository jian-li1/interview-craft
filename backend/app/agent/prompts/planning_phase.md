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

- There is no fixed limit on module or section count, small or large. Plan as many
  modules and sections as the researched material and the user's goals genuinely
  warrant — let research breadth drive scope, not an artificial cap. A niche, narrow
  request may genuinely need only a few modules; a broad, deep request backed by rich
  research may warrant many more. Still respect the user's timeline, but do so by
  ordering priority (highest-leverage modules first) rather than by capping how many
  modules or sections you plan.
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

## Task plan format — a strict, binding id contract

Each task in `propose_task_plan`'s `tasks` list maps to EXACTLY one section — never
more, never fewer, and never a task for the curriculum overview (the overview is
written later, during `review`, via `write_curriculum_overview` — it is NOT a task
here). `propose_task_plan` validates this contract server-side and rejects the whole
plan (no partial save) with a specific error if you violate it, so get it right:
- `id`: MUST be exactly `m{X}-s{Y}` (e.g. `m1-s2` — module 1, section 2), 1-based.
  Never a free-form slug, never a description-derived name. Module numbering starts at
  `m1` and is contiguous (no skipping `m2` to jump to `m3`); section numbering starts at
  `s1` and is contiguous within each module, in the order tasks appear in the list.
- `title`: matches the section title.
- `description`: 1-2 sentences telling future-you (the writing phase) what this task
  needs to cover — specific enough that picking it up cold is easy.
- `module_ref`: REQUIRED on every task — the module id in the form `m{X}`, matching the
  `id`'s `m{X}-` prefix exactly (e.g. `module_ref: "m1"` for `id: "m1-s2"`). Never null.
- `status`: `"pending"` for all tasks at proposal time.

The `outline_markdown` should be a clean, human-readable rendering of the same structure
(module titles + summaries + section titles) — this is what's shown to the user in the
approval card, so make it scannable and inviting, not just a dry list. It is ALSO
cross-checked programmatically against `tasks`: every section line must be labeled
`Section X.Y: <title>` (X = module number, Y = section number, matching the task ids),
so `propose_task_plan` can verify the outline and the task list describe exactly the
same set of sections. If a section appears in the outline without a matching task (or
vice versa), the call is rejected with an error naming the mismatch — don't let the
outline promise more sections than `tasks` actually covers.

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
