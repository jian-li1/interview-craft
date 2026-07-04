"""Planning tools: propose_task_plan (HITL gate) and get_task_plan."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.tools.base import AgentContext, Tool
from app.services import firestore as fs


class PlanTaskInput(BaseModel):
    """A single task within a proposed task plan, corresponding to one section stub."""

    id: str = Field(..., description="Short stable slug, unique within the plan, e.g. 'm1-s2'.")
    title: str = Field(..., description="Task title, matching the section/overview title.")
    description: str = Field("", description="1-2 sentences describing what this task covers.")
    module_ref: str | None = Field(None, description="The module id/slug this task belongs to, or null.")
    status: Literal["pending", "in_progress", "done"] = "pending"


class ProposeTaskPlanInput(BaseModel):
    """Input schema for `ProposeTaskPlanTool`."""

    outline_markdown: str = Field(
        ..., description="Human-readable outline (module titles + summaries + section titles)."
    )
    tasks: list[PlanTaskInput] = Field(..., description="The full task list for this plan version.")


class ProposeTaskPlanTool(Tool):
    name = "propose_task_plan"
    description = (
        "HITL GATE — propose the curriculum outline and task plan to the user for approval. "
        "Saves the plan, sets curriculum status to 'awaiting_approval', emits a plan_proposed "
        "event to the client, and PAUSES your loop until the user responds with approve or "
        "modify. Call this alone, with no other tool calls in the same step. Use this both for "
        "the initial proposal and for re-proposing after incorporating 'modify' feedback "
        "(the plan version increments automatically)."
    )
    input_model = ProposeTaskPlanInput

    async def execute(self, input: ProposeTaskPlanInput, ctx: AgentContext) -> dict[str, Any]:
        """Save the proposed plan, transition to awaiting_approval, and signal a HITL gate.

        This is one of the two HITL gate tools (see `HITL_GATE_TOOLS` in
        `tools/registry.py`): the returned `_hitl_gate: True` flag causes the
        orchestrator to pause the ReAct loop after this call, resuming only on the next
        `plan_decision` WS frame (handled by `Orchestrator._apply_plan_decision`).

        Args:
            input (ProposeTaskPlanInput): The validated outline markdown and full task
                list for this plan version.
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes the plan document.

        Returns:
            dict[str, Any]: `{"status": "proposed", "version", "task_count",
                "_ws_event": {...}, "_hitl_gate": True}` — the `_ws_event` carries a
                `plan_proposed` event (with the full outline/tasks/version) for the
                client to render as an approval card.
        """
        existing = fs.get_plan(ctx.curriculum_id)
        # Plan versions increment monotonically across proposals (initial + any
        # re-proposals after "modify" feedback); user_feedback accumulates across
        # versions so later proposals retain the full feedback history.
        next_version = (existing.get("version", 0) + 1) if existing else 1
        user_feedback = existing.get("user_feedback", []) if existing else []

        plan_doc = {
            "version": next_version,
            "outline_markdown": input.outline_markdown,
            "tasks": [t.model_dump() for t in input.tasks],
            "status": "proposed",
            "user_feedback": user_feedback,
        }
        fs.set_plan(ctx.curriculum_id, plan_doc)
        fs.update_curriculum(ctx.curriculum_id, {"status": "awaiting_approval"})
        fs.set_agent_state(
            ctx.curriculum_id,
            {"phase": "awaiting_approval"},
        )

        return {
            "status": "proposed",
            "version": next_version,
            "task_count": len(input.tasks),
            "_ws_event": {
                "type": "plan_proposed",
                "plan": {
                    "outline_markdown": input.outline_markdown,
                    "tasks": plan_doc["tasks"],
                    "version": next_version,
                },
            },
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
