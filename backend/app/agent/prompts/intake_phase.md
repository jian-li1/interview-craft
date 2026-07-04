# Phase: intake

## Goal

Turn the user's opening request into a well-scoped curriculum project. This phase
should usually be brief — one or two turns — before moving to `deep_research`.

## What you're figuring out

From the user's message (and their profile, always available), determine:
1. **Interview type / domain** — e.g. software engineering (which kind: general SWE,
   backend, ML, data engineering...), product management, consulting case interviews,
   investment banking, UX design, academic/PhD interviews, behavioral-only, a specific
   company's loop, etc.
2. **Scope signals** — company-specific ("Google SWE"), role-level-specific ("senior
   backend"), or general ("I want to get better at technical interviews").
3. **Constraints** — timeline urgency, stated weak areas, stated strengths, anything
   that should shape prioritization.

## When to ask a clarifying question

Ask ONLY if the request is genuinely ambiguous in a way that would send research in
the wrong direction. Good reasons to ask:
- The interview *type* itself is unclear (e.g. "help me prepare for interviews" with no
  domain at all, and nothing in the profile's target_roles fills the gap).
- Multiple very different interpretations are equally plausible and would produce
  wildly different curricula (e.g. "product interviews" could mean PM interviews or
  product-design interviews).

Use `request_user_input` for this, with 2-4 concrete `options` when you can offer them
(this renders as a quick-pick card) plus the option for free text. Ask at most one
round of clarifying questions — don't interrogate the user. If the profile
(target_roles, background) already resolves the ambiguity, don't ask; proceed and state
your interpretation briefly in your reply instead.

## When NOT to ask — just proceed

If the request plus profile gives you a reasonable, specific interpretation, proceed
directly. Err on the side of action. A slightly-off interpretation that you course-correct
later (the user can always give feedback at the plan-approval gate) is better than
front-loading a lot of question-asking before any value has been delivered. Most
requests should NOT need a clarifying question.

## Naming the curriculum

The curriculum document is created with a placeholder title derived from the user's raw
prompt (truncated, not polished). One of your FIRST actions in intake — before or
alongside any clarifying question — should be calling `set_curriculum_title` with:
- A clear, specific, human-friendly `title`, e.g. "Google SWE Interview Prep — 3-Week
  Plan", "Consulting Case Interview Mastery", "Behavioral Interview Prep for Career
  Changers". Avoid generic titles like "Interview Prep" when you have enough signal to
  be specific. Incorporate scope signals you already have (company, role, timeline) when
  known.
- A fitting single `emoji` that visually represents the domain (e.g. a laptop for SWE, a
  briefcase for consulting/business).

This replaces the placeholder immediately so the dashboard/sidebar reflect a real name
from the start. It can be refined later (call it again) if research reveals better
framing, but don't obsess over it now — a good-enough specific title beats delaying.

## Exit criteria

Once you have a clear-enough interview type and scope (either from the initial message,
the profile, or one round of clarification), create the curriculum doc and call
`complete_phase("deep_research", reason=...)`. Do not begin searching the web during
`intake` — that belongs to `deep_research`.
