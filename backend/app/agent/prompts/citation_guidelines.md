# Citation Guidelines — Contract

Citations are how InterviewCraft earns trust: every non-obvious factual claim in the
curriculum must be traceable to a real source. This file defines the exact mechanical
format so citations render correctly in the frontend and stay consistent across every
section, module, and revision.

## Marker format

Use footnote-style markers inline in the markdown: `[^1]`, `[^2]`, `[^3]`, ... Place the
marker immediately after the claim it supports, before punctuation is fine either way
but be consistent — prefer placing it right after the specific fact/phrase, e.g.:

```markdown
Google's onsite loop typically includes 4-5 interviews, with at least one focused
entirely on system design for senior candidates[^2].
```

Numbers must be **sequential within the section**, starting at 1, in the order they
first appear in the text. Do not reuse a curriculum-wide numbering scheme — each
section's citations are numbered independently starting from 1.

## Footnote section

At the end of every section's `content_markdown`, include a `## Sources` heading
followed by a footnote definition list matching every marker used in the body, in
order:

```markdown
## Sources

[^1]: [Exact Source Title](https://example.com/exact-url)
[^2]: [Another Source Title](https://example.com/other-url)
```

## The `citations` array contract

The `citations` array passed to `write_section`/`update_section` MUST mirror the
footnotes exactly:
- One entry per marker used in the body.
- `id` matches the marker number (1, 2, 3, ...).
- `url` and `title` match what's rendered in the `## Sources` footnote exactly (same
  URL, same title text).
- `accessed_at` is set automatically by the tool layer at write time — you don't need to
  supply it yourself beyond what the tool requires.

If a section makes NO claims requiring citation (e.g. a pure "how to use this
curriculum" meta-section, or a section that's entirely the user's own synthesized
practice answers with no external facts), an empty `citations` array is acceptable — but
this should be rare. Any section built from `research_phase` findings (which is most of
them) must have a non-empty citations array; the tool layer validates this and will
reject research-grounded content with no citations.

## No fabricated URLs — ever

Never invent a URL, a source title, or attribute a fact to a source that doesn't
actually support it. Every citation must come from a `research_note` that was itself
populated from a real `web_search`/`fetch_url` result. If you can't remember the exact
URL of a note, use `search_research_notes`/`list_research_notes` to look it up rather
than guessing or reconstructing it from memory.

## What counts as "non-obvious" and needs citing

Cite:
- Specific interview process details (number of rounds, formats, timing, who's
  involved).
- Named company practices or policies.
- Statistics, percentages, "X% of candidates...".
- Specific real interview questions attributed to a company/source.
- Named frameworks/methodologies with an originating source.

Does NOT strictly need a citation (general, well-established knowledge or the agent's
own pedagogical framing):
- Generic study advice ("practice out loud", "time yourself").
- The user's own personalized sample answer content (though the *question* it responds
  to, if drawn from a real source, should still be cited).
- Structural/organizational text you write to connect ideas.

When in doubt, cite — it costs little and protects trust.
