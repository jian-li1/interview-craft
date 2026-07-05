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

# Phase labels shown in phase_change events and replayed on reconnect (see app/ws/chat.py
# session_ready resume snapshot).
PHASE_LABELS: dict[str, str] = {
    "intake": "Getting started",
    "deep_research": "Researching",
    "outline_planning": "Planning the curriculum",
    "awaiting_approval": "Awaiting your approval",
    "writing": "Writing curriculum content",
    "review": "Reviewing",
    "ready": "Ready",
    "refinement": "Refining",
}


class RequestUserInputInput(BaseModel):
    """Input schema for `RequestUserInputTool`."""

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
        """Signal a HITL pause requesting a clarifying answer from the user.

        This is the second of the two HITL gate tools (alongside `propose_task_plan`).
        Unlike a plan decision, resumption here is via an ordinary `user_message` WS
        frame — there is no dedicated "answer" frame type; the orchestrator just treats
        the next user message as the reply and continues the loop.

        Args:
            input (RequestUserInputInput): The validated question and optional quick-pick
                options.
            ctx (AgentContext): The current agent run's context (unused directly here;
                required by the `Tool.execute` signature).

        Returns:
            dict[str, Any]: `{"status": "awaiting_user_input", "question", "options",
                "_hitl_gate": True}` — the `_hitl_gate` flag causes the orchestrator to
                pause the loop after this call.
        """
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
    """Input schema for `UpdateScratchpadTool`."""

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
        """Overwrite the agent state doc's scratchpad field.

        Args:
            input (UpdateScratchpadInput): The validated full replacement scratchpad
                content (this always overwrites, never appends).
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                identifies the state doc to update.

        Returns:
            dict[str, Any]: `{"status": "updated"}`.
        """
        fs.set_agent_state(ctx.curriculum_id, {"scratchpad": input.content})
        return {"status": "updated"}


class CompletePhaseInput(BaseModel):
    """Input schema for `CompletePhaseTool`."""

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
        """Validate and apply a phase transition, updating state/curriculum status.

        Note that `ctx.phase` reflects the phase as of the start of this orchestrator
        iteration (per `app/agent/CLAUDE.md`, the orchestrator re-reads phase fresh from
        Firestore every iteration, so a transition here takes effect starting next
        iteration, not immediately within this one). Also keeps the curriculum's
        persisted `progress.phase` (and, on reaching "ready", `progress.detail`) in sync
        so REST readers never see a stale phase.

        Args:
            input (CompletePhaseInput): The validated target phase and a reason string
                (used for logging/debugging, not shown in the response beyond echoing
                it back).
            ctx (AgentContext): The current agent run's context; `ctx.phase` is the
                current phase used to validate the transition, and `ctx.curriculum_id`
                scopes the state/curriculum updates.

        Returns:
            dict[str, Any]: On success, `{"status": "transitioned", "phase", "reason",
                "_ws_event": {...}}` with a `phase_change` event for the orchestrator to
                forward. On failure, `{"error": "..."}` if `next_phase` is not a known
                `AgentPhase` value, or not an allowed transition from the current phase
                per `_VALID_TRANSITIONS`.
        """
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

        # Curriculum-facing status differs from the internal phase name in a few cases
        # (e.g. both "writing" and "review" phases map to the "writing" status shown to
        # the user; "ready" and "refinement" both map to "ready").
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
            # Keep the persisted progress blob's phase in sync with the curriculum status so
            # REST readers (dashboard) don't show a stale phase; full-object write because
            # update_curriculum merges top-level fields only (a dotted "progress.phase" key
            # would be stored literally, not merged into the nested dict).
            curriculum = fs.get_curriculum(ctx.curriculum_id) or {}
            progress = dict(curriculum.get("progress") or {})
            progress["phase"] = input.next_phase
            if input.next_phase == "ready":
                progress["detail"] = "Curriculum complete"
            fs.update_curriculum(ctx.curriculum_id, {"status": new_status, "progress": progress})

        return {
            "status": "transitioned",
            "phase": input.next_phase,
            "reason": input.reason,
            "_ws_event": {
                "type": "phase_change",
                "phase": input.next_phase,
                "label": PHASE_LABELS.get(input.next_phase, input.next_phase),
            },
        }
