"""Control tools: request_user_input (HITL gate), update_scratchpad, complete_phase."""

from __future__ import annotations

from typing import Any, get_args

from pydantic import BaseModel, Field

from app.agent.tools.base import AgentContext, Tool
from app.models.curriculum import AgentPhase
from app.services import firestore as fs

_VALID_PHASES = set(get_args(AgentPhase))

# Allowed forward/backward transitions, mirroring the state machine in spec 02 §2.
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "intake": {"deep_research"},
    "deep_research": {"outline_planning"},
    "outline_planning": {"awaiting_approval", "outline_planning"},
    "awaiting_approval": {"writing", "outline_planning"},
    "writing": {"review"},
    "review": {"ready"},
    "ready": {"refinement"},
    "refinement": {"refinement"},
}


class RequestUserInputInput(BaseModel):
    question: str = Field(..., description="The clarifying question to ask the user.")
    options: list[str] | None = Field(
        None, description="Optional 2-4 concrete quick-pick options; free text is always still allowed."
    )


class RequestUserInputTool(Tool):
    name = "request_user_input"
    description = (
        "HITL GATE — ask the user a clarifying question and PAUSE your loop until they reply. "
        "Renders as an interactive question card in chat. Provide 'options' for quick-pick "
        "choices when applicable. Use sparingly — only when genuinely ambiguous (see "
        "intake_phase.md); most requests should proceed without this."
    )
    input_model = RequestUserInputInput

    async def execute(self, input: RequestUserInputInput, ctx: AgentContext) -> dict[str, Any]:
        # No WS event is emitted directly by this tool; the orchestrator streams the
        # question as ordinary assistant text (rendered as a question card by the
        # frontend based on message shape) and pauses the loop via the `_hitl_gate` flag.
        return {
            "status": "awaiting_user_input",
            "question": input.question,
            "options": input.options,
            "_hitl_gate": True,
        }


class UpdateScratchpadInput(BaseModel):
    content: str = Field(
        ..., description="The full new scratchpad content, overwriting the previous value."
    )


class UpdateScratchpadTool(Tool):
    name = "update_scratchpad"
    description = (
        "Overwrite your own working scratchpad in the agent state doc: notes to your future "
        "self about what's done, what's next, and open questions/decisions. Keep this current "
        "so a crashed/resumed run or a post-compaction turn can pick up seamlessly."
    )
    input_model = UpdateScratchpadInput

    async def execute(self, input: UpdateScratchpadInput, ctx: AgentContext) -> dict[str, Any]:
        fs.set_agent_state(ctx.curriculum_id, {"scratchpad": input.content})
        return {"status": "updated"}


class CompletePhaseInput(BaseModel):
    next_phase: str = Field(..., description="The phase to transition into.")
    reason: str = Field(..., description="Brief reason for this transition (for logging/debugging).")


class CompletePhaseTool(Tool):
    name = "complete_phase"
    description = (
        "Transition the agent to the next phase in the state machine (intake -> deep_research "
        "-> outline_planning -> awaiting_approval -> writing -> review -> ready -> refinement). "
        "Validates the transition is allowed, updates the state doc and curriculum status, and "
        "emits a phase_change event. Only call this once your current phase's exit criteria "
        "(defined in its instruction file) are actually met."
    )
    input_model = CompletePhaseInput

    async def execute(self, input: CompletePhaseInput, ctx: AgentContext) -> dict[str, Any]:
        if input.next_phase not in _VALID_PHASES:
            return {"error": f"unknown phase: {input.next_phase!r}"}

        current = ctx.phase
        allowed = _VALID_TRANSITIONS.get(current, set())
        if input.next_phase not in allowed:
            return {
                "error": (
                    f"invalid transition from {current!r} to {input.next_phase!r}; "
                    f"allowed next phases from here: {sorted(allowed)}"
                )
            }

        fs.set_agent_state(ctx.curriculum_id, {"phase": input.next_phase})

        status_map = {
            "deep_research": "researching",
            "outline_planning": "planning",
            "awaiting_approval": "awaiting_approval",
            "writing": "writing",
            "review": "writing",
            "ready": "ready",
            "refinement": "ready",
        }
        new_status = status_map.get(input.next_phase)
        if new_status:
            fs.update_curriculum(ctx.curriculum_id, {"status": new_status})

        label_map = {
            "intake": "Getting started",
            "deep_research": "Researching",
            "outline_planning": "Planning the curriculum",
            "awaiting_approval": "Awaiting your approval",
            "writing": "Writing curriculum content",
            "review": "Reviewing",
            "ready": "Ready",
            "refinement": "Refining",
        }

        return {
            "status": "transitioned",
            "phase": input.next_phase,
            "reason": input.reason,
            "_ws_event": {
                "type": "phase_change",
                "phase": input.next_phase,
                "label": label_map.get(input.next_phase, input.next_phase),
            },
        }
