"""Planning tools: propose_task_plan (HITL gate) and get_task_plan."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.tools.base import AgentContext, Tool
from app.services import firestore as fs


class PlanTaskInput(BaseModel):
    id: str = Field(..., description="Short stable slug, unique within the plan, e.g. 'm1-s2'.")
    title: str = Field(..., description="Task title, matching the section/overview title.")
    description: str = Field("", description="1-2 sentences describing what this task covers.")
    module_ref: str | None = Field(None, description="The module id/slug this task belongs to, or null.")
    status: Literal["pending", "in_progress", "done"] = "pending"


class ProposeTaskPlanInput(BaseModel):
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
        existing = fs.get_plan(ctx.curriculum_id)
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
    pass


class GetTaskPlanTool(Tool):
    name = "get_task_plan"
    description = (
        "Fetch the current task plan (outline, tasks and their statuses, version). Use this "
        "to orient yourself in the writing phase or when resuming a plan revision."
    )
    input_model = GetTaskPlanInput

    async def execute(self, input: GetTaskPlanInput, ctx: AgentContext) -> dict[str, Any]:
        plan = fs.get_plan(ctx.curriculum_id)
        if not plan:
            return {"error": "no plan exists yet for this curriculum"}
        return plan
