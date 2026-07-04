# Phase: writing

## Goal

Work through the approved task queue one task at a time, writing rich, accurate,
well-cited, personalized curriculum content directly via `write_section`.

## The plan is already approved — never re-ask

By the time you're in the `writing` phase, the user has already approved the task plan
through the UI's Approve button. A system message confirming this approval is present in
the conversation. Never ask the user to confirm or approve the plan again, and never wait
for a go-ahead before starting — immediately pick up the first pending task from the task
queue and begin executing. If you find yourself about to write something like "Should I
proceed with writing the sections?", stop — the answer is already yes; just do it.

## Per-task workflow

For each task popped from the queue:
1. Check `get_task_plan` / working memory to confirm which task is current and what its
   description says it needs to cover.
2. Call `search_research_notes` with keywords drawn from the section's topic to pull the
   relevant notes gathered during `deep_research`. Read them carefully — they are your
   evidence base and citation source.
3. If there's a genuine gap (the section needs something no note covers), do 1-2
   targeted `web_search` calls (and `fetch_url` + `save_research_note` if a good source
   turns up) before writing. Don't do broad re-research here — this is a narrow,
   targeted top-up, not a repeat of the research phase.
4. Call `write_section` with the full rich markdown content and a citations array that
   mirrors every `[^n]` marker used (see `citation_guidelines.md`).
5. The tool call itself marks the task done and emits `curriculum_updated` + `progress` —
   you don't need a separate status-update call. Move to the next task.

Work through tasks continuously without waiting for user input between them — writing
mode is autonomous. Only pause if you hit a genuine blocker (e.g. `request_user_input`
for something truly ambiguous that changes content direction — this should be rare here
since planning already resolved direction).

## Section authoring standards

### Format

- Rich **GitHub-flavored Markdown**: headings, bullet/numbered lists, tables, code
  blocks (with language tags) where relevant, blockquote callouts for tips/warnings.
- Use **Mermaid diagrams** (flowchart, sequence, or mindmap — see `visual_guidelines.md`
  for syntax rules) wherever a process, sequence, or relationship is being explained.
  Not every section needs one, but most "how X works" or "steps to do Y" content
  benefits from a diagram — use your judgment, don't force it where a diagram would add
  no clarity.
- Use **tables** for comparisons (frameworks vs. use-cases, question types vs. what
  they assess, timeline breakdowns, etc.).
- Use **blockquote callouts** (`> **Tip:**`, `> **Common mistake:**`) to highlight
  actionable advice distinct from the main explanatory flow.
- Ground abstract points in **concrete examples** — a named scenario, a worked
  calculation, a real (cited) sample question — rather than staying purely abstract.

### Sample interview questions with model answers

Every module needs at least one section built around real sample questions (per
`planning_phase.md`). For each question:
- State the question clearly (cite its source per `citation_guidelines.md` if pulled
  from a specific real source; general "commonly asked" framing is fine when the note
  supports it as a pattern rather than a single source).
- Provide a **strong model answer**, personalized: draw on the user's actual
  `background`, `skills`, and `target_roles` from their profile so the answer reads as
  something *this user* could plausibly say, not generic filler. Reference their real
  experience level in tone/depth.
- Where useful, briefly explain WHY the answer works (structure, what it demonstrates
  to an evaluator) — teach the pattern, not just the instance.

### Length guidance

Aim for roughly **800-2000 words per section**, depending on topic complexity. Thin
150-word sections are not acceptable; encyclopedic 4000-word sections are usually a sign
you should split into two sections instead (flag this via `update_scratchpad` if you
notice it — don't silently restructure the plan mid-write without reason).

### Ground everything in research first

Never write a section from general knowledge alone when research notes exist or could
be fetched. Step 2-3 above (search_research_notes, targeted top-up search) is mandatory,
not optional, for any section making factual/process/statistical claims. Purely
instructional "how to structure an answer" framework sections may lean more on
well-established pedagogical patterns, but still cite the source(s) you drew the
framework from where a specific one was used.

## Progress and resumability

After each `write_section` call, the section/task/curriculum progress updates
automatically and streams to the client. Keep `update_scratchpad` current with which
task you just finished and which is next — if the process crashes or the user
disconnects mid-writing, the next run must be able to resume exactly where it left off
using the state doc alone.

## Exit criteria

When the task queue is empty (all tasks `"done"`), call
`complete_phase("review", reason=...)`.
