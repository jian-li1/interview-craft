"""The Orchestrator: full ReAct loop with streaming, phase state machine, HITL gates.

See docs/specs/02-agent-system-spec.md §3 for the exact contract this implements.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.agent.memory.manager import MemoryManager
from app.agent.stream_split import ThinkingStreamSplitter
from app.agent.tools.base import AgentContext
from app.agent.tools.registry import ToolRegistry
from app.core.config import Settings
from app.core.logging import get_logger
from app.services import firestore as fs
from app.services.llm.base import ChatMessage, Done, TextDelta, ToolCallDelta
from app.services.llm.factory import get_llm_provider
from app.services.search.factory import get_search_provider

logger = get_logger(__name__)

# WS emitter is any async callable taking a JSON-serializable event dict.
Emitter = Callable[[dict[str, Any]], Awaitable[None]]

TOOL_OUTPUT_PREVIEW_CHARS = 1500


class TurnOutcome(str, Enum):
    DONE = "done"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(slots=True)
class RunResult:
    outcome: TurnOutcome
    detail: str = ""


@dataclass
class PlanDecision:
    decision: str  # "approve" | "modify"
    feedback: str | None = None


# One asyncio.Lock per conversation id, so only one agent run is ever active for a given
# conversation at a time (spec 02 §3: "Concurrency guard: one active run per conversation").
_conversation_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# Cancellation events keyed by conversation id, set by the `stop` WS frame handler.
_cancel_events: dict[str, asyncio.Event] = defaultdict(asyncio.Event)


def get_conversation_lock(conversation_id: str) -> asyncio.Lock:
    return _conversation_locks[conversation_id]


def request_stop(conversation_id: str) -> None:
    """Signal cancellation for the currently running turn on this conversation, if any."""
    _cancel_events[conversation_id].set()


def _clear_cancel(conversation_id: str) -> None:
    _cancel_events[conversation_id].clear()


class Orchestrator:
    """Runs one agent turn (a bounded ReAct loop) for a given conversation/curriculum."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._registry = ToolRegistry()
        self._memory = MemoryManager(settings)

    async def run_turn(
        self,
        *,
        conversation_id: str,
        curriculum_id: str,
        owner_uid: str,
        user_input: str | PlanDecision | None,
        emit: Emitter,
        llm_provider_override: str | None = None,
        search_provider_override: str | None = None,
    ) -> RunResult:
        """Run a bounded ReAct loop for one user turn, streaming events via `emit`.

        Acquires the per-conversation lock so only one run is ever active. Returns once
        the turn is DONE (plain text answer), PAUSED (a HITL gate tool was called),
        CANCELLED (a `stop` frame arrived), or ERROR (max iterations / unrecoverable).
        """
        lock = get_conversation_lock(conversation_id)
        if lock.locked():
            await emit(
                {
                    "type": "error",
                    "message": "An agent run is already active for this conversation.",
                    "recoverable": True,
                }
            )
            return RunResult(TurnOutcome.ERROR, "already running")

        async with lock:
            _clear_cancel(conversation_id)
            cancel_event = _cancel_events[conversation_id]
            try:
                return await self._run_turn_inner(
                    conversation_id=conversation_id,
                    curriculum_id=curriculum_id,
                    owner_uid=owner_uid,
                    user_input=user_input,
                    emit=emit,
                    cancel_event=cancel_event,
                    llm_provider_override=llm_provider_override,
                    search_provider_override=search_provider_override,
                )
            except Exception as exc:  # last-resort guard: the loop itself must not crash the WS
                logger.exception(
                    "orchestrator run_turn failed",
                    extra={"extra_fields": {"conversation_id": conversation_id}},
                )
                await emit({"type": "error", "message": f"internal error: {exc}", "recoverable": True})
                return RunResult(TurnOutcome.ERROR, str(exc))

    async def _run_turn_inner(
        self,
        *,
        conversation_id: str,
        curriculum_id: str,
        owner_uid: str,
        user_input: str | PlanDecision | None,
        emit: Emitter,
        cancel_event: asyncio.Event,
        llm_provider_override: str | None,
        search_provider_override: str | None,
    ) -> RunResult:
        user = fs.get_user(owner_uid) or {}
        user_settings = user.get("settings", {}) if isinstance(user, dict) else {}
        llm = get_llm_provider(llm_provider_override or user_settings.get("llm_provider"), self._settings)
        small_llm = llm  # same provider instance handles `small=True` model routing internally
        search = get_search_provider(search_provider_override or user_settings.get("search_provider"), self._settings)

        # Record the incoming user turn (unless this is a plan_decision resume, which has
        # no new chat message of its own — it's handled as a synthetic tool observation).
        if isinstance(user_input, str):
            fs.append_message(conversation_id, {"role": "user", "content": user_input})
        elif isinstance(user_input, PlanDecision):
            await self._apply_plan_decision(conversation_id, curriculum_id, user_input)
            await emit({"type": "curriculum_updated", "curriculum_id": curriculum_id, "scope": "curriculum"})

        profile = fs.get_profile(owner_uid)
        synthesized_profile = profile.get("synthesized_profile") if profile else None

        state = fs.get_agent_state(curriculum_id) or {"phase": "intake", "task_queue": [], "scratchpad": "", "iteration_count": 0}
        phase = state.get("phase", "intake")

        max_iterations = self._settings.agent_max_iterations

        for iteration in range(max_iterations):
            if cancel_event.is_set():
                fs.set_agent_state(curriculum_id, {"iteration_count": iteration})
                await emit({"type": "agent_done", "status": "cancelled"})
                return RunResult(TurnOutcome.CANCELLED)

            state = fs.get_agent_state(curriculum_id) or state
            phase = state.get("phase", phase)

            async def on_compaction(preview: str, before: int, after: int) -> None:
                await emit(
                    {
                        "type": "compaction",
                        "summary_preview": preview,
                        "tokens_before": before,
                        "tokens_after": after,
                    }
                )

            messages = await self._memory.build_context(
                conversation_id=conversation_id,
                phase=phase,
                synthesized_profile=synthesized_profile,
                profile=profile,
                agent_state=state,
                small_llm=small_llm,
                on_compaction=on_compaction,
            )

            ctx = AgentContext(
                curriculum_id=curriculum_id,
                conversation_id=conversation_id,
                owner_uid=owner_uid,
                settings=self._settings,
                llm=llm,
                small_llm=small_llm,
                search=search,
                phase=phase,
                emit=emit,
            )

            message_id = fs.new_id()
            await emit({"type": "message_start", "message_id": message_id, "role": "assistant"})

            tool_specs = self._registry.specs_for_phase(phase)

            splitter = ThinkingStreamSplitter()
            reasoning_acc = ""
            text_acc = ""
            tool_calls: list[ToolCallDelta] = []

            stream = llm.chat_stream(messages, tools=tool_specs)
            try:
                async for event in stream:
                    if cancel_event.is_set():
                        break
                    if isinstance(event, TextDelta):
                        delta = splitter.feed(event.text)
                        if delta.reasoning:
                            reasoning_acc += delta.reasoning
                            await emit(
                                {"type": "reasoning_delta", "message_id": message_id, "delta": delta.reasoning}
                            )
                        if delta.text:
                            text_acc += delta.text
                            await emit({"type": "text_delta", "message_id": message_id, "delta": delta.text})
                    elif isinstance(event, ToolCallDelta):
                        tool_calls.append(event)
                    elif isinstance(event, Done):
                        pass
            except Exception as exc:
                logger.exception("LLM stream failed", extra={"extra_fields": {"conversation_id": conversation_id}})
                await emit({"type": "error", "message": f"LLM error: {exc}", "recoverable": True})
                await emit({"type": "message_end", "message_id": message_id})
                return RunResult(TurnOutcome.ERROR, str(exc))
            finally:
                # If we broke out early due to cancellation, the async generator is still
                # "open" from the provider's/SDK's point of view — closing it here signals
                # the underlying HTTP stream to shut down instead of leaving it abandoned
                # (which would otherwise keep a local llama.cpp server generating forever).
                # aclose() on an already-exhausted generator is a harmless no-op.
                with contextlib.suppress(Exception):
                    await stream.aclose()

            if cancel_event.is_set():
                final_delta = splitter.flush()
                text_acc += final_delta.text
                reasoning_acc += final_delta.reasoning
                fs.append_message(
                    conversation_id,
                    {"role": "assistant", "content": text_acc, "reasoning": reasoning_acc or None, "tool_calls": []},
                )
                fs.set_agent_state(curriculum_id, {"iteration_count": iteration})
                await emit({"type": "message_end", "message_id": message_id})
                await emit({"type": "agent_done", "status": "cancelled"})
                return RunResult(TurnOutcome.CANCELLED)

            final_delta = splitter.flush()
            text_acc += final_delta.text
            reasoning_acc += final_delta.reasoning

            if not tool_calls:
                fs.append_message(
                    conversation_id,
                    {"role": "assistant", "content": text_acc, "reasoning": reasoning_acc or None, "tool_calls": []},
                )
                await emit({"type": "message_end", "message_id": message_id})
                fs.set_agent_state(curriculum_id, {"iteration_count": iteration + 1})

                await emit({"type": "agent_done", "status": "ok"})
                return RunResult(TurnOutcome.DONE)

            tool_call_records: list[dict[str, Any]] = []
            hit_hitl_gate = False

            for tc in tool_calls:
                await emit(
                    {
                        "type": "tool_call_start",
                        "message_id": message_id,
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                )
                result = await self._registry.execute(tc.name, tc.arguments, ctx)
                output = dict(result.output)
                ws_events = output.pop("_ws_events", None) or (
                    [output.pop("_ws_event")] if output.get("_ws_event") else []
                )
                output.pop("_ws_event", None)
                is_gate = bool(output.pop("_hitl_gate", False)) or self._registry.is_hitl_gate(tc.name)

                preview_source = json.dumps(output, default=str)
                output_preview = preview_source[:TOOL_OUTPUT_PREVIEW_CHARS]

                await emit(
                    {
                        "type": "tool_call_result",
                        "message_id": message_id,
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "output_preview": output_preview,
                        "status": result.status,
                        "elapsed_ms": result.elapsed_ms,
                    }
                )
                for ws_event in ws_events:
                    if ws_event:
                        await emit(ws_event)

                tool_call_records.append(
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                        "output_preview": output_preview,
                        "status": result.status,
                    }
                )

                if is_gate and result.status == "ok":
                    hit_hitl_gate = True

            fs.append_message(
                conversation_id,
                {
                    "role": "assistant",
                    "content": text_acc,
                    "reasoning": reasoning_acc or None,
                    "tool_calls": tool_call_records,
                },
            )
            await emit({"type": "message_end", "message_id": message_id})

            fs.set_agent_state(curriculum_id, {"iteration_count": iteration + 1})

            if hit_hitl_gate:
                await emit({"type": "agent_done", "status": "paused"})
                return RunResult(TurnOutcome.PAUSED)

            # Otherwise loop again: tool observations are now in context for next iteration.

        await emit(
            {
                "type": "error",
                "message": "Agent reached the maximum number of reasoning iterations for this turn.",
                "recoverable": True,
            }
        )
        await emit({"type": "agent_done", "status": "max_iterations"})
        return RunResult(TurnOutcome.ERROR, "max iterations")

    async def _apply_plan_decision(
        self, conversation_id: str, curriculum_id: str, decision: PlanDecision
    ) -> None:
        """Handle an incoming plan_decision frame: approve materializes stubs, modify records feedback.

        Appends a synthetic system message in both branches so the resumed model can see
        (via the rebuilt context) that the decision already happened, instead of asking the
        user to confirm/approve again next turn.
        """
        plan = fs.get_plan(curriculum_id)
        if not plan:
            return

        if decision.decision == "approve":
            fs.set_plan(curriculum_id, {"status": "approved"})
            await self._materialize_modules_and_sections(curriculum_id, plan)
            task_ids = [t["id"] for t in plan.get("tasks", []) if t.get("status") != "done"]
            fs.set_agent_state(
                curriculum_id,
                {"phase": "writing", "task_queue": task_ids, "current_task_id": task_ids[0] if task_ids else None},
            )
            fs.update_curriculum(curriculum_id, {"status": "writing"})
            plan_version = plan.get("version", 1)
            fs.append_message(
                conversation_id,
                {
                    "role": "system",
                    "content": (
                        f"The user APPROVED task plan v{plan_version} by clicking the Approve "
                        f"button. Module and section stubs have been materialized and the phase "
                        f"is now 'writing'. Begin executing the first task from the task queue "
                        f"immediately. Do NOT ask for approval or confirmation again."
                    ),
                },
            )
        else:
            feedback_list = plan.get("user_feedback", [])
            if decision.feedback:
                feedback_list.append(decision.feedback)
            fs.set_plan(curriculum_id, {"status": "revising", "user_feedback": feedback_list})
            fs.set_agent_state(curriculum_id, {"phase": "outline_planning"})
            fs.update_curriculum(curriculum_id, {"status": "planning"})
            fs.append_message(
                conversation_id,
                {
                    "role": "system",
                    "content": (
                        f"The user requested changes to the task plan with this feedback: "
                        f"{decision.feedback!r}. Revise the outline accordingly and re-propose "
                        f"with propose_task_plan."
                    ),
                },
            )

    async def _materialize_modules_and_sections(self, curriculum_id: str, plan: dict[str, Any]) -> None:
        """Create module/section stub docs from the approved plan's tasks.

        Groups tasks by `module_ref`; each distinct module_ref becomes a module doc (title
        derived from the first task referencing it, refined later by the agent if needed),
        and each task becomes a "planned" section stub the writing phase will fill in.
        """
        tasks = plan.get("tasks", [])
        module_order: dict[str, int] = {}
        module_titles: dict[str, str] = {}

        for t in tasks:
            module_ref = t.get("module_ref")
            if not module_ref:
                continue
            if module_ref not in module_order:
                module_order[module_ref] = len(module_order)
                module_titles[module_ref] = t.get("title", module_ref).split(":")[0][:80]

        existing_modules = {m["id"] for m in fs.list_modules(curriculum_id)}
        for module_id, order in module_order.items():
            if module_id in existing_modules:
                continue
            fs.create_module(
                curriculum_id,
                module_id,
                {
                    "order": order,
                    "title": module_titles[module_id],
                    "summary": "",
                    "objectives": [],
                    "status": "planned",
                    "estimated_minutes": 0,
                },
            )

        section_order: dict[str, int] = defaultdict(int)
        for t in tasks:
            module_ref = t.get("module_ref")
            if not module_ref:
                continue
            section_id = t["id"]
            existing = fs.get_section(curriculum_id, module_ref, section_id)
            if existing:
                continue
            order = section_order[module_ref]
            section_order[module_ref] += 1
            fs.create_section(
                curriculum_id,
                module_ref,
                section_id,
                {
                    "order": order,
                    "title": t.get("title", ""),
                    "content_markdown": "",
                    "citations": [],
                    "status": "planned",
                },
            )
