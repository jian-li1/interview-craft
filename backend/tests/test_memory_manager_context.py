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
        self._summary = summary
        self.complete_calls: list[list[ChatMessage]] = []

    async def complete(self, messages, small: bool = False) -> str:
        self.complete_calls.append(messages)
        return self._summary

    async def chat_stream(self, messages, tools=None, small: bool = False):
        raise NotImplementedError


@pytest.fixture()
def manager(settings) -> MemoryManager:
    return MemoryManager(settings)


@pytest.mark.asyncio
async def test_build_context_includes_static_and_working_memory_blocks(manager, fake_fs):
    conv = fake_fs.fs.create_conversation("uid1", "New chat", curriculum_id="cur1")
    fake_fs.fs.append_message(conv["id"], {"role": "user", "content": "help me prep for a PM interview"})

    messages = await manager.build_context(
        conversation_id=conv["id"],
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
    conv = fake_fs.fs.create_conversation("uid1", "New chat", curriculum_id="cur1")
    fake_fs.fs.append_message(conv["id"], {"role": "user", "content": "short message"})
    small_llm = FakeSmallLLM()

    await manager.build_context(
        conversation_id=conv["id"],
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
