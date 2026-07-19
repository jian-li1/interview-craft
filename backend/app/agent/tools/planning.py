"""Planning tools: propose_task_plan (HITL gate) and get_task_plan."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.tools.base import AgentContext, Tool
from app.agent.tools.control import PHASE_LABELS
from app.services import firestore as fs

# Binding ID contract (see CLAUDE.md / spec 02): a task id is "m{X}-s{Y}" (X,Y >= 1),
# module_ref is "m{X}" matching the id's prefix. These anchor the format checks in
# `_validate_plan` below.
_MODULE_REF_RE = re.compile(r"^m[1-9]\d*$")
_TASK_ID_RE = re.compile(r"^(m[1-9]\d*)-s([1-9]\d*)$")
# Cross-checks outline_markdown against tasks: every planned section must be labeled
# "Section X.Y: <title>" so propose_task_plan can verify 1:1 coverage against tasks.
_OUTLINE_SECTION_RE = re.compile(r"[Ss]ection\s+(\d+)\.(\d+)")


class PlanTaskInput(BaseModel):
    """A single task within a proposed task plan, corresponding to one section stub."""

    id: str = Field(
        ...,
        description=(
            "Task id in the form 'm{X}-s{Y}' (e.g. 'm1-s2'), unique within the plan. X/Y are "
            "1-based and must match this task's position: module numbering starts at m1 and is "
            "contiguous, section numbering starts at s1 and is contiguous within each module. "
            "There is exactly one task per planned section — never a slug, and never a task for "
            "the curriculum overview (that is written later via write_curriculum_overview)."
        ),
    )
    title: str = Field(..., description="Task title, matching the section title.")
    description: str = Field("", description="1-2 sentences describing what this task covers.")
    module_ref: str = Field(
        ...,
        description=(
            "The module id this task belongs to, in the form 'm{X}' matching the id's 'm{X}-' "
            "prefix (e.g. module_ref 'm1' for id 'm1-s2'). Required — every task maps to exactly "
            "one section, so this is never null."
        ),
    )
    status: Literal["pending", "in_progress", "done"] = "pending"


class PlanModuleInput(BaseModel):
    """A single module's structural identity (id + real display title) within a proposed plan."""

    id: str = Field(
        ...,
        description=(
            "Module id in the form 'm{X}' (e.g. 'm1'), matching the module numbering used by "
            "the `id`/`module_ref` fields of this module's tasks."
        ),
    )
    title: str = Field(
        ...,
        description=(
            "The module's human-readable display title, exactly as it appears in the outline "
            "(e.g. for outline heading 'Module 3: System Design Fundamentals' this is "
            "'System Design Fundamentals' — WITHOUT the leading 'Module X:' numbering prefix). "
            "Non-empty, at most 80 characters. This exact string is persisted verbatim as the "
            "module document's display title once the plan is approved, so it must be the real "
            "module-level title — never a copy of one of its section titles, and never the bare "
            "module id."
        ),
    )
    description: str = Field(
        ...,
        description=(
            "1-2 sentences describing what this module covers, shown under the module's title "
            "on its node in the workflow canvas. Plain prose (no markdown), at most 300 "
            "characters. Must be a real summary of the module's content — never a restatement "
            "of the title, and never a list of its section titles."
        ),
    )


class ProposeTaskPlanInput(BaseModel):
    """Input schema for `ProposeTaskPlanTool`."""

    outline_markdown: str = Field(
        ...,
        description=(
            "Human-readable outline (module titles + summaries + section titles). Every section "
            "line MUST be labeled 'Section X.Y: <title>' (X = module number, Y = section number "
            "within that module) — propose_task_plan cross-checks these labels against `tasks` "
            "and rejects the plan if they don't match 1:1."
        ),
    )
    description: str = Field(
        ...,
        description=(
            "1-2 sentences describing what this curriculum covers and for whom, shown on the "
            "user's dashboard card under the curriculum title. Plain prose (no markdown), at "
            "most 300 characters."
        ),
    )
    tasks: list[PlanTaskInput] = Field(..., description="The full task list for this plan version.")
    modules: list[PlanModuleInput] = Field(
        ...,
        description=(
            "One entry per distinct module referenced by `tasks`, in module-number order "
            "(m1, m2, ...). The set of ids here must exactly match the set of `module_ref`s used "
            "across `tasks` (same ids, same order) — propose_task_plan rejects the plan if they "
            "don't align. This is the only place module display titles are captured; they are "
            "persisted onto the module documents when the plan is approved."
        ),
    )


def _validate_plan(input: ProposeTaskPlanInput) -> str | None:
    """Validate a proposed plan against the binding module/section id contract.

    Checks (in order, first failure wins): tasks non-empty; every task's `id`/
    `module_ref` match the `m{X}-s{Y}`/`m{X}` format with a consistent prefix; task ids
    are unique; module numbering is contiguous from m1 in first-appearance order; the
    `modules` list's ids exactly match that module set (same ids, same order) and every
    module has a non-empty, <=100-char title and a non-empty, <=500-char description
    (error text quotes the tighter 80/300-char prompt targets, not these real caps, so
    the model isn't told about the extra slack); section numbering is contiguous from s1
    per module in task-list order; the `outline_markdown`'s `Section X.Y` labels exactly
    match the task id set; and the curriculum-level `description` is non-empty and
    <=500 chars (same 300-char prompt target / undisclosed slack as above). Designed to
    catch the
    failure modes seen in practice: invented ids, missing module_ref, a module list that
    doesn't cover the tasks' modules (or reuses a section title as the module title), an
    outline that describes more sections than the task list actually covers, and a
    missing/oversized description at either the curriculum or module level.

    Args:
        input (ProposeTaskPlanInput): The plan input as submitted to `propose_task_plan`.

    Returns:
        str | None: A human/LLM-readable error message describing the first violation
            found, or None if the plan passes every check.
    """
    if not input.tasks:
        return "tasks must be non-empty — propose_task_plan requires at least one planned section."

    # Per-task format check: id/module_ref shape and their prefix must agree.
    for t in input.tasks:
        if not _MODULE_REF_RE.match(t.module_ref or ""):
            return (
                f"task {t.id!r} has invalid module_ref {t.module_ref!r} — module_ref must match "
                f"'m{{X}}' (e.g. 'm1'), and every task must set it (the overview is not a task)."
            )
        match = _TASK_ID_RE.match(t.id)
        if not match:
            return (
                f"task id {t.id!r} is invalid — ids must match 'm{{X}}-s{{Y}}' (e.g. 'm1-s2'), "
                f"never a free-form slug."
            )
        if match.group(1) != t.module_ref:
            return (
                f"task {t.id!r} has module_ref {t.module_ref!r}, but its id prefix implies module "
                f"{match.group(1)!r} — the 'm{{X}}-' prefix of id must equal module_ref exactly."
            )

    # Uniqueness of task ids.
    ids = [t.id for t in input.tasks]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        return f"duplicate task ids found: {dupes} — every task id must be unique within the plan."

    # Module numbering: contiguous from m1, in ascending first-appearance order (i.e.
    # m1's tasks must all be introduced before m2 first appears, etc.).
    module_first_seen: list[str] = []
    for t in input.tasks:
        if t.module_ref not in module_first_seen:
            module_first_seen.append(t.module_ref)
    expected_modules = [f"m{i}" for i in range(1, len(module_first_seen) + 1)]
    if module_first_seen != expected_modules:
        return (
            f"module numbering must be contiguous starting at m1 with modules introduced in "
            f"ascending order; got modules in first-appearance order {module_first_seen}, "
            f"expected {expected_modules}."
        )

    # Structured module list: ids must exactly cover expected_modules (same set, same
    # order) so every module gets a real display title captured for materialization.
    module_ids = [m.id for m in input.modules]
    if module_ids != expected_modules:
        return (
            f"modules must list exactly one entry per module in order m1..m{len(expected_modules)} "
            f"matching the module_refs used by tasks; got module ids {module_ids}, expected "
            f"{expected_modules}."
        )
    # Every module needs a real, non-empty, bounded-length display title — this is what
    # becomes the module doc's title at materialization, so a blank/oversized value is
    # rejected here rather than silently persisted.
    for m in input.modules:
        # Real hard cap is 100 chars; error text still cites 80 (the prompt target) so
        # the model isn't told about the extra slack.
        if not m.title.strip() or len(m.title) > 100:
            return (
                f"module {m.id!r} has an invalid title {m.title!r} — provide the module's real "
                f"display title as it appears in the outline (not a section title, not a bare "
                f"id), non-empty and at most 80 characters."
            )
        # Module description must be a real summary, bounded so it fits the workflow node
        # card. Real hard cap is 500 chars; error text still cites 300 (the prompt target)
        # so the model isn't told about the extra slack.
        if not m.description.strip() or len(m.description) > 500:
            return (
                f"module {m.id!r} has an invalid description — it must be non-empty and at most "
                f"300 characters, summarizing the module's content (not a copy of its title)."
            )

    # Section numbering: contiguous from s1 per module, in task-list order within that module.
    sections_by_module: dict[str, list[int]] = {}
    for t in input.tasks:
        section_num = int(_TASK_ID_RE.match(t.id).group(2))
        sections_by_module.setdefault(t.module_ref, []).append(section_num)
    for module_ref, section_nums in sections_by_module.items():
        expected = list(range(1, len(section_nums) + 1))
        if section_nums != expected:
            return (
                f"module {module_ref!r} section numbering must be contiguous starting at s1 in "
                f"task-list order; got {section_nums}, expected {expected}."
            )

    # Outline <-> tasks cross-check: every "Section X.Y" label in outline_markdown must
    # have exactly one corresponding m{X}-s{Y} task, and vice versa.
    outline_pairs = _OUTLINE_SECTION_RE.findall(input.outline_markdown)
    if not outline_pairs:
        return (
            "outline_markdown has no 'Section X.Y: <title>' labels — every section line in the "
            "outline must be labeled this way (X = module number, Y = section number) so it can "
            "be cross-checked against tasks."
        )
    outline_ids = {f"m{x}-s{y}" for x, y in outline_pairs}
    task_ids = set(ids)
    missing_from_tasks = sorted(outline_ids - task_ids)
    missing_from_outline = sorted(task_ids - outline_ids)
    if missing_from_tasks or missing_from_outline:
        parts = []
        if missing_from_tasks:
            parts.append(
                f"outline mentions {missing_from_tasks} but tasks has no matching entry"
            )
        if missing_from_outline:
            parts.append(
                f"tasks has {missing_from_outline} but outline_markdown never labels it "
                f"'Section X.Y'"
            )
        return (
            "outline_markdown and tasks disagree on which sections exist: "
            + "; ".join(parts)
            + " — every section in the outline needs exactly one task, and vice versa."
        )

    # Curriculum-level description must be a real summary, bounded so it fits the
    # dashboard card subtitle. Real hard cap is 500 chars; error text still cites 300
    # (the prompt target) so the model isn't told about the extra slack.
    if not input.description.strip() or len(input.description) > 500:
        return (
            "description is invalid — it must be non-empty and at most 300 characters, "
            "summarizing what this curriculum covers and for whom."
        )

    return None


class ProposeTaskPlanTool(Tool):
    name = "propose_task_plan"
    description = (
        "HITL GATE — propose the curriculum outline and task plan to the user for approval. "
        "Validates the plan first (task id format 'm{X}-s{Y}', module_ref prefix match, "
        "contiguous module/section numbering, that modules' ids exactly cover the tasks' module "
        "set with a real non-empty <=80-char title and non-empty <=300-char description per "
        "module, that outline_markdown's 'Section X.Y' labels match tasks 1:1, and a non-empty "
        "<=300-char curriculum-level description) — returns an error observation and saves "
        "nothing if the plan fails any check. Saves the plan, sets curriculum status to 'awaiting_approval', "
        "emits phase_change, progress, and plan_proposed events to the client (the modules list is "
        "saved but NOT included in the plan_proposed payload), and PAUSES your loop until the user "
        "responds with approve or modify. Call this alone, with no other tool calls in the same "
        "step. Use this both for the initial proposal and for re-proposing after incorporating "
        "'modify' feedback (the plan version increments automatically)."
    )
    input_model = ProposeTaskPlanInput

    async def execute(self, input: ProposeTaskPlanInput, ctx: AgentContext) -> dict[str, Any]:
        """Save the proposed plan, transition to awaiting_approval, and signal a HITL gate.

        This is one of the two HITL gate tools (see `HITL_GATE_TOOLS` in
        `tools/registry.py`): the returned `_hitl_gate: True` flag causes the
        orchestrator to pause the ReAct loop after this call, resuming only on the next
        `plan_decision` WS frame (handled by `Orchestrator._apply_plan_decision`).

        Args:
            input (ProposeTaskPlanInput): The validated outline markdown, curriculum-level
                description, full task list, and structured module list (id + display
                title + description, one per module) for this plan version.
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes the plan document.

        Returns:
            dict[str, Any]: `{"status": "proposed", "version", "task_count",
                "_ws_events": [...], "_hitl_gate": True}` — `_ws_events` carries, in
                order, a `phase_change` (awaiting_approval), a `progress` event (task
                counts, only when there are tasks), and the `plan_proposed` event (with
                the full outline/tasks/version — `modules` is persisted to the plan doc
                but intentionally omitted from this client-facing payload) for the
                client to render an approval card. `{"error": "..."}` instead, with no
                writes performed at all, if `_validate_plan` finds the plan violates the
                id/module_ref/modules/outline contract (invented ids, non-contiguous
                numbering, a modules list that doesn't cover the tasks' modules or has
                an invalid title, outline/tasks mismatch).
        """
        # Reject a malformed plan before any write — an invented id or an outline that
        # over-promises relative to tasks corrupts materialization downstream, so this
        # must be caught here rather than left for the writing phase to discover.
        validation_error = _validate_plan(input)
        if validation_error:
            return {"error": validation_error}

        existing = fs.get_plan(ctx.curriculum_id)
        # Plan versions increment monotonically across proposals (initial + any
        # re-proposals after "modify" feedback); user_feedback accumulates across
        # versions so later proposals retain the full feedback history.
        next_version = (existing.get("version", 0) + 1) if existing else 1
        user_feedback = existing.get("user_feedback", []) if existing else []

        plan_doc = {
            "version": next_version,
            "outline_markdown": input.outline_markdown,
            "description": input.description,
            "tasks": [t.model_dump() for t in input.tasks],
            # Structured module titles+descriptions (id + real display title + summary) —
            # the source of truth for module doc fields at materialization (see
            # orchestrator.py); NOT mirrored into the plan_proposed WS payload below
            # (frontend contract unchanged).
            "modules": [m.model_dump() for m in input.modules],
            "status": "proposed",
            "user_feedback": user_feedback,
        }
        fs.set_plan(ctx.curriculum_id, plan_doc)

        # done_count mirrors the reconnect-snapshot derivation in app/ws/chat.py so a
        # live client and a freshly (re)connected client see identical progress counts.
        tasks = plan_doc["tasks"]
        done_count = sum(1 for t in tasks if t.get("status") == "done")
        # Full-object write: update_curriculum merges top-level fields only, so the
        # nested "progress" dict must be written whole (same pattern as TransitionPhaseTool).
        # "description" is also written here so the dashboard card shows it as soon as a
        # plan is proposed — re-proposals overwrite it, latest wins.
        fs.update_curriculum(
            ctx.curriculum_id,
            {
                "status": "awaiting_approval",
                "description": input.description,
                "progress": {
                    "phase": "awaiting_approval",
                    "completed_tasks": done_count,
                    "total_tasks": len(tasks),
                    "detail": "",
                },
            },
        )
        fs.set_agent_state(
            ctx.curriculum_id,
            {"phase": "awaiting_approval"},
        )

        # Live WS events for the plan-gate transition — previously only the reconnect
        # snapshot emitted phase_change/progress, leaving a live client stuck showing
        # the prior phase until the next page load.
        ws_events: list[dict[str, Any]] = [
            {
                "type": "phase_change",
                "phase": "awaiting_approval",
                "label": PHASE_LABELS["awaiting_approval"],
            },
        ]
        if tasks:
            ws_events.append(
                {"type": "progress", "completed": done_count, "total": len(tasks), "detail": ""}
            )
        ws_events.append(
            {
                "type": "plan_proposed",
                "plan": {
                    "outline_markdown": input.outline_markdown,
                    "tasks": plan_doc["tasks"],
                    "version": next_version,
                },
            }
        )

        return {
            "status": "proposed",
            "version": next_version,
            "task_count": len(input.tasks),
            "_ws_events": ws_events,
            "_hitl_gate": True,
        }


class GetTaskPlanInput(BaseModel):
    """Input schema for `GetTaskPlanTool` (no fields — takes no arguments)."""

    pass


class GetTaskPlanTool(Tool):
    name = "get_task_plan"
    description = (
        "Fetch the current task plan (outline, tasks and their statuses, version). Use this "
        "to orient yourself in the writing phase or when resuming a plan revision."
    )
    input_model = GetTaskPlanInput

    async def execute(self, input: GetTaskPlanInput, ctx: AgentContext) -> dict[str, Any]:
        """Fetch the curriculum's current plan document.

        Args:
            input (GetTaskPlanInput): Empty input (no fields).
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes the lookup.

        Returns:
            dict[str, Any]: The full plan document (outline_markdown, tasks, status,
                version, user_feedback) on success, or `{"error": "..."}` if no plan
                has been proposed yet.
        """
        plan = fs.get_plan(ctx.curriculum_id)
        if not plan:
            return {"error": "no plan exists yet for this curriculum"}
        return plan
