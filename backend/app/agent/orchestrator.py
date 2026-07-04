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
    """Terminal outcomes of one `Orchestrator.run_turn` call.

    Attributes:
        DONE: The model produced a plain-text answer with no tool calls; the turn is
            fully finished.
        PAUSED: A HITL gate tool (`propose_task_plan` or `request_user_input`) fired
            successfully this iteration; the loop is paused pending the next WS frame.
        CANCELLED: A `stop` WS frame arrived (cancel_event set) before or during this
            turn's LLM stream.
        ERROR: An unrecoverable condition occurred — an LLM stream error, or the loop
            exhausted `AGENT_MAX_ITERATIONS` without reaching DONE/PAUSED.
    """

    DONE = "done"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(slots=True)
class RunResult:
    """Return value of `Orchestrator.run_turn` / `_run_turn_inner`.

    Attributes:
        outcome (TurnOutcome): How the turn ended.
        detail (str): Optional human-readable detail (e.g. an exception message), empty
            string by default.
    """

    outcome: TurnOutcome
    detail: str = ""


@dataclass
class PlanDecision:
    """The user's response to a `propose_task_plan` HITL gate, carried in a WS frame.

    Attributes:
        decision (str): Either `"approve"` or `"modify"`.
        feedback (str | None): Free-text revision feedback, present when `decision` is
            `"modify"`; None for approvals.
    """

    decision: str  # "approve" | "modify"
    feedback: str | None = None


# One asyncio.Lock per conversation id, so only one agent run is ever active for a given
# conversation at a time (spec 02 §3: "Concurrency guard: one active run per conversation").
# NOTE (see backend/CLAUDE.md "Module-level orchestrator state"): this dict is
# process-global and keyed by conversation id, with no cleanup/eviction — a freshly
# constructed `Orchestrator(settings)` does NOT get its own lock/cancel state, it shares
# this module-level state with every other Orchestrator instance in the process.
_conversation_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# Cancellation events keyed by conversation id, set by the `stop` WS frame handler.
_cancel_events: dict[str, asyncio.Event] = defaultdict(asyncio.Event)


def get_conversation_lock(conversation_id: str) -> asyncio.Lock:
    """Return the (lazily created) asyncio.Lock guarding runs for `conversation_id`.

    Args:
        conversation_id (str): The conversation to get the lock for.

    Returns:
        asyncio.Lock: The shared lock instance for this conversation id (created on
            first access via the `defaultdict`, then reused for the life of the
            process).
    """
    return _conversation_locks[conversation_id]


def request_stop(conversation_id: str) -> None:
    """Signal cancellation for the currently running turn on this conversation, if any.

    Called by the WS layer when a `stop` frame arrives. Setting the event is a no-op if
    no turn is currently running (the event is simply left set until the next
    `_clear_cancel` call at the start of a new turn) or if the current iteration has
    already progressed past a cancellation check point.

    Args:
        conversation_id (str): The conversation whose active run should be cancelled.
    """
    _cancel_events[conversation_id].set()


def _clear_cancel(conversation_id: str) -> None:
    """Reset the cancellation event for `conversation_id` at the start of a new turn.

    Args:
        conversation_id (str): The conversation whose cancel event to clear.
    """
    _cancel_events[conversation_id].clear()


class Orchestrator:
    """Runs one agent turn (a bounded ReAct loop) for a given conversation/curriculum."""

    def __init__(self, settings: Settings) -> None:
        """Construct an Orchestrator with its own tool registry and memory manager.

        Note that the per-conversation locks/cancel events used by `run_turn` are
        module-level state shared across all Orchestrator instances (see the
        `_conversation_locks`/`_cancel_events` comments above) — only the registry and
        memory manager are per-instance here.

        Args:
            settings (Settings): Application settings, threaded through to the tool
                registry's tools (via `AgentContext`) and the memory manager (context
                token limit, prompt directory resolution).
        """
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
        If the lock is already held (a concurrent call for the same conversation), this
        returns immediately with a recoverable ERROR rather than queuing or blocking —
        the caller is expected to surface this to the client rather than retry silently.

        Args:
            conversation_id (str): The conversation this turn belongs to; also the key
                for the per-conversation lock/cancel event.
            curriculum_id (str): The curriculum this conversation is building/refining.
            owner_uid (str): The authenticated user's uid, used for profile/settings
                lookups and passed into `AgentContext`.
            user_input (str | PlanDecision | None): A plain user chat message, a
                `PlanDecision` (resuming a `propose_task_plan` HITL gate), or None (e.g.
                resuming after a `request_user_input` gate via an ordinary message is
                still a str — None covers other resume paths with no new input to record).
            emit (Emitter): Async callable used to stream WS events to the client for
                this turn.
            llm_provider_override (str | None): Optional per-call override of the LLM
                provider, beating both env default and the user's saved setting.
            search_provider_override (str | None): Optional per-call override of the
                search provider, beating both env default and the user's saved setting.

        Returns:
            RunResult: The terminal outcome and optional detail message for this turn.
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
            # Reset any stale cancellation from a previous turn before starting fresh —
            # otherwise a leftover `set()` from an earlier `stop` frame would cause this
            # brand-new turn to cancel itself on its very first check.
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
        """Run the actual ReAct loop body, already holding the per-conversation lock.

        Implements the per-iteration cycle documented in `app/agent/CLAUDE.md`:
        `build_context -> chat_stream -> split thinking/text -> execute tool calls ->
        check HITL gate -> loop or return`. Re-reads `phase` fresh from Firestore at the
        top of every iteration (a `complete_phase` call from a tool executed in a prior
        iteration only takes effect starting the next iteration).

        Args:
            conversation_id (str): The conversation this turn belongs to.
            curriculum_id (str): The curriculum this conversation is building/refining.
            owner_uid (str): The authenticated user's uid.
            user_input (str | PlanDecision | None): The new user input for this turn,
                as described in `run_turn`.
            emit (Emitter): Async callable used to stream WS events to the client.
            cancel_event (asyncio.Event): Cleared at the start of this turn; checked at
                each iteration boundary and mid-stream to support cooperative
                cancellation from a `stop` WS frame.
            llm_provider_override (str | None): Optional per-call LLM provider override.
            search_provider_override (str | None): Optional per-call search provider
                override.

        Returns:
            RunResult: The terminal outcome (DONE/PAUSED/CANCELLED/ERROR) for this turn.
        """
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
            # Cooperative cancellation check #1: before starting a new iteration at all.
            # (See below for check #2, mid-stream, and the post-stream re-check.)
            if cancel_event.is_set():
                fs.set_agent_state(curriculum_id, {"iteration_count": iteration})
                await emit({"type": "agent_done", "status": "cancelled"})
                return RunResult(TurnOutcome.CANCELLED)

            # Re-read phase fresh from Firestore every iteration (not cached from the
            # loop's start) — a `complete_phase` tool call in the previous iteration
            # must be visible here so the next iteration uses the new phase's tools/prompt.
            state = fs.get_agent_state(curriculum_id) or state
            phase = state.get("phase", phase)

            async def on_compaction(preview: str, before: int, after: int) -> None:
                """Forward a compaction event to the client via the outer `emit`.

                Args:
                    preview (str): A short preview of the new rolling summary.
                    before (int): Estimated token count before compaction.
                    after (int): Estimated token count after compaction.
                """
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
                    # Cooperative cancellation check #2: mid-stream, so a `stop` frame
                    # that arrives while the model is still generating breaks out promptly
                    # instead of waiting for the full response.
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

            # Cooperative cancellation check #3: after the stream loop exits (whether via
            # natural completion or the mid-stream `break` above) — persists whatever
            # partial text/reasoning was accumulated before the cancellation was noticed,
            # rather than silently discarding it.
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
                # No tool calls this iteration means the model produced a final answer:
                # persist it and end the turn as DONE (no further looping needed).
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
                # Pop the internal signaling keys before building the client-visible
                # preview — `_ws_events`/`_ws_event` are extra WS events a tool wants
                # emitted (e.g. curriculum_updated, progress), and `_hitl_gate` marks a
                # successful call as one that should pause the loop. None of these three
                # keys should leak into the JSON preview shown to the client/model.
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

                # Only a *successful* gate call pauses the loop — a failed
                # propose_task_plan/request_user_input call (e.g. validation error)
                # should not pause; the model gets the error observation and can retry
                # within the same turn, up to max_iterations.
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
                # Pause immediately even if this wasn't the last tool call batched this
                # step and even if max_iterations hasn't been reached — a gate call
                # always ends the turn, per app/agent/CLAUDE.md.
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
        user to confirm/approve again next turn. This is the resume half of the
        `propose_task_plan` HITL gate documented in `app/agent/CLAUDE.md`.

        Args:
            conversation_id (str): The conversation to append the synthetic system
                message to.
            curriculum_id (str): The curriculum whose plan/state/status are updated.
            decision (PlanDecision): The user's decision — "approve" (materialize
                modules/sections, jump to the "writing" phase) or "modify" (record
                feedback, return to "outline_planning" for a re-proposal).

        Returns:
            None: Mutates Firestore state and appends a message; does not return a value.
            No-ops entirely if no plan exists yet for this curriculum.
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
        Idempotent with respect to already-materialized modules/sections (skips ids that
        already exist), so re-running this after a partial failure or a second approval
        of the same plan version does not duplicate stubs.

        Args:
            curriculum_id (str): The curriculum to create module/section stubs under.
            plan (dict[str, Any]): The approved plan document, whose `tasks` list
                (each with `id`, `title`, optional `module_ref`) drives stub creation.

        Returns:
            None: Creates Firestore module/section documents as a side effect.
        """
        tasks = plan.get("tasks", [])
        module_order: dict[str, int] = {}
        module_titles: dict[str, str] = {}

        # First pass: discover distinct module_refs in task order, assigning each a
        # stable order index and deriving its title from the first task that references
        # it (truncated at any ':' separator and 80 chars, matching module doc limits).
        for t in tasks:
            module_ref = t.get("module_ref")
            if not module_ref:
                continue
            if module_ref not in module_order:
                module_order[module_ref] = len(module_order)
                module_titles[module_ref] = t.get("title", module_ref).split(":")[0][:80]

        # Only create modules that don't already exist — re-approving a plan (or a
        # partially-completed prior materialization) must not duplicate/reset modules.
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

        # Second pass: create a "planned" section stub per task, using a per-module
        # counter (defaultdict) so each module's sections are ordered 0..N independent
        # of their position in the flat `tasks` list.
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
