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
        self._events = events

    async def chat_stream(self, messages, tools=None, small: bool = False):
        for event in self._events:
            yield event

    async def complete(self, messages, small: bool = False) -> str:
        return "stub completion"


class StubSearch:
    async def search(self, query: str, max_results: int = 8):
        return []


@pytest.fixture()
def orchestrator(settings) -> Orchestrator:
    return Orchestrator(settings)


def _setup_conversation(fake_fs, phase: str = "outline_planning"):
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
