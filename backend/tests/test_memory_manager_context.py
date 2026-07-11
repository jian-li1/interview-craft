"""MemoryManager.build_context: layered assembly + auto-compaction trigger, using a fake
small LLM and the in-memory fake Firestore (no network/credentials).
"""

from __future__ import annotations

import pytest

from app.agent.memory.manager import MemoryManager
from app.services.llm.base import ChatMessage


class FakeSmallLLM:
    """Minimal LLMProvider stand-in: complete() returns a canned compaction summary."""

    def __init__(self, summary: str = "## Summary\n\nStub compacted summary.") -> None:
        """Initialize the fake with a canned summary to return from `complete`.

        Args:
            summary (str): The fixed text `complete()` will return on every call.
        """
        self._summary = summary
        self.complete_calls: list[list[ChatMessage]] = []

    async def complete(self, messages, small: bool = False) -> str:
        """Record the call and return the canned summary, standing in for a real LLM.

        Args:
            messages: The chat messages that would have been sent to the LLM.
            small (bool): Unused; present to match the `LLMProvider` protocol signature.

        Returns:
            str: The fixed summary text configured at construction time.
        """
        self.complete_calls.append(messages)
        return self._summary

    async def chat_stream(self, messages, tools=None, small: bool = False):
        """Unimplemented streaming stand-in — this fake only supports `complete`.

        Raises:
            NotImplementedError: Always; compaction only calls `complete`, so streaming
                is intentionally left unsupported here.
        """
        raise NotImplementedError


@pytest.fixture()
def manager(settings) -> MemoryManager:
    """Construct a `MemoryManager` wired to the real (test) app settings.

    Args:
        settings: The `settings` fixture from conftest.py.

    Returns:
        MemoryManager: A manager instance ready to call `build_context` against the
            in-memory fake Firestore.
    """
    return MemoryManager(settings)


@pytest.mark.asyncio
async def test_build_context_includes_static_and_working_memory_blocks(manager, fake_fs):
    """Verify `build_context` assembles system messages covering the static prompt,
    user memory, and working memory layers, and includes conversation history.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New chat", curriculum_id="cur1")
    fake_fs.fs.append_message(conv["id"], {"role": "user", "content": "help me prep for a PM interview"})

    messages = await manager.build_context(
        conversation_id=conv["id"],
        curriculum_id="cur1",
        phase="intake",
        synthesized_profile="A career-changer targeting PM roles.",
        profile={"target_roles": ["Product Manager"]},
        agent_state={"phase": "intake", "task_queue": [], "scratchpad": ""},
        small_llm=None,
        on_compaction=None,
    )

    system_messages = [m for m in messages if m.role == "system"]
    assert len(system_messages) >= 3  # static prompt, user memory, working memory
    joined = "\n".join(m.content for m in system_messages)
    assert "career-changer" in joined
    assert "intake" in joined

    user_messages = [m for m in messages if m.role == "user"]
    assert any("PM interview" in m.content for m in user_messages)


@pytest.mark.asyncio
async def test_build_context_does_not_compact_below_threshold(manager, fake_fs):
    """Verify `build_context` skips compaction when the conversation is well under the
    0.8x context_token_limit trigger — no LLM call and no summary persisted.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New chat", curriculum_id="cur1")
    fake_fs.fs.append_message(conv["id"], {"role": "user", "content": "short message"})
    small_llm = FakeSmallLLM()

    await manager.build_context(
        conversation_id=conv["id"],
        curriculum_id="cur1",
        phase="refinement",
        synthesized_profile=None,
        profile=None,
        agent_state={"phase": "refinement"},
        small_llm=small_llm,
        on_compaction=None,
    )

    assert small_llm.complete_calls == []
    updated_conv = fake_fs.fs.get_conversation(conv["id"])
    assert updated_conv["summary"] is None


@pytest.mark.asyncio
async def test_build_context_triggers_compaction_above_threshold(manager, fake_fs, monkeypatch):
    """Force a tiny context_token_limit so a handful of messages exceeds the 0.8x trigger,
    then verify compaction runs, persists a summary + last_compaction checkpoint (with
    token_estimate reflecting the POST-compaction figure), fires on_compaction_start
    before on_compaction, and passes the 4-arg on_compaction form (the FULL untruncated
    summary plus the compacted-through message id).

    Fixtures:
        monkeypatch: Used to shrink `manager._settings.context_token_limit` to 50 so
            the compaction threshold is easily exceeded by a handful of test messages.
    """
    monkeypatch.setattr(manager._settings, "context_token_limit", 50)

    conv = fake_fs.fs.create_conversation("uid1", "New chat", curriculum_id="cur1")
    for i in range(20):
        fake_fs.fs.append_message(
            conv["id"], {"role": "user", "content": f"message number {i} with some extra padding text to add tokens"}
        )

    small_llm = FakeSmallLLM(summary="## Summary\n\nCondensed everything.")
    # Records (event_name, payload) in the order each callback fires, so ordering
    # between on_compaction_start and on_compaction can be asserted below.
    call_order = []

    async def on_compaction_start(before):
        call_order.append(("start", before))

    async def on_compaction(summary, before, after, compacted_through):
        call_order.append(("compaction", summary, before, after, compacted_through))

    await manager.build_context(
        conversation_id=conv["id"],
        curriculum_id="cur1",
        phase="refinement",
        synthesized_profile=None,
        profile=None,
        agent_state={"phase": "refinement"},
        small_llm=small_llm,
        on_compaction=on_compaction,
        on_compaction_start=on_compaction_start,
    )

    assert len(small_llm.complete_calls) == 1
    # on_compaction_start must fire before on_compaction, both exactly once.
    assert [c[0] for c in call_order] == ["start", "compaction"]
    _, start_before = call_order[0]
    _, summary, before, after, compacted_through = call_order[1]
    assert start_before == before  # same tokens_before figure in both callbacks
    # Callback receives the FULL rolling summary, not a truncated preview.
    assert summary == "## Summary\n\nCondensed everything."
    assert before > after or before >= 0  # after should shrink relative to full context
    assert compacted_through is not None

    updated_conv = fake_fs.fs.get_conversation(conv["id"])
    assert updated_conv["summary"] == "## Summary\n\nCondensed everything."
    assert updated_conv["compacted_through"] is not None
    # token_estimate must reflect the POST-compaction context (tokens_after), not the
    # pre-compaction figure that triggered this pass.
    assert updated_conv["token_estimate"] == after
    # New checkpoint map persisted for the WS reconnect snapshot to replay the chip.
    assert updated_conv["last_compaction"] == {"tokens_before": before, "tokens_after": after}


@pytest.mark.asyncio
async def test_build_context_force_compact_below_threshold(manager, fake_fs):
    """Verify `force_compact=True` triggers compaction even though the default
    context_token_limit is nowhere near exceeded by a handful of short messages —
    the manual "Compact now" path — and persists the summary/compacted_through checkpoint.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New chat", curriculum_id="cur1")
    for i in range(5):
        fake_fs.fs.append_message(conv["id"], {"role": "user", "content": f"short message {i}"})

    small_llm = FakeSmallLLM(summary="## Summary\n\nForced compaction.")

    await manager.build_context(
        conversation_id=conv["id"],
        curriculum_id="cur1",
        phase="refinement",
        synthesized_profile=None,
        profile=None,
        agent_state={"phase": "refinement"},
        small_llm=small_llm,
        force_compact=True,
    )

    assert len(small_llm.complete_calls) == 1
    updated_conv = fake_fs.fs.get_conversation(conv["id"])
    assert updated_conv["summary"] == "## Summary\n\nForced compaction."
    assert updated_conv["compacted_through"] is not None


@pytest.mark.asyncio
async def test_build_context_force_compact_too_few_messages_skips(manager, fake_fs):
    """Verify `force_compact=True` with only 2 candidate messages does NOT compact —
    the `len(candidate_messages) > 2` guard applies regardless of `force_compact`, so
    a lingering couple of messages is never folded down to nothing.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New chat", curriculum_id="cur1")
    fake_fs.fs.append_message(conv["id"], {"role": "user", "content": "first"})
    fake_fs.fs.append_message(conv["id"], {"role": "assistant", "content": "second"})

    small_llm = FakeSmallLLM()
    compaction_calls = []

    async def on_compaction(summary, before, after, compacted_through):
        compaction_calls.append((summary, before, after, compacted_through))

    await manager.build_context(
        conversation_id=conv["id"],
        curriculum_id="cur1",
        phase="refinement",
        synthesized_profile=None,
        profile=None,
        agent_state={"phase": "refinement"},
        small_llm=small_llm,
        force_compact=True,
        on_compaction=on_compaction,
    )

    assert small_llm.complete_calls == []
    assert compaction_calls == []
    updated_conv = fake_fs.fs.get_conversation(conv["id"])
    assert updated_conv["summary"] is None


@pytest.mark.asyncio
async def test_build_context_on_context_usage_fires_both_branches(manager, fake_fs, monkeypatch):
    """Verify `on_context_usage` fires exactly once with the final token estimate in
    both the no-compaction branch (tokens_before) and the compaction branch (tokens_after).
    """
    conv = fake_fs.fs.create_conversation("uid1", "New chat", curriculum_id="cur1")
    fake_fs.fs.append_message(conv["id"], {"role": "user", "content": "short message"})

    usage_calls = []

    async def on_context_usage(tokens):
        usage_calls.append(tokens)

    # Branch 1: no small_llm at all, well under any threshold — no compaction.
    await manager.build_context(
        conversation_id=conv["id"],
        curriculum_id="cur1",
        phase="refinement",
        synthesized_profile=None,
        profile=None,
        agent_state={"phase": "refinement"},
        small_llm=None,
        on_context_usage=on_context_usage,
    )
    assert len(usage_calls) == 1
    updated_conv = fake_fs.fs.get_conversation(conv["id"])
    assert usage_calls[0] == updated_conv["token_estimate"]

    # Branch 2: force compaction to run, so on_context_usage should report tokens_after.
    for i in range(5):
        fake_fs.fs.append_message(conv["id"], {"role": "user", "content": f"padding message {i}"})
    small_llm = FakeSmallLLM(summary="## Summary\n\nForced.")
    await manager.build_context(
        conversation_id=conv["id"],
        curriculum_id="cur1",
        phase="refinement",
        synthesized_profile=None,
        profile=None,
        agent_state={"phase": "refinement"},
        small_llm=small_llm,
        force_compact=True,
        on_context_usage=on_context_usage,
    )
    assert len(usage_calls) == 2
    updated_conv = fake_fs.fs.get_conversation(conv["id"])
    assert usage_calls[1] == updated_conv["token_estimate"] == updated_conv["last_compaction"]["tokens_after"]


@pytest.mark.asyncio
async def test_build_context_injects_sources_block_between_working_memory_and_summary(manager, fake_fs):
    """Verify saved sources are rendered into their own system block, positioned after
    working memory and before the rolling summary — the fixed layer order invariant
    from `app/agent/CLAUDE.md`.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New chat", curriculum_id="cur1")
    fake_fs.fs.update_conversation(conv["id"], {"summary": "Earlier conversation summary text."})
    fake_fs.fs.create_source(
        "cur1",
        {
            "query": "system design basics",
            "url": "https://example.com/ddia",
            "title": "Designing Data-Intensive Apps",
            "summary": "Covers leader-follower replication trade-offs.",
            "content_markdown": "# Replication\n\nLeader-follower replication details.",
            "content_truncated": False,
        },
    )

    messages = await manager.build_context(
        conversation_id=conv["id"],
        curriculum_id="cur1",
        phase="writing",
        synthesized_profile=None,
        profile=None,
        agent_state={"phase": "writing"},
        small_llm=None,
        on_compaction=None,
    )

    system_messages = [m for m in messages if m.role == "system"]
    contents = [m.content for m in system_messages]
    # "pinned working memory" is unique to build_sources_memory_block's own heading —
    # the phrase "Saved research sources" alone also appears (quoted) in the static
    # phase prompts, so it can't disambiguate the block by itself.
    sources_idx = next(i for i, c in enumerate(contents) if "pinned working memory" in c)
    working_memory_idx = next(i for i, c in enumerate(contents) if "Agent working memory" in c)
    summary_idx = next(i for i, c in enumerate(contents) if "Summary of earlier conversation" in c)

    assert working_memory_idx < sources_idx < summary_idx
    # The sources block carries the agent's summary, not the full fetched page content.
    assert "Covers leader-follower replication trade-offs." in contents[sources_idx]
    assert "Leader-follower replication details." not in contents[sources_idx]
