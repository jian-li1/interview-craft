"""Orchestrator ReAct loop: HITL pause on propose_task_plan, plain-text DONE turn,
and cancellation, all against the in-memory fake Firestore with a scripted fake LLM
(no real network/provider credentials).
"""

from __future__ import annotations

import pytest

from app.agent.orchestrator import Orchestrator, PlanDecision, TurnOutcome
from app.services.llm.base import Done, TextDelta, ToolCallDelta


class ScriptedLLM:
    """Fake LLMProvider: chat_stream yields a pre-scripted sequence of events, once."""

    def __init__(self, events: list) -> None:
        """Store the fixed sequence of streaming events to replay.

        Args:
            events (list): Sequence of `TextDelta`/`ToolCallDelta`/`Done` events that
                `chat_stream` will yield, in order, on its single supported call.
        """
        self._events = events

    async def chat_stream(self, messages, tools=None, small: bool = False):
        """Yield the pre-scripted events in order, ignoring the actual arguments.

        Args:
            messages: Chat messages that would have been sent to a real provider.
            tools: Tool specs that would have been sent to a real provider.
            small (bool): Unused; present to match the `LLMProvider` protocol signature.

        Yields:
            The scripted event objects, in the order supplied at construction time.
        """
        for event in self._events:
            yield event

    async def complete(self, messages, small: bool = False) -> str:
        """Return a fixed stub string instead of calling a real completion endpoint.

        Args:
            messages: Chat messages that would have been sent to a real provider.
            small (bool): Unused; present to match the `LLMProvider` protocol signature.

        Returns:
            str: The literal string "stub completion".
        """
        return "stub completion"


class StubSearch:
    """Fake search provider that always returns no results, avoiding network calls."""

    async def search(self, query: str, max_results: int = 8):
        """Return an empty result list regardless of the query.

        Args:
            query (str): Search query (ignored).
            max_results (int): Maximum results requested (ignored).

        Returns:
            list: Always an empty list.
        """
        return []


@pytest.fixture()
def orchestrator(settings) -> Orchestrator:
    """Construct an `Orchestrator` wired to the real (test) app settings.

    Args:
        settings: The `settings` fixture from conftest.py.

    Returns:
        Orchestrator: An orchestrator instance ready to run turns against the
            in-memory fake Firestore and a scripted fake LLM.
    """
    return Orchestrator(settings)


def _setup_conversation(fake_fs, phase: str = "outline_planning"):
    """Seed a conversation, curriculum, and agent state at a given phase.

    Args:
        fake_fs: The `fake_fs` fixture, used to seed the in-memory store directly.
        phase (str): Agent phase to initialize the persisted state with.

    Returns:
        tuple: A `(conversation_dict, curriculum_dict)` pair for the newly created docs.
    """
    conv = fake_fs.fs.create_conversation("uid1", "Test chat", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "Test curriculum", "prep me for a SWE interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.set_agent_state(
        curriculum["id"],
        {"phase": phase, "task_queue": [], "current_task_id": None, "scratchpad": "", "iteration_count": 0},
    )
    return conv, curriculum


@pytest.mark.asyncio
async def test_run_turn_pauses_on_hitl_gate_tool_call(monkeypatch, fake_fs, orchestrator):
    """Verify calling `propose_task_plan` pauses the turn (HITL gate), streams the
    expected event sequence ending in `agent_done`/paused, and persists the plan with
    the curriculum status flipped to "awaiting_approval".
    """
    conv, curriculum = _setup_conversation(fake_fs, phase="outline_planning")

    scripted = ScriptedLLM(
        [
            TextDelta(text="<thinking>proposing a plan</thinking>Here is my proposed outline."),
            ToolCallDelta(
                id="call_1",
                name="propose_task_plan",
                arguments={
                    "outline_markdown": "# Outline\n\n## Module 1",
                    "tasks": [{"id": "m1-s1", "title": "Intro", "module_ref": "m1"}],
                },
            ),
            Done(),
        ]
    )
    monkeypatch.setattr("app.agent.orchestrator.get_llm_provider", lambda *a, **k: scripted)
    monkeypatch.setattr("app.agent.orchestrator.get_search_provider", lambda *a, **k: StubSearch())

    events = []

    async def emit(event):
        events.append(event)

    result = await orchestrator.run_turn(
        conversation_id=conv["id"],
        curriculum_id=curriculum["id"],
        owner_uid="uid1",
        user_input="please propose a plan",
        emit=emit,
    )

    assert result.outcome == TurnOutcome.PAUSED

    event_types = [e["type"] for e in events]
    assert "message_start" in event_types
    assert "reasoning_delta" in event_types
    assert "text_delta" in event_types
    assert "tool_call_start" in event_types
    assert "tool_call_result" in event_types
    assert "plan_proposed" in event_types
    assert event_types[-1] == "agent_done"
    assert events[-1]["status"] == "paused"

    # Plan and curriculum status persisted.
    plan = fake_fs.fs.get_plan(curriculum["id"])
    assert plan is not None
    assert plan["status"] == "proposed"
    updated_curriculum = fake_fs.fs.get_curriculum(curriculum["id"])
    assert updated_curriculum["status"] == "awaiting_approval"


@pytest.mark.asyncio
async def test_run_turn_plain_text_answer_completes_done(monkeypatch, fake_fs, orchestrator):
    """Verify a plain-text LLM response (no tool calls) completes the turn as DONE,
    splitting `<thinking>` reasoning from user-facing content in the saved message.
    """
    conv, curriculum = _setup_conversation(fake_fs, phase="refinement")

    scripted = ScriptedLLM(
        [
            TextDelta(text="<thinking>just answer</thinking>Sure, here's an explanation."),
            Done(),
        ]
    )
    monkeypatch.setattr("app.agent.orchestrator.get_llm_provider", lambda *a, **k: scripted)
    monkeypatch.setattr("app.agent.orchestrator.get_search_provider", lambda *a, **k: StubSearch())

    events = []

    async def emit(event):
        events.append(event)

    result = await orchestrator.run_turn(
        conversation_id=conv["id"],
        curriculum_id=curriculum["id"],
        owner_uid="uid1",
        user_input="explain module 2",
        emit=emit,
    )

    assert result.outcome == TurnOutcome.DONE
    assert events[-1] == {"type": "agent_done", "status": "ok"}

    messages = fake_fs.fs.list_messages(conv["id"])
    # user message + assistant message appended
    assert any(m["role"] == "user" and m["content"] == "explain module 2" for m in messages)
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == "Sure, here's an explanation."
    assert assistant_msgs[0]["reasoning"] == "just answer"


@pytest.mark.asyncio
async def test_run_turn_applies_plan_decision_approve_and_materializes(monkeypatch, fake_fs, orchestrator):
    """Verify approving a proposed plan transitions the curriculum/state to "writing",
    materializes modules from the plan's tasks, and emits a `curriculum_updated` event.
    """
    conv, curriculum = _setup_conversation(fake_fs, phase="awaiting_approval")
    fake_fs.fs.set_plan(
        curriculum["id"],
        {
            "version": 1,
            "outline_markdown": "# Outline",
            "tasks": [
                {"id": "m1-s1", "title": "Intro", "module_ref": "m1", "status": "pending"},
                {"id": "m1-s2", "title": "Basics", "module_ref": "m1", "status": "pending"},
            ],
            "status": "proposed",
            "user_feedback": [],
        },
    )

    scripted = ScriptedLLM([TextDelta(text="Great, let's get writing!"), Done()])
    monkeypatch.setattr("app.agent.orchestrator.get_llm_provider", lambda *a, **k: scripted)
    monkeypatch.setattr("app.agent.orchestrator.get_search_provider", lambda *a, **k: StubSearch())

    events = []

    async def emit(event):
        events.append(event)

    result = await orchestrator.run_turn(
        conversation_id=conv["id"],
        curriculum_id=curriculum["id"],
        owner_uid="uid1",
        user_input=PlanDecision(decision="approve", feedback=None),
        emit=emit,
    )

    assert result.outcome == TurnOutcome.DONE

    updated_curriculum = fake_fs.fs.get_curriculum(curriculum["id"])
    assert updated_curriculum["status"] == "writing"

    state = fake_fs.fs.get_agent_state(curriculum["id"])
    assert state["phase"] == "writing"
    assert state["task_queue"] == ["m1-s1", "m1-s2"]

    modules = fake_fs.fs.list_modules(curriculum["id"])
    assert any(m["id"] == "m1" for m in modules)

    curriculum_updated_events = [e for e in events if e["type"] == "curriculum_updated"]
    assert len(curriculum_updated_events) == 1
    assert curriculum_updated_events[0] == {
        "type": "curriculum_updated",
        "curriculum_id": curriculum["id"],
        "scope": "curriculum",
    }


@pytest.mark.asyncio
async def test_plan_decision_approve_appends_system_message_with_approved(monkeypatch, fake_fs, orchestrator):
    """Verify approving a plan appends exactly one system message recording the
    approval, mentioning "APPROVED" and the approved plan's version number.
    """
    conv, curriculum = _setup_conversation(fake_fs, phase="awaiting_approval")
    fake_fs.fs.set_plan(
        curriculum["id"],
        {
            "version": 2,
            "outline_markdown": "# Outline",
            "tasks": [{"id": "m1-s1", "title": "Intro", "module_ref": "m1", "status": "pending"}],
            "status": "proposed",
            "user_feedback": [],
        },
    )

    scripted = ScriptedLLM([TextDelta(text="Great, let's get writing!"), Done()])
    monkeypatch.setattr("app.agent.orchestrator.get_llm_provider", lambda *a, **k: scripted)
    monkeypatch.setattr("app.agent.orchestrator.get_search_provider", lambda *a, **k: StubSearch())

    async def emit(event):
        pass

    result = await orchestrator.run_turn(
        conversation_id=conv["id"],
        curriculum_id=curriculum["id"],
        owner_uid="uid1",
        user_input=PlanDecision(decision="approve", feedback=None),
        emit=emit,
    )
    assert result.outcome == TurnOutcome.DONE

    messages = fake_fs.fs.list_messages(conv["id"])
    system_msgs = [m for m in messages if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert "APPROVED" in system_msgs[0]["content"]
    assert "v2" in system_msgs[0]["content"]


@pytest.mark.asyncio
async def test_plan_decision_modify_appends_system_message_with_feedback(monkeypatch, fake_fs, orchestrator):
    """Verify requesting plan modifications appends a system message containing the
    user's feedback text, and still fires `curriculum_updated` to keep the client in sync.
    """
    conv, curriculum = _setup_conversation(fake_fs, phase="awaiting_approval")
    fake_fs.fs.set_plan(
        curriculum["id"],
        {
            "version": 1,
            "outline_markdown": "# Outline",
            "tasks": [{"id": "m1-s1", "title": "Intro", "module_ref": "m1", "status": "pending"}],
            "status": "proposed",
            "user_feedback": [],
        },
    )

    scripted = ScriptedLLM([TextDelta(text="Sure, let me revise the outline."), Done()])
    monkeypatch.setattr("app.agent.orchestrator.get_llm_provider", lambda *a, **k: scripted)
    monkeypatch.setattr("app.agent.orchestrator.get_search_provider", lambda *a, **k: StubSearch())

    events = []

    async def emit(event):
        events.append(event)

    result = await orchestrator.run_turn(
        conversation_id=conv["id"],
        curriculum_id=curriculum["id"],
        owner_uid="uid1",
        user_input=PlanDecision(decision="modify", feedback="Add more system design content"),
        emit=emit,
    )
    assert result.outcome == TurnOutcome.DONE

    messages = fake_fs.fs.list_messages(conv["id"])
    system_msgs = [m for m in messages if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert "Add more system design content" in system_msgs[0]["content"]

    # curriculum_updated fires on modify too (harmless — keeps client status in sync).
    curriculum_updated_events = [e for e in events if e["type"] == "curriculum_updated"]
    assert len(curriculum_updated_events) == 1
    assert curriculum_updated_events[0]["curriculum_id"] == curriculum["id"]


@pytest.mark.asyncio
async def test_run_turn_rejects_concurrent_run_on_same_conversation(monkeypatch, fake_fs, orchestrator):
    """Simulate a run already holding the conversation lock: a second run_turn call must
    be rejected with an error rather than interleaving with the first.

    Confirms the one-active-run-per-conversation invariant enforced via the
    per-conversation asyncio lock returned by `get_conversation_lock`.
    """
    conv, curriculum = _setup_conversation(fake_fs, phase="refinement")

    from app.agent.orchestrator import get_conversation_lock

    lock = get_conversation_lock(conv["id"])
    await lock.acquire()
    try:
        events = []

        async def emit(event):
            events.append(event)

        result = await orchestrator.run_turn(
            conversation_id=conv["id"],
            curriculum_id=curriculum["id"],
            owner_uid="uid1",
            user_input="hello",
            emit=emit,
        )
        assert result.outcome == TurnOutcome.ERROR
        assert any(e["type"] == "error" for e in events)
    finally:
        lock.release()


@pytest.mark.asyncio
async def test_run_turn_cancels_mid_tool_call(monkeypatch, fake_fs, orchestrator):
    """Verify a `stop` frame that arrives while a tool call is still in-flight (e.g. a
    slow `fetch_url`) aborts the tool batch immediately rather than waiting for it to
    finish, emits an error-status `tool_call_result` for the aborted call, and ends the
    turn as CANCELLED — the `_wait_cancellable` race in `_run_turn_inner`'s tool-batch
    loop (see orchestrator.py item B.3) is what's under test here.
    """
    import asyncio

    from app.agent.orchestrator import _cancel_events

    conv, curriculum = _setup_conversation(fake_fs, phase="deep_research")

    # Script a single tool call (web_search) followed by Done — the fake registry
    # execute() below never actually returns normally; it hangs until cancelled so we
    # can deterministically simulate "cancellation arrives mid-tool-call".
    scripted = ScriptedLLM(
        [
            TextDelta(text="<thinking>searching</thinking>Let me look that up."),
            ToolCallDelta(id="call_1", name="web_search", arguments={"query": "system design interview"}),
            Done(),
        ]
    )
    monkeypatch.setattr("app.agent.orchestrator.get_llm_provider", lambda *a, **k: scripted)
    monkeypatch.setattr("app.agent.orchestrator.get_search_provider", lambda *a, **k: StubSearch())

    cancel_event = _cancel_events[conv["id"]]

    async def slow_execute(tool_name, raw_input, ctx):
        """Simulate a tool call that never completes on its own — only cancellation
        (via the cancel_event, set by the `stop` frame) ends it, standing in for a
        real slow tool such as `fetch_url` stalling on a slow remote server.
        """
        # Signal cancellation once we're confirmed to be "inside" tool execution, then
        # hang until asyncio.wait's caller (_wait_cancellable) cancels this task.
        cancel_event.set()
        await asyncio.sleep(3600)
        raise AssertionError("slow_execute should have been cancelled before waking up")

    monkeypatch.setattr(orchestrator._registry, "execute", slow_execute)

    events = []

    async def emit(event):
        events.append(event)

    result = await orchestrator.run_turn(
        conversation_id=conv["id"],
        curriculum_id=curriculum["id"],
        owner_uid="uid1",
        user_input="find me some resources",
        emit=emit,
    )

    assert result.outcome == TurnOutcome.CANCELLED

    tool_results = [e for e in events if e["type"] == "tool_call_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["status"] == "error"
    assert tool_results[0]["tool_call_id"] == "call_1"
    assert "cancelled" in tool_results[0]["output_preview"]

    assert events[-1] == {"type": "agent_done", "status": "cancelled"}

    # The aborted call's record was still persisted so the next turn's context reflects
    # what actually happened this iteration.
    messages = fake_fs.fs.list_messages(conv["id"])
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["tool_calls"][0]["status"] == "error"
