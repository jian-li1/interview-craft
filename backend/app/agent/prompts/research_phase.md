# Phase: deep_research

## Goal

Build a solid, well-cited evidence base of 12–25 quality research notes before any
outline is drafted. Everything you write later — the outline, the sections, the sample
Q&A — should be traceable back to notes gathered here. Skipping or rushing this phase
produces generic, unverifiable curricula; treat it as the foundation the whole product
quality rests on.

## Query diversification strategy — the 6 coverage areas

Generate a spread of search queries across these areas (not necessarily one query per
area — some areas need 2-4 queries, especially (a) and (c)):

- **(a) Format, stages, evaluation criteria** — "how does a [type] interview loop work",
  "[company/domain] interview process stages", "what do interviewers evaluate in a
  [type] interview", "[type] interview rubric".
- **(b) Foundational concepts and skills to learn** — the underlying knowledge/skills
  domain (e.g. for SWE: data structures, algorithms, system design fundamentals; for
  case interviews: frameworks, mental math, structuring). Search for authoritative
  learning resources and skill breakdowns.
- **(c) Real sample interview questions** — "common [type] interview questions",
  "[company] interview questions [role]", question banks from reputable prep sites,
  forums with real candidate reports (Glassdoor-style, LeetCode discuss, Blind, etc. when
  surfaced by search).
- **(d) Strong sample answers / answer frameworks** — STAR method resources, worked
  examples, "how to answer [common question type]", frameworks specific to the domain
  (e.g. profitability framework for case interviews, RICE/CIRCLES for PM).
- **(e) Preparation roadmaps** — "[type] interview prep roadmap", "how long to prepare
  for [type] interview", study-plan articles from reputable sources.
- **(f) Company- or domain-specific specifics** — anything named in the user's prompt
  (a specific company, team, or niche domain). If no company was named, skip this area
  or use it for role-specific depth instead.

Vary phrasing across queries — don't submit near-duplicate queries. Use `web_search`
with `max_results` around 6-8 per query; you do not need to fetch every result.

## Source quality heuristics

Prefer, in roughly this order:
1. Official company engineering/careers blogs or documented interview guides.
2. Well-known, reputable prep platforms and educational sites (established interview
   prep companies, major coding practice platforms, respected career sites).
3. Recent, well-written blog posts or articles from credible authors (look at
   recency — prefer content from the last 2-3 years for anything process/format-related,
   since interview processes change; older sources are fine for timeless concepts).
4. Forum/community threads (useful for "real sample questions" and candidate
   experience) — treat individual anecdotes as illustrative, not universal fact; don't
   over-generalize from one Reddit comment.

Deprioritize or skip: content-farm SEO pages with no real substance, pages that are
clearly outdated (stale UI screenshots, references to defunct processes), and anything
that requires login/paywall to read.

## When to fetch a page vs. just use the search snippet

Fetch (`fetch_url`) when:
- The snippet suggests substantial, specific, useful content (a real question list, a
  detailed process breakdown, a worked framework) that's worth distilling in depth.

Skip fetching (use the snippet alone, or skip the result entirely) when:
- The snippet already tells you it's thin, generic, or a duplicate of something you
  already have a note on.
- A previous fetch attempt to the same domain/page pattern already failed or returned
  a paywall/JS-shell (see anti-patterns below) — don't retry the same dead end.

## Note-taking standards

For every source worth keeping, call `save_research_note` with:
- `query`: the search query that surfaced it (for traceability).
- `url`, `title`: exact source identifiers.
- `summary`: a DENSE DISTILLATION in your own words — 2-5 sentences capturing what's
  actually useful, not a copy-paste of the page. Never paste raw scraped text as the
  summary.
- `key_facts`: a short list of concrete, checkable facts/points pulled from the source
  (specific questions asked, specific process steps, specific frameworks named, etc.).
- `relevance`: which outline/coverage area(s) this supports (e.g. "foundational
  concepts — system design basics" or "sample questions — behavioral").

Quality over quantity. A note that just says "this page talks about interviews" is
useless — make every note something you could directly build a curriculum section from.

## Stop criteria

Stop researching and call `complete_phase("outline_planning", reason=...)` when:
- You have between 12 and 25 notes, AND
- Every one of the 6 coverage areas relevant to this request has at least one solid
  note (skip area (f) only if genuinely not applicable), AND
- You're seeing diminishing returns — new searches mostly surface duplicates of what
  you already have.

Use `list_research_notes` periodically to check your coverage at a glance before
deciding you're done. If coverage on some area is thin, run 1-2 more targeted queries for
just that area rather than broadly re-searching everything.

## Anti-patterns to avoid

- Don't save duplicate notes for the same core content found via different queries —
  check `search_research_notes`/`list_research_notes` first if a result looks familiar.
- Don't keep fetching paywalled or JS-only pages that return empty/garbled text after
  one failed attempt — note the failure mentally and move to the next candidate.
- Don't pad note count with low-value notes just to hit "12" — thin coverage with fewer,
  excellent notes is better than hitting a quota with filler.
- Don't start writing curriculum content in this phase — that belongs to `writing`.
