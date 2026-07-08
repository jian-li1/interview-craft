# Phase: review

## Goal

Every planned section has been written — the draft is complete. Your job now is a
structured quality pass over the entire curriculum, fixing real problems directly, then
publishing it: write the curriculum overview and transition to `ready`.

## Review workflow

1. Call `list_curriculum_structure` to see every module and section with statuses.
2. Walk the curriculum module by module. For each section, call `read_section` and check
   it against the checklist below. Actually read the content — do not rubber-stamp.
3. Fix failures immediately by rewriting the section with `write_section` (the same
   module_id/section_id overwrites in place). `write_section` replaces the whole section —
   always pass the full corrected markdown and the complete citations array, never a
   fragment. If a fix needs source material, your "Saved research sources"
   working-memory block lists every saved source with your summary of it — call
   `fetch_url` on the relevant saved URL to pull its full content back before rewriting.
4. Keep `update_scratchpad` current with which modules you have already reviewed, so a
   crashed or resumed run can continue where it left off instead of re-reviewing.
5. After all modules pass, call `write_curriculum_overview` with a compelling overview of
   the whole curriculum (what it covers, how it is personalized to this user, how to work
   through it).
6. Call `complete_phase("ready", reason=...)`, then tell the user in one short message
   that the curriculum is complete and they can ask for refinements, explanations, or
   additions from here on.

## Review checklist (per section)

- **Citations**: every non-obvious factual claim carries a `[^n]` marker; the footnote
  list and the citations array mirror each other; no fabricated or dead-looking URLs
  (see `citation_guidelines.md`).
- **Visuals**: processes, sequences, and relationships are diagrammed where a diagram
  genuinely adds clarity (see `visual_guidelines.md`); Mermaid syntax follows the
  guardrails so diagrams actually render.
- **Sample Q&A coverage**: every module has at least one section with real sample
  questions and strong model answers personalized to the user's background and target
  roles — not generic filler.
- **Substance and length**: roughly 800-2000 words of genuinely instructive content; no
  thin stubs, placeholders, or sections that merely restate their own heading.
- **Coherence**: the section fits its module's arc and doesn't contradict or needlessly
  duplicate neighboring sections.
- **Module status**: after reviewing a module, if its displayed status is stale, correct
  it with `set_module_status`.

## Scope discipline

This is a verification pass, not a second writing phase. Only rewrite sections that
actually fail the checklist; leave passing sections untouched. No new research — the
saved sources in your working memory are your entire source pool here; you may
`fetch_url` a saved URL to re-read it, but don't hunt for new sources (that belonged in
`writing`, and can happen again in `refinement` if the user asks).

## Exit criteria

All sections pass the checklist, module statuses are accurate, and the curriculum
overview has been written. Then — and only then — call `complete_phase("ready", reason=...)`.
This is validated server-side: the call is rejected if any section isn't `"complete"` or
the overview is still empty — finish those first rather than calling it speculatively.
