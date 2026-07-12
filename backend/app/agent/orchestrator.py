"""The Orchestrator: full ReAct loop with streaming, phase state machine, HITL gates.

See docs/specs/02-agent-system-spec.md §3 for the exact contract this implements.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.agent.memory.manager import COMPACTION_TRIGGER_FRACTION, MemoryManager
from app.agent.tools.base import AgentContext
from app.agent.tools.control import PHASE_LABELS
from app.agent.tools.curriculum import strip_stale_section_content
from app.agent.tools.registry import ToolRegistry
from app.agent.tools.research import strip_stale_fetch_url_outputs
from app.core.config import Settings
from app.core.logging import get_logger
from app.services import firestore as fs
from app.services.llm.base import ChatMessage, Done, ReasoningDelta, TextDelta, ToolCallDelta
from app.services.llm.factory import get_llm_provider, resolve_model
from app.services.search.factory import get_search_provider, resolve_search_provider

logger = get_logger(__name__)

# WS emitter is any async callable taking a JSON-serializable event dict.
Emitter = Callable[[dict[str, Any]], Awaitable[None]]

# Client-facing preview cap only. The full tool output is stored separately in
# `output_full` and replayed to the model verbatim — this cap governs the short
# `output_preview` shown in the WS/UI, NOT what the model sees.
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


# Sentinel: converts StopAsyncIteration to a plain value so asyncio.wait() can
# distinguish stream exhaustion from exceptions.
_STREAM_END = object()


async def _wait_cancellable(coro_task: asyncio.Task, cancel_event: asyncio.Event) -> tuple[bool, Any]:
    """Race an in-flight task against a cancellation event, whichever finishes first.

    This is the core primitive behind "immediate" `stop` handling: without it, a `stop`
    WS frame only takes effect at coarse checkpoints (between loop iterations), leaving
    two gaps — (a) nothing interrupts a long wait on the next LLM stream chunk (a slow
    prefill on a local OpenAI-compatible server can stall for many seconds), and (b) a
    long-running tool call (e.g. `fetch_url`, which fetches a full page and can take
    10-30s) runs to completion even after `stop` arrives. By racing the actual work
    against `cancel_event.wait()`, a `stop` frame that arrives mid-await is noticed
    within one event-loop tick instead of only at the next natural checkpoint.

    Args:
        coro_task (asyncio.Task): An already-scheduled task wrapping the awaitable to
            race (e.g. a task wrapping `stream.__anext__()` or `registry.execute(...)`).
            Must be a `Task` (not a bare coroutine) so it can be cancelled independently
            of the waiter task below.
        cancel_event (asyncio.Event): The per-conversation cancellation event; if this
            is set before `coro_task` completes, `coro_task` is cancelled and this
            function returns early.

    Returns:
        tuple[bool, Any]: `(cancelled, result)`. If `coro_task` finished first,
            `cancelled` is False and `result` is `coro_task.result()` (any exception
            raised by `coro_task` propagates to the caller here, exactly as a plain
            `await coro_task` would — callers rely on this to keep their existing
            `except Exception` handling around the LLM stream working unchanged). If
            the cancel event fired first, `cancelled` is True, `result` is None,
            `coro_task` is cancelled, and any exception it raises as a result of that
            cancellation is suppressed (we don't care about it — the caller is
            abandoning this operation).
    """
    # Wrap the cancel_event wait in its own task so asyncio.wait can race the two
    # concurrently; a bare coroutine can't be cancelled independently the way a Task can.
    waiter = asyncio.create_task(cancel_event.wait())
    try:
        done, _pending = await asyncio.wait({coro_task, waiter}, return_when=asyncio.FIRST_COMPLETED)

        if coro_task in done:
            # Work finished first — .result() lets any exception propagate to the caller.
            return False, coro_task.result()

        # Cancel event fired first: cancel the in-flight work and discard whatever it
        # raises while unwinding — the caller is abandoning this result anyway.
        coro_task.cancel()
        with contextlib.suppress(BaseException):
            await coro_task
        return True, None
    finally:
        # Always reap the waiter so it can't log "exception never retrieved" at GC time.
        waiter.cancel()
        with contextlib.suppress(BaseException):
            await waiter


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
        model: str | None = None,
        search_provider: str | None = None,
    ) -> RunResult:
        """Run a bounded ReAct loop for one user turn, streaming events via `emit`.

        Acquires the per-conversation lock so only one run is ever active. Returns once
        the turn is DONE (plain text answer), PAUSED (a HITL gate tool was called),
        CANCELLED (a `stop` frame arrived), or ERROR (max iterations / unrecoverable).
        If the lock is already held (a concurrent call for the same conversation), this
        returns immediately with a recoverable ERROR rather than queuing or blocking —
        the caller is expected to surface this to the client rather than retry silently.
        On every terminal path reached once the lock is held (including the LLM-stream
        failure path and this method's own outer exception handler) an `agent_done`
        event is emitted, carrying a server-measured `elapsed_ms` for the whole run.

        Args:
            conversation_id (str): The conversation this turn belongs to; also the key
                for the per-conversation lock/cancel event.
            curriculum_id (str): The curriculum this conversation is building/refining.
            owner_uid (str): The authenticated user's uid, passed into `AgentContext`.
            user_input (str | PlanDecision | None): A plain user chat message, a
                `PlanDecision` (resuming a `propose_task_plan` HITL gate), or None (e.g.
                resuming after a `request_user_input` gate via an ordinary message is
                still a str — None covers other resume paths with no new input to
                record). A str value also clears any persisted `pending_user_input` on
                the agent state doc, since it answers/dismisses that gate if one was open.
            emit (Emitter): Async callable used to stream WS events to the client for
                this turn.
            model (str | None): Optional per-call model selection (from the composer's
                model chip, sent on the WS frame); beats the conversation doc's
                persisted `selected_model`, which beats `Settings.default_model`. See
                `_run_turn_inner` for the full resolution/persistence logic.
            search_provider (str | None): Optional per-call search provider selection
                (from the composer's search chip); beats the conversation doc's
                persisted `search_provider`, which beats `DEFAULT_SEARCH_PROVIDER`.

        Returns:
            RunResult: The terminal outcome and optional detail message for this turn.
        """
        lock = get_conversation_lock(conversation_id)
        if lock.locked():
            # NOTE: do NOT emit agent_done here — another run is genuinely still active
            # for this conversation, so emitting it would wrongly clear the client's
            # running state for that other, still-in-flight run.
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
            # Server-measured wall-clock start of this run, threaded through to
            # _run_turn_inner so every terminal path can compute an authoritative
            # elapsed_ms (the frontend previously only measured this client-side).
            run_started = time.monotonic()
            try:
                return await self._run_turn_inner(
                    conversation_id=conversation_id,
                    curriculum_id=curriculum_id,
                    owner_uid=owner_uid,
                    user_input=user_input,
                    emit=emit,
                    cancel_event=cancel_event,
                    model=model,
                    search_provider=search_provider,
                    run_started=run_started,
                )
            except Exception as exc:  # last-resort guard: the loop itself must not crash the WS
                logger.exception(
                    "orchestrator run_turn failed",
                    extra={"extra_fields": {"conversation_id": conversation_id}},
                )
                await emit({"type": "error", "message": f"internal error: {exc}", "recoverable": True})
                # Without this, an internal error here (outside _run_turn_inner's own
                # handling) would leave the client stuck showing the run as "running".
                await emit(
                    {
                        "type": "agent_done",
                        "status": "error",
                        "elapsed_ms": int((time.monotonic() - run_started) * 1000),
                    }
                )
                return RunResult(TurnOutcome.ERROR, str(exc))

    async def compact_now(
        self,
        *,
        conversation_id: str,
        curriculum_id: str,
        owner_uid: str,
        emit: Emitter,
        model: str | None = None,
    ) -> None:
        """Manually trigger compaction for this conversation, bypassing the token threshold.

        Backs the client's "Compact now" button (the `compact` WS frame — see
        `app/ws/chat.py`). Mirrors `run_turn`'s concurrency guard: since compaction reads
        the conversation/state doc and mutates the conversation doc, it must not run
        concurrently with an active agent turn on the same conversation, so it acquires
        the same per-conversation lock via `get_conversation_lock` and, if already held,
        emits a recoverable error instead of blocking or queuing. On success it streams
        the same `compaction_start`/`compaction`/`context_usage` WS events as auto-
        compaction (via `MemoryManager.build_context(..., force_compact=True)`); the
        assembled message list itself is discarded since this call's only purpose is the
        side effect (persisting the new summary checkpoint).

        Args:
            conversation_id (str): The conversation to compact.
            curriculum_id (str): The curriculum whose saved sources feed the context
                assembly (unused for compaction itself, but required by
                `MemoryManager.build_context`'s signature).
            owner_uid (str): The authenticated user's uid (kept for signature symmetry
                with `run_turn`; no longer used to look up per-user provider settings).
            emit (Emitter): Async callable used to stream WS events to the client.
            model (str | None): Optional per-call model selection (from the composer's
                model chip); beats the conversation doc's persisted `selected_model`,
                which beats `Settings.default_model` — same resolution as `run_turn`, so
                compaction always runs on the model the user actually has selected.

        Returns:
            None: Streams events and mutates Firestore as side effects; no return value.
        """
        lock = get_conversation_lock(conversation_id)
        if lock.locked():
            # Same non-blocking guard as run_turn: a concurrent agent turn already holds
            # the lock, so compacting now would race its own build_context call.
            await emit(
                {
                    "type": "error",
                    "message": "Agent is busy — wait for the current run to finish before compacting.",
                    "recoverable": True,
                }
            )
            return

        async with lock:
            # Resolve the effective model: frame value -> conversation doc's persisted
            # selection -> server default. No more per-user settings lookup.
            conversation = fs.get_conversation(conversation_id) or {}
            effective_model = model or conversation.get("selected_model")
            _provider_name, model_id = resolve_model(effective_model, self._settings)
            if model_id != conversation.get("selected_model"):
                # Persist the resolved selection so it's restored on reconnect, mirroring
                # _run_turn_inner's persistence.
                fs.update_conversation(conversation_id, {"selected_model": model_id})
            llm = get_llm_provider(model_id, self._settings)

            profile = fs.get_profile(owner_uid)
            synthesized_profile = profile.get("synthesized_profile") if profile else None
            state = fs.get_agent_state(curriculum_id) or {
                "phase": "intake",
                "task_queue": [],
                "scratchpad": "",
                "iteration_count": 0,
            }
            phase = state.get("phase", "intake")

            # Tracks whether on_compaction actually fired this call — build_context skips
            # compaction entirely (even with force_compact=True) if there aren't enough
            # candidate messages to make folding meaningful (see its >2 guard).
            compaction_fired = False

            async def on_compaction(summary: str, before: int, after: int, compacted_through: str) -> None:
                """Forward the compaction result (full rolling summary) and flag that it ran."""
                nonlocal compaction_fired
                compaction_fired = True
                await emit(
                    {
                        "type": "compaction",
                        # Full summary text — the client's chip dropdown scrolls it.
                        "summary": summary,
                        "tokens_before": before,
                        "tokens_after": after,
                        "compacted_through": compacted_through,
                    }
                )

            async def on_compaction_start(before: int) -> None:
                """Forward the compaction-starting event so the client can show a spinner chip."""
                await emit({"type": "compaction_start", "tokens_before": before})

            async def on_context_usage(tokens: int) -> None:
                """Forward the resulting context-token estimate for the composer's usage warning."""
                await emit(
                    {
                        "type": "context_usage",
                        "tokens": tokens,
                        "limit": self._settings.context_token_limit,
                        "threshold": COMPACTION_TRIGGER_FRACTION,
                    }
                )

            # Discard the returned message list — this call's only purpose is the
            # persisted-summary side effect, not to actually send anything to an LLM.
            await self._memory.build_context(
                conversation_id=conversation_id,
                curriculum_id=curriculum_id,
                phase=phase,
                synthesized_profile=synthesized_profile,
                profile=profile,
                agent_state=state,
                compaction_llm=llm,
                force_compact=True,
                on_compaction=on_compaction,
                on_compaction_start=on_compaction_start,
                on_context_usage=on_context_usage,
            )

            if not compaction_fired:
                await emit(
                    {
                        "type": "error",
                        "message": "Not enough conversation history to compact yet.",
                        "recoverable": True,
                    }
                )

    async def _run_turn_inner(
        self,
        *,
        conversation_id: str,
        curriculum_id: str,
        owner_uid: str,
        user_input: str | PlanDecision | None,
        emit: Emitter,
        cancel_event: asyncio.Event,
        model: str | None,
        search_provider: str | None,
        run_started: float,
    ) -> RunResult:
        """Run the actual ReAct loop body, already holding the per-conversation lock.

        Implements the per-iteration cycle documented in `app/agent/CLAUDE.md`:
        `build_context -> chat_stream -> route reasoning/text deltas -> execute tool
        calls -> check HITL gate -> loop or return`. Re-reads `phase` fresh from Firestore at the
        top of every iteration (a `transition_phase` call from a tool executed in a prior
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
            model (str | None): Optional per-call model selection (composer chip);
                resolved against the conversation doc's persisted `selected_model` and
                `Settings.default_model` — see the resolution block below.
            search_provider (str | None): Optional per-call search provider selection
                (composer chip); resolved against the conversation doc's persisted
                `search_provider` and `DEFAULT_SEARCH_PROVIDER`.
            run_started (float): `time.monotonic()` timestamp captured by `run_turn`
                right before this call, used to compute the server-measured
                `elapsed_ms` stamped on `agent_done` and on the run's tail message.

        Returns:
            RunResult: The terminal outcome (DONE/PAUSED/CANCELLED/ERROR) for this turn.
        """

        def _elapsed_ms() -> int:
            """Return milliseconds elapsed since this run started."""
            return int((time.monotonic() - run_started) * 1000)

        # Id of the assistant message most recently persisted this run — set after every
        # assistant-role append_message call below so _finish_run knows which message is
        # this run's tail (the one to stamp run_elapsed_ms onto).
        last_assistant_msg_id: str | None = None

        async def _finish_run(status: str) -> int:
            """Stamp elapsed time on the run's tail message and emit the terminal agent_done.

            The tail message is often only known to be the tail AFTER it was persisted
            (pause/max-iterations/cancel all persist mid-loop), so a merge-update here is
            the uniform way to stamp `run_elapsed_ms` regardless of which path finished.

            Args:
                status (str): The terminal status to report on the `agent_done` event
                    ("ok" | "paused" | "cancelled" | "max_iterations" | "error").

            Returns:
                int: The computed elapsed milliseconds, for callers that also want it.
            """
            elapsed = _elapsed_ms()
            if last_assistant_msg_id is not None:
                fs.update_message(conversation_id, last_assistant_msg_id, {"run_elapsed_ms": elapsed})
            await emit({"type": "agent_done", "status": status, "elapsed_ms": elapsed})
            return elapsed

        # Resolve model/search provider: frame value (this call's `model`/
        # `search_provider` args) wins, else the conversation doc's persisted
        # selection, else the server default — no more per-user settings lookup.
        conversation_doc = fs.get_conversation(conversation_id) or {}
        effective_model = model or conversation_doc.get("selected_model")
        _provider_name, resolved_model = resolve_model(effective_model, self._settings)
        resolved_search = resolve_search_provider(
            search_provider or conversation_doc.get("search_provider"), self._settings
        )
        # Persist the resolved values when they differ from what's stored, so the next
        # reconnect/run picks up the same selection without the client resending it.
        persist_fields: dict[str, Any] = {}
        if resolved_model != conversation_doc.get("selected_model"):
            persist_fields["selected_model"] = resolved_model
        if resolved_search != conversation_doc.get("search_provider"):
            persist_fields["search_provider"] = resolved_search
        if persist_fields:
            fs.update_conversation(conversation_id, persist_fields)

        llm = get_llm_provider(resolved_model, self._settings)
        search = get_search_provider(resolved_search, self._settings)

        # Record the incoming user turn (unless this is a plan_decision resume, which has
        # no new chat message of its own — it's handled as a synthetic tool observation).
        if isinstance(user_input, str):
            fs.append_message(conversation_id, {"role": "user", "content": user_input})
            # A plain string user_input is either a normal chat message or the reply to a
            # pending request_user_input question (option click or free text both arrive
            # this way) — either way, clear the persisted question so a reconnecting
            # client stops replaying an already-answered card.
            fs.set_agent_state(curriculum_id, {"pending_user_input": None})
        elif isinstance(user_input, PlanDecision):
            await self._apply_plan_decision(conversation_id, curriculum_id, user_input, emit)
            await emit({"type": "curriculum_updated", "curriculum_id": curriculum_id, "scope": "curriculum"})

        profile = fs.get_profile(owner_uid)
        synthesized_profile = profile.get("synthesized_profile") if profile else None

        state = fs.get_agent_state(curriculum_id) or {"phase": "intake", "task_queue": [], "scratchpad": "", "iteration_count": 0}
        phase = state.get("phase", "intake")

        # Shared across every iteration's AgentContext for this run only (not persisted)
        # so save_sources can reuse pages fetch_url already fetched earlier this run.
        page_cache: dict[str, dict[str, Any]] = {}

        max_iterations = self._settings.agent_max_iterations

        for iteration in range(max_iterations):
            # Cooperative cancellation check #1: before starting a new iteration at all.
            # (See below for check #2, mid-stream, and the post-stream re-check.)
            if cancel_event.is_set():
                fs.set_agent_state(curriculum_id, {"iteration_count": iteration})
                await _finish_run("cancelled")
                return RunResult(TurnOutcome.CANCELLED)

            # Re-read phase fresh from Firestore every iteration (not cached from the
            # loop's start) — a `transition_phase` tool call in the previous iteration
            # must be visible here so the next iteration uses the new phase's tools/prompt.
            state = fs.get_agent_state(curriculum_id) or state
            phase = state.get("phase", phase)

            async def on_compaction(summary: str, before: int, after: int, compacted_through: str) -> None:
                """Forward a compaction event to the client via the outer `emit`.

                Args:
                    summary (str): The FULL new rolling summary text (untruncated — the
                        client renders it in a scroll-capped expandable panel).
                    before (int): Estimated token count before compaction.
                    after (int): Estimated token count after compaction.
                    compacted_through (str): Id of the last message folded into the
                        summary — lets the client anchor the resolved chip in the
                        transcript at the right position.
                """
                await emit(
                    {
                        "type": "compaction",
                        "summary": summary,
                        "tokens_before": before,
                        "tokens_after": after,
                        "compacted_through": compacted_through,
                    }
                )

            async def on_compaction_start(before: int) -> None:
                """Forward the compaction-starting event so the client can show a spinner chip.

                Fired right before the (potentially slow) small-model summarization call,
                so the in-progress state is visible immediately rather than only once
                compaction finishes.

                Args:
                    before (int): Estimated token count of the context about to be compacted.
                """
                await emit({"type": "compaction_start", "tokens_before": before})

            async def on_context_usage(tokens: int) -> None:
                """Forward the current context-token estimate for the composer's usage warning.

                Fired at the end of every `build_context` call (compacted or not) so the
                client can render the "Context X% full" card once usage crosses the warn
                threshold, ahead of auto-compaction actually triggering.

                Args:
                    tokens (int): The final token estimate of the context this iteration.
                """
                await emit(
                    {
                        "type": "context_usage",
                        "tokens": tokens,
                        "limit": self._settings.context_token_limit,
                        "threshold": COMPACTION_TRIGGER_FRACTION,
                    }
                )

            messages = await self._memory.build_context(
                conversation_id=conversation_id,
                curriculum_id=curriculum_id,
                phase=phase,
                synthesized_profile=synthesized_profile,
                profile=profile,
                agent_state=state,
                compaction_llm=llm,
                on_compaction=on_compaction,
                on_compaction_start=on_compaction_start,
                on_context_usage=on_context_usage,
            )

            ctx = AgentContext(
                curriculum_id=curriculum_id,
                conversation_id=conversation_id,
                owner_uid=owner_uid,
                settings=self._settings,
                llm=llm,
                search=search,
                phase=phase,
                emit=emit,
                page_cache=page_cache,
            )

            message_id = fs.new_id()
            await emit({"type": "message_start", "message_id": message_id, "role": "assistant"})

            tool_specs = self._registry.specs_for_phase(phase)

            reasoning_acc = ""
            text_acc = ""
            tool_calls: list[ToolCallDelta] = []

            stream = llm.chat_stream(messages, tools=tool_specs)
            it = stream.__aiter__()

            async def _next() -> Any:
                """Advance the stream by one event, converting exhaustion to a sentinel.

                `asyncio.wait` (used by `_wait_cancellable`) needs a plain return value
                to distinguish "the task completed" from "the task raised" via
                `.result()`/`.exception()` — but `StopAsyncIteration` is how a normal,
                successful end-of-stream is signaled by `__anext__`, and we don't want
                `_wait_cancellable` to (mis)treat normal stream exhaustion as an error
                propagating from `coro_task.result()`. Converting it to `_STREAM_END`
                here lets the loop below just check for that sentinel like any other
                event type.

                Returns:
                    Any: The next `LLMEvent` from the stream, or the `_STREAM_END`
                        sentinel once the stream is exhausted.
                """
                try:
                    return await it.__anext__()
                except StopAsyncIteration:
                    return _STREAM_END

            try:
                while True:
                    # Cooperative cancellation check #2: race the stream chunk against
                    # cancel_event so a `stop` interrupts mid-wait (including prefill stalls).
                    cancelled, event = await _wait_cancellable(asyncio.create_task(_next()), cancel_event)
                    if cancelled:
                        break
                    if event is _STREAM_END:
                        break
                    if isinstance(event, ReasoningDelta):
                        # Provider-native reasoning (OpenAI-compat reasoning_content/
                        # reasoning field, or Gemini thought-summary parts) — forwarded
                        # 1:1 to the client as reasoning_delta.
                        reasoning_acc += event.text
                        await emit({"type": "reasoning_delta", "message_id": message_id, "delta": event.text})
                    elif isinstance(event, TextDelta):
                        text_acc += event.text
                        await emit({"type": "text_delta", "message_id": message_id, "delta": event.text})
                    elif isinstance(event, ToolCallDelta):
                        tool_calls.append(event)
                    elif isinstance(event, Done):
                        pass
            except Exception as exc:
                # _wait_cancellable re-raises stream errors via .result(), so this catches
                # genuine LLM failures exactly as before.
                logger.exception("LLM stream failed", extra={"extra_fields": {"conversation_id": conversation_id}})
                await emit({"type": "error", "message": f"LLM error: {exc}", "recoverable": True})
                await emit({"type": "message_end", "message_id": message_id})
                # BUG FIX: previously no agent_done fired on this path, leaving the client
                # stuck showing the run as "running" forever. This also stamps
                # run_elapsed_ms on any tail message persisted by earlier iterations.
                await _finish_run("error")
                return RunResult(TurnOutcome.ERROR, str(exc))
            finally:
                # If we broke out early due to cancellation, the async generator is still
                # "open" from the provider's/SDK's point of view — closing it here signals
                # the underlying HTTP stream to shut down instead of leaving it abandoned
                # (which would otherwise keep a local OpenAI-compatible server generating forever).
                # aclose() on an already-exhausted generator is a harmless no-op.
                with contextlib.suppress(Exception):
                    await stream.aclose()

            # Cooperative cancellation check #3: after the stream loop exits (whether via
            # natural completion or the mid-stream `break` above) — persists whatever
            # partial text/reasoning was accumulated before the cancellation was noticed,
            # rather than silently discarding it.
            if cancel_event.is_set():
                stored = fs.append_message(
                    conversation_id,
                    {"role": "assistant", "content": text_acc, "reasoning": reasoning_acc or None, "tool_calls": []},
                )
                last_assistant_msg_id = stored["id"]  # this run's tail message so far
                fs.set_agent_state(curriculum_id, {"iteration_count": iteration})
                await emit({"type": "message_end", "message_id": message_id})
                await _finish_run("cancelled")
                return RunResult(TurnOutcome.CANCELLED)

            if not tool_calls:
                # No tool calls this iteration means the model produced a final answer:
                # persist it and end the turn as DONE (no further looping needed).
                stored = fs.append_message(
                    conversation_id,
                    {"role": "assistant", "content": text_acc, "reasoning": reasoning_acc or None, "tool_calls": []},
                )
                last_assistant_msg_id = stored["id"]  # this run's (final) tail message
                await emit({"type": "message_end", "message_id": message_id})
                fs.set_agent_state(curriculum_id, {"iteration_count": iteration + 1})

                await _finish_run("ok")
                return RunResult(TurnOutcome.DONE)

            tool_call_records: list[dict[str, Any]] = []
            hit_hitl_gate = False
            tool_batch_cancelled = False
            # Set if any fetch_url call this batch succeeded — triggers a dedup pass over
            # stored fetch_url outputs after the batch is persisted (see below).
            any_fetch_succeeded = False
            # Set if any write/update_section (any status) or successful read_section call
            # ran this batch — triggers a dedup pass over stored section content (see below).
            any_section_content = False

            for tc in tool_calls:
                # Cancellation check: must stop the *rest* of batch from starting, else
                # remaining tool calls (e.g. slow fetch_url) run to completion.
                if cancel_event.is_set():
                    tool_batch_cancelled = True
                    break

                await emit(
                    {
                        "type": "tool_call_start",
                        "message_id": message_id,
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                )

                # Race tool execution against cancel_event to interrupt slow in-flight
                # calls (e.g. fetch_url).
                cancelled, result = await _wait_cancellable(
                    asyncio.create_task(self._registry.execute(tc.name, tc.arguments, ctx)),
                    cancel_event,
                )
                if cancelled:
                    # Partial Firestore writes acceptable: tools are merge-based or
                    # idempotent, so half-applied writes are not corrupt, just incomplete.
                    await emit(
                        {
                            "type": "tool_call_result",
                            "message_id": message_id,
                            "tool_call_id": tc.id,
                            "name": tc.name,
                            "output_full": '{"error": "cancelled by user"}',
                            "output_preview": '{"error": "cancelled by user"}',
                            "status": "error",
                            "elapsed_ms": 0,
                        }
                    )
                    tool_call_records.append(
                        {
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                            # Short error string — no separate full output to preserve.
                            "output_full": '{"error": "cancelled by user"}',
                            "output_preview": '{"error": "cancelled by user"}',
                            "status": "error",
                        }
                    )
                    tool_batch_cancelled = True
                    break

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
                # Track whether any fetch_url call in this batch succeeded — a single
                # dedup pass after the batch covers every fetch this turn.
                if tc.name == "fetch_url" and result.status == "ok":
                    any_fetch_succeeded = True
                # write/update inputs carry full section content even on error (e.g. a rejected
                # citation guard); a read only adds content when it succeeds.
                if tc.name in ("write_section", "update_section") or (
                    tc.name == "read_section" and result.status == "ok"
                ):
                    any_section_content = True

                # `output_full` is the complete tool result replayed to the model;
                # `output_preview` is a short slice for the client UI only.
                output_full = json.dumps(output, default=str)
                output_preview = output_full[:TOOL_OUTPUT_PREVIEW_CHARS]

                await emit(
                    {
                        "type": "tool_call_result",
                        "message_id": message_id,
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        # Client gets both: full output for expandable views, preview for
                        # compact ones.
                        "output_full": output_full,
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
                        # Full output for model replay; short preview for the client.
                        "output_full": output_full,
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

            if tool_batch_cancelled:
                # Persist what ran (including cancelled tool records) and end turn.
                stored = fs.append_message(
                    conversation_id,
                    {
                        "role": "assistant",
                        "content": text_acc,
                        "reasoning": reasoning_acc or None,
                        "tool_calls": tool_call_records,
                    },
                )
                last_assistant_msg_id = stored["id"]  # this run's tail message so far
                fs.set_agent_state(curriculum_id, {"iteration_count": iteration})
                await emit({"type": "message_end", "message_id": message_id})
                await _finish_run("cancelled")
                return RunResult(TurnOutcome.CANCELLED)

            stored = fs.append_message(
                conversation_id,
                {
                    "role": "assistant",
                    "content": text_acc,
                    "reasoning": reasoning_acc or None,
                    "tool_calls": tool_call_records,
                },
            )
            last_assistant_msg_id = stored["id"]  # this run's tail message so far
            await emit({"type": "message_end", "message_id": message_id})

            if any_fetch_succeeded:
                # Dedup fetch_url outputs: keep only the newest fetch of each URL in
                # context, so re-fetching the same URL later never duplicates content.
                strip_stale_fetch_url_outputs(conversation_id)

            if any_section_content:
                # Dedup section content: only the latest read/write of each section keeps
                # its markdown in context, so a section's content never appears twice.
                strip_stale_section_content(conversation_id)

            fs.set_agent_state(curriculum_id, {"iteration_count": iteration + 1})

            if hit_hitl_gate:
                # Pause immediately even if this wasn't the last tool call batched this
                # step and even if max_iterations hasn't been reached — a gate call
                # always ends the turn, per app/agent/CLAUDE.md.
                await _finish_run("paused")
                return RunResult(TurnOutcome.PAUSED)

            # Otherwise loop again: tool observations are now in context for next iteration.

        await emit(
            {
                "type": "error",
                "message": "Agent reached the maximum number of reasoning iterations for this turn.",
                "recoverable": True,
            }
        )
        await _finish_run("max_iterations")
        return RunResult(TurnOutcome.ERROR, "max iterations")

    async def _apply_plan_decision(
        self, conversation_id: str, curriculum_id: str, decision: PlanDecision, emit: Emitter
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
                feedback and leave the phase at "awaiting_approval"; the agent itself
                chooses, via `transition_phase`, whether to revise directly from
                `outline_planning` or gather more sources first via `deep_research`).
            emit (Emitter): Async callable used to stream `phase_change`/`progress`
                events live to the client — previously this transition only surfaced on
                the next reconnect snapshot, leaving the sticky phase banner stale. On
                "modify" no phase_change is emitted here; `transition_phase` emits its own
                once the agent picks a target phase.

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
            # Seed persisted progress counters here (not just via write_section later) so
            # the dashboard progress bar shows the correct total immediately on approval,
            # rather than staying at 0 until the first section is written.
            tasks = plan.get("tasks", [])
            done_count = sum(1 for t in tasks if t.get("status") == "done")
            fs.update_curriculum(curriculum_id, {
                "status": "writing",
                "progress": {
                    "phase": "writing",
                    "completed_tasks": done_count,
                    "total_tasks": len(tasks),
                    "detail": "Plan approved — writing sections",
                },
            })
            # Live WS events for the approval transition — mirrors the persisted state
            # above so a connected client updates immediately, not just on reconnect.
            await emit({"type": "phase_change", "phase": "writing", "label": PHASE_LABELS["writing"]})
            if tasks:
                await emit(
                    {
                        "type": "progress",
                        "completed": done_count,
                        "total": len(tasks),
                        "detail": "Plan approved — writing sections",
                    }
                )
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
            # Record feedback and mark the plan revising, but leave phase/status alone —
            # the agent now picks its own path (outline_planning vs. deep_research) via
            # transition_phase, which handles status + phase_change itself once it decides.
            feedback_list = plan.get("user_feedback", [])
            if decision.feedback:
                feedback_list.append(decision.feedback)
            fs.set_plan(curriculum_id, {"status": "revising", "user_feedback": feedback_list})
            fs.append_message(
                conversation_id,
                {
                    "role": "system",
                    "content": (
                        f"The user requested changes to the task plan with this feedback: "
                        f"{decision.feedback!r}. You are still in the 'awaiting_approval' phase "
                        f"and MUST now choose your next phase with transition_phase: if the "
                        f"feedback asks for topics or depth your saved sources do not cover, "
                        f"call transition_phase('deep_research') to research them first; "
                        f"otherwise call transition_phase('outline_planning'). Then revise the "
                        f"outline to address ALL accumulated feedback and re-propose it with "
                        f"propose_task_plan."
                    ),
                },
            )

    async def _materialize_modules_and_sections(self, curriculum_id: str, plan: dict[str, Any]) -> None:
        """Create module/section stub docs from the approved plan's tasks.

        Groups tasks by `module_ref`; each distinct module_ref becomes a module doc. Its
        title is taken from the plan's structured `modules` list (`{id, title, description}`,
        added by `propose_task_plan`'s `modules` field) — the module's real outline-authored
        display title, truncated to 80 chars for safety — when a matching non-empty entry
        exists. Legacy plans that predate the `modules` field (or that omit an entry for a
        given module_ref) fall back to the original heuristic: deriving the title from the
        first task referencing that module, truncated at any ':' separator and 80 chars.
        The module doc's `description` is likewise taken from the structured entry
        (stripped); legacy plans that predate the field (or omit an entry) get `""` — there
        is no title-style heuristic fallback for description since it isn't derivable from a
        task title. Each task becomes a "planned" section stub the writing phase will fill
        in. The section doc id is derived from the task id: under the binding `m{X}-s{Y}` id
        contract (see `tools/planning.py`'s `_validate_plan`), stripping the `m{X}-`
        prefix yields the section doc id (e.g. task `m1-s2` -> module doc `m1`, section
        doc `s2`); legacy plans whose task ids don't carry that prefix fall back to using
        the full task id verbatim as the section doc id. Idempotent with respect to
        already-materialized modules/sections (skips ids that already exist), so
        re-running this after a partial failure or a second approval of the same plan
        version does not duplicate stubs.

        Args:
            curriculum_id (str): The curriculum to create module/section stubs under.
            plan (dict[str, Any]): The approved plan document, whose `tasks` list
                (each with `id`, `title`, optional `module_ref`) drives stub creation,
                and whose optional `modules` list (`{id, title, description}`) supplies
                each module's real display title and summary.

        Returns:
            None: Creates Firestore module/section documents as a side effect.
        """
        tasks = plan.get("tasks", [])
        module_order: dict[str, int] = {}
        module_titles: dict[str, str] = {}
        module_descriptions: dict[str, str] = {}

        # Structured entries keyed by module id, from the plan's `modules` list — the
        # source of truth for module doc title/description.
        structured_entries = {m["id"]: m for m in plan.get("modules", []) or []}

        # First pass: discover distinct module_refs in task order, assigning each a
        # stable order index and resolving its title/description — prefer the structured
        # plan entry; legacy plans without a matching `modules` entry fall back to
        # deriving the title from the first task referencing this module (truncated at
        # any ':' separator), with description defaulting to "" (not derivable from a
        # task title).
        for t in tasks:
            module_ref = t.get("module_ref")
            if not module_ref:
                continue
            if module_ref not in module_order:
                module_order[module_ref] = len(module_order)
                entry = structured_entries.get(module_ref) or {}
                structured_title = entry.get("title")
                module_titles[module_ref] = (
                    structured_title[:80]
                    if structured_title
                    else t.get("title", module_ref).split(":")[0][:80]
                )
                module_descriptions[module_ref] = (entry.get("description") or "").strip()

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
                    "description": module_descriptions[module_id],
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
            # Derive the section doc id by stripping the "m{X}-" prefix from the task id
            # (new convention); fall back to the full task id for legacy plans that
            # don't carry that prefix, so old curricula stay readable.
            task_id = t["id"]
            prefix = f"{module_ref}-"
            section_id = task_id[len(prefix):] if task_id.startswith(prefix) else task_id
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
