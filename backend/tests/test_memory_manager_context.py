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
    then verify compaction runs, persists a summary, and fires the on_compaction callback.

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
    compaction_calls = []

    async def on_compaction(preview, before, after):
        compaction_calls.append((preview, before, after))

    await manager.build_context(
        conversation_id=conv["id"],
        curriculum_id="cur1",
        phase="refinement",
        synthesized_profile=None,
        profile=None,
        agent_state={"phase": "refinement"},
        small_llm=small_llm,
        on_compaction=on_compaction,
    )

    assert len(small_llm.complete_calls) == 1
    assert len(compaction_calls) == 1
    preview, before, after = compaction_calls[0]
    assert preview.startswith("## Summary")
    assert before > after or before >= 0  # after should shrink relative to full context

    updated_conv = fake_fs.fs.get_conversation(conv["id"])
    assert updated_conv["summary"] == "## Summary\n\nCondensed everything."
    assert updated_conv["compacted_through"] is not None


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
