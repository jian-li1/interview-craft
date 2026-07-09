"""Orchestrator ReAct loop: HITL pause on propose_task_plan, plain-text DONE turn,
and cancellation, all against the in-memory fake Firestore with a scripted fake LLM
(no real network/provider credentials).
"""

from __future__ import annotations

import pytest

from app.agent.orchestrator import Orchestrator, PlanDecision, TurnOutcome
from app.services.llm.base import Done, ReasoningDelta, TextDelta, ToolCallDelta


class ScriptedLLM:
    """Fake LLMProvider: chat_stream yields a pre-scripted sequence of events, once."""

    def __init__(self, events: list) -> None:
        """Store the fixed sequence of streaming events to replay.

        Args:
            events (list): Sequence of `ReasoningDelta`/`TextDelta`/`ToolCallDelta`/`Done`
                events that `chat_stream` will yield, in order, on its single supported call.
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
            ReasoningDelta(text="proposing a plan"),
            TextDelta(text="Here is my proposed outline."),
            ToolCallDelta(
                id="call_1",
                name="propose_task_plan",
                arguments={
                    # "Section 1.1" label is required so propose_task_plan's outline<->tasks
                    # cross-check matches this against task id "m1-s1".
                    "outline_markdown": "# Outline\n\n## Module 1\n\nSection 1.1: Intro",
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

    # phase_change/progress must be emitted live (not just on reconnect) so the sticky
    # phase banner updates immediately when the plan is proposed, and both must arrive
    # before plan_proposed so the client's phase/progress state is current when the
    # approval card renders.
    phase_change_events = [e for e in events if e["type"] == "phase_change"]
    assert len(phase_change_events) == 1
    assert phase_change_events[0]["phase"] == "awaiting_approval"
    progress_events = [e for e in events if e["type"] == "progress"]
    assert len(progress_events) == 1
    assert progress_events[0] == {"type": "progress", "completed": 0, "total": 1, "detail": ""}
    assert event_types.index("phase_change") < event_types.index("plan_proposed")
    assert event_types.index("progress") < event_types.index("plan_proposed")

    # Plan and curriculum status persisted.
    plan = fake_fs.fs.get_plan(curriculum["id"])
    assert plan is not None
    assert plan["status"] == "proposed"
    updated_curriculum = fake_fs.fs.get_curriculum(curriculum["id"])
    assert updated_curriculum["status"] == "awaiting_approval"
    # REST readers (dashboard) must see the same progress counters as the live WS event.
    assert updated_curriculum["progress"] == {
        "phase": "awaiting_approval",
        "completed_tasks": 0,
        "total_tasks": 1,
        "detail": "",
    }


@pytest.mark.asyncio
async def test_run_turn_request_user_input_emits_event_and_persists_state(monkeypatch, fake_fs, orchestrator):
    """Verify calling `request_user_input` emits a `user_input_requested` WS event
    carrying question+options, persists `pending_user_input` in the agent state doc,
    and still pauses the turn as PAUSED (the HITL gate).
    """
    conv, curriculum = _setup_conversation(fake_fs, phase="intake")

    scripted = ScriptedLLM(
        [
            TextDelta(text="I need to clarify something first."),
            ToolCallDelta(
                id="call_1",
                name="request_user_input",
                arguments={"question": "Which language track?", "options": ["Python", "Java"]},
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
        user_input="I'm not sure which track to pick",
        emit=emit,
    )

    assert result.outcome == TurnOutcome.PAUSED

    # Dedicated WS event, not just a generic tool_call_result, carries the question card data.
    question_events = [e for e in events if e["type"] == "user_input_requested"]
    assert len(question_events) == 1
    assert question_events[0]["question"] == "Which language track?"
    assert question_events[0]["options"] == ["Python", "Java"]

    # Persisted so a reconnecting client can restore the card.
    state = fake_fs.fs.get_agent_state(curriculum["id"])
    assert state["pending_user_input"] == {"question": "Which language track?", "options": ["Python", "Java"]}


@pytest.mark.asyncio
async def test_run_turn_string_input_clears_pending_user_input(monkeypatch, fake_fs, orchestrator):
    """Verify a subsequent `run_turn` with a plain string `user_input` clears
    `pending_user_input` from the agent state — the user's reply answers/dismisses
    a previously-pending `request_user_input` question.
    """
    conv, curriculum = _setup_conversation(fake_fs, phase="intake")
    # Seed a pending question as if a prior turn had paused on request_user_input.
    fake_fs.fs.set_agent_state(
        curriculum["id"], {"pending_user_input": {"question": "Which language track?", "options": None}}
    )

    scripted = ScriptedLLM([TextDelta(text="Got it, thanks."), Done()])
    monkeypatch.setattr("app.agent.orchestrator.get_llm_provider", lambda *a, **k: scripted)
    monkeypatch.setattr("app.agent.orchestrator.get_search_provider", lambda *a, **k: StubSearch())

    async def emit(event):
        pass

    result = await orchestrator.run_turn(
        conversation_id=conv["id"],
        curriculum_id=curriculum["id"],
        owner_uid="uid1",
        user_input="Python please",
        emit=emit,
    )

    assert result.outcome == TurnOutcome.DONE
    state = fake_fs.fs.get_agent_state(curriculum["id"])
    assert state["pending_user_input"] is None


@pytest.mark.asyncio
async def test_run_turn_plain_text_answer_completes_done(monkeypatch, fake_fs, orchestrator):
    """Verify a plain-text LLM response (no tool calls) completes the turn as DONE,
    with provider-native reasoning and user-facing content saved separately in the message.
    """
    conv, curriculum = _setup_conversation(fake_fs, phase="refinement")

    scripted = ScriptedLLM(
        [
            ReasoningDelta(text="just answer"),
            TextDelta(text="Sure, here's an explanation."),
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
    materializes modules from the plan's tasks, emits a `curriculum_updated` event, and
    seeds the curriculum doc's persisted `progress` counters from the plan's tasks.
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
    # Progress must be seeded immediately on approval (not left at 0 until the first
    # write_section) — total_tasks counts ALL plan tasks, not just the pending queue.
    assert updated_curriculum["progress"]["total_tasks"] == 2
    assert updated_curriculum["progress"]["completed_tasks"] == 0
    assert updated_curriculum["progress"]["phase"] == "writing"

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

    # phase_change/progress must be emitted live on approval, not only via reconnect
    # snapshot, else the client stays stuck showing "awaiting_approval" until reload.
    phase_change_events = [e for e in events if e["type"] == "phase_change"]
    assert len(phase_change_events) == 1
    assert phase_change_events[0]["phase"] == "writing"
    progress_events = [e for e in events if e["type"] == "progress"]
    assert len(progress_events) == 1
    assert progress_events[0]["completed"] == 0
    assert progress_events[0]["total"] == 2


@pytest.mark.asyncio
async def test_materialize_modules_and_sections_derives_section_ids_from_task_ids(fake_fs, orchestrator):
    """Approved tasks m1-s1, m1-s2, m2-s1 must materialize module docs m1/m2 and, under
    each, section docs whose ids are the task id's suffix after stripping "m{X}-"
    (s1/s2 under m1, s1 under m2) — not the full task id. Also verifies idempotency:
    calling materialization twice does not duplicate or reset anything.
    """
    plan = {
        "version": 1,
        "outline_markdown": "# Outline",
        "tasks": [
            {"id": "m1-s1", "title": "Intro", "module_ref": "m1", "status": "pending"},
            {"id": "m1-s2", "title": "Basics", "module_ref": "m1", "status": "pending"},
            {"id": "m2-s1", "title": "Practice", "module_ref": "m2", "status": "pending"},
        ],
        "status": "approved",
    }
    curriculum = fake_fs.fs.create_curriculum("uid1", "Test", "prep me", conversation_id="conv1")

    await orchestrator._materialize_modules_and_sections(curriculum["id"], plan)

    modules = {m["id"] for m in fake_fs.fs.list_modules(curriculum["id"])}
    assert modules == {"m1", "m2"}

    m1_sections = {s["id"] for s in fake_fs.fs.list_sections(curriculum["id"], "m1")}
    assert m1_sections == {"s1", "s2"}
    m2_sections = {s["id"] for s in fake_fs.fs.list_sections(curriculum["id"], "m2")}
    assert m2_sections == {"s1"}

    # Every stub starts "planned" with empty content, matching the writing phase's expectations.
    assert fake_fs.fs.get_section(curriculum["id"], "m1", "s1")["status"] == "planned"

    # Re-running (e.g. a second approval of the same plan version) must not duplicate.
    await orchestrator._materialize_modules_and_sections(curriculum["id"], plan)
    assert len(fake_fs.fs.list_modules(curriculum["id"])) == 2
    assert len(fake_fs.fs.list_sections(curriculum["id"], "m1")) == 2
    assert len(fake_fs.fs.list_sections(curriculum["id"], "m2")) == 1


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
    """Verify requesting plan modifications records feedback, leaves the phase at
    `awaiting_approval` (the agent picks its own next phase via `complete_phase`), appends
    a system message instructing that choice, and still fires `curriculum_updated`.
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
    # System message must instruct the agent to pick its own next phase — not force one.
    assert "deep_research" in system_msgs[0]["content"]
    assert "outline_planning" in system_msgs[0]["content"]

    # curriculum_updated fires on modify too (harmless — keeps client status in sync);
    # this is unconditional in run_turn, independent of the modify branch's own updates.
    curriculum_updated_events = [e for e in events if e["type"] == "curriculum_updated"]
    assert len(curriculum_updated_events) == 1
    assert curriculum_updated_events[0]["curriculum_id"] == curriculum["id"]

    # The orchestrator no longer forces a phase on modify — no phase_change is emitted
    # here; the agent emits its own once it calls complete_phase in a later turn.
    phase_change_events = [e for e in events if e["type"] == "phase_change"]
    assert len(phase_change_events) == 0

    # Phase stays at awaiting_approval until the agent itself transitions via complete_phase.
    agent_state = fake_fs.fs.get_agent_state(curriculum["id"])
    assert agent_state["phase"] == "awaiting_approval"

    # Plan status recorded as revising with the feedback appended.
    plan = fake_fs.fs.get_plan(curriculum["id"])
    assert plan["status"] == "revising"
    assert "Add more system design content" in plan["user_feedback"]


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
    slow `fetch_url`, which fetches a full page) aborts the tool batch
    immediately rather than waiting for it to finish, emits an error-status
    `tool_call_result` for the aborted call, and ends the turn as CANCELLED — the
    `_wait_cancellable` race in `_run_turn_inner`'s tool-batch loop (see orchestrator.py
    item B.3) is what's under test here.
    """
    import asyncio

    from app.agent.orchestrator import _cancel_events

    conv, curriculum = _setup_conversation(fake_fs, phase="deep_research")

    # Script a single tool call (fetch_url) followed by Done — the fake registry
    # execute() below never actually returns normally; it hangs until cancelled so we
    # can deterministically simulate "cancellation arrives mid-tool-call".
    scripted = ScriptedLLM(
        [
            ReasoningDelta(text="searching"),
            TextDelta(text="Let me look that up."),
            ToolCallDelta(id="call_1", name="fetch_url", arguments={"url": "https://example.com/guide"}),
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


@pytest.mark.asyncio
async def test_successful_fetch_url_strips_stale_prior_fetch_of_same_url(monkeypatch, fake_fs, orchestrator):
    """Verify a batch containing a successful `fetch_url` call triggers
    `strip_stale_fetch_url_outputs` for the conversation — rewriting an earlier stored
    `fetch_url` output for the SAME URL down to a short note (losing `content_markdown`)
    while the just-appended (latest) fetch of that URL keeps its content intact, per the
    dedup contract: only the newest fetch of a URL stays in context.
    """
    import json

    conv, curriculum = _setup_conversation(fake_fs, phase="deep_research")

    # Seed a prior assistant message with a fetch_url tool_call carrying full page
    # content for the same URL, as if it ran in an earlier turn/iteration.
    prior_output = {"url": "https://example.com/guide", "title": "Guide", "content_markdown": "# Old guide content"}
    fake_fs.fs.append_message(
        conv["id"],
        {
            "role": "assistant",
            "content": "",
            "reasoning": None,
            "tool_calls": [
                {
                    "id": "prior_call",
                    "name": "fetch_url",
                    "input": {"url": "https://example.com/guide"},
                    "output_full": json.dumps(prior_output),
                    "output_preview": json.dumps(prior_output)[:1500],
                    "status": "ok",
                }
            ],
        },
    )

    class _TwoTurnLLM:
        """Fake LLMProvider: calls fetch_url on the first chat_stream call, then answers
        with plain text on the second — needed because fetch_url is not a HITL-gate
        tool, so the orchestrator loops to a second iteration after it runs.
        """

        def __init__(self) -> None:
            """Track how many times chat_stream has been invoked."""
            self._calls = 0

        async def chat_stream(self, messages, tools=None, small: bool = False):
            """Yield the tool-call script on call 1, a plain-text script on call 2+."""
            self._calls += 1
            if self._calls == 1:
                events = [
                    TextDelta(text="Re-reading the guide."),
                    ToolCallDelta(
                        id="call_fetch",
                        name="fetch_url",
                        arguments={"url": "https://example.com/guide"},
                    ),
                    Done(),
                ]
            else:
                events = [TextDelta(text="Read it."), Done()]
            for event in events:
                yield event

        async def complete(self, messages, small: bool = False) -> str:
            """Unused by this test; present to satisfy the LLMProvider protocol."""
            return "stub completion"

    scripted = _TwoTurnLLM()
    monkeypatch.setattr("app.agent.orchestrator.get_llm_provider", lambda *a, **k: scripted)
    monkeypatch.setattr("app.agent.orchestrator.get_search_provider", lambda *a, **k: StubSearch())

    # Stub the registry's execute to return a fetch_url-shaped success without touching
    # real network plumbing — this test is about the orchestrator's dedup wiring, not
    # fetch_url's own internals (covered separately in test_research_tools.py).
    from app.agent.tools.registry import ToolResult

    async def fake_execute(tool_name, raw_input, ctx):
        """Return a canned successful fetch_url result for the same URL, with new content."""
        assert tool_name == "fetch_url"
        return ToolResult(
            {"url": raw_input["url"], "title": "Guide", "content_markdown": "# New guide content"},
            "ok",
            5,
        )

    monkeypatch.setattr(orchestrator._registry, "execute", fake_execute)

    events = []

    async def emit(event):
        events.append(event)

    result = await orchestrator.run_turn(
        conversation_id=conv["id"],
        curriculum_id=curriculum["id"],
        owner_uid="uid1",
        user_input="re-read that page",
        emit=emit,
    )

    assert result.outcome == TurnOutcome.DONE

    messages = fake_fs.fs.list_messages(conv["id"])
    prior_msg = next(m for m in messages if any(tc["id"] == "prior_call" for tc in m.get("tool_calls", [])))
    prior_tc = next(tc for tc in prior_msg["tool_calls"] if tc["id"] == "prior_call")
    rewritten = json.loads(prior_tc["output_full"])
    assert "content_markdown" not in rewritten
    assert rewritten["url"] == "https://example.com/guide"

    # The latest fetch (appended by this turn) keeps its content intact.
    latest_msg = next(m for m in messages if any(tc["id"] == "call_fetch" for tc in m.get("tool_calls", [])))
    latest_tc = next(tc for tc in latest_msg["tool_calls"] if tc["id"] == "call_fetch")
    kept = json.loads(latest_tc["output_full"])
    assert kept["content_markdown"] == "# New guide content"
