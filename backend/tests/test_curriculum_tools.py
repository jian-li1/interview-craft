"""Curriculum tools: set_curriculum_title updates both curriculum + conversation."""

from __future__ import annotations

import pytest

from app.agent.tools.base import AgentContext
from app.agent.tools.curriculum import SetCurriculumTitleInput, SetCurriculumTitleTool
from app.core.config import get_settings


def _make_ctx(curriculum_id: str, conversation_id: str) -> AgentContext:
    """Build a minimal `AgentContext` for exercising a tool in isolation.

    Args:
        curriculum_id (str): Curriculum id to scope the context to.
        conversation_id (str): Conversation id to scope the context to.

    Returns:
        AgentContext: Context with a fixed owner uid, real settings, and placeholder
            (non-functional) LLM/search clients — sufficient for tools that only touch
            Firestore via the `fake_fs` fixture.
    """
    return AgentContext(
        curriculum_id=curriculum_id,
        conversation_id=conversation_id,
        owner_uid="uid1",
        settings=get_settings(),
        llm=object(),
        small_llm=object(),
        search=object(),
        phase="intake",
    )


@pytest.mark.asyncio
async def test_set_curriculum_title_updates_curriculum_and_conversation(fake_fs):
    """Verify SetCurriculumTitleTool updates both the curriculum's title/emoji and the
    linked conversation's title, and emits a `curriculum_updated` WS event.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep me for a google swe interview...", "prep me for a google swe interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})

    tool = SetCurriculumTitleTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    result = await tool.execute(
        SetCurriculumTitleInput(title="Google SWE Interview Prep — 3-Week Plan", emoji="\U0001F4BB"),
        ctx,
    )

    assert result["status"] == "updated"
    assert result["_ws_event"] == {
        "type": "curriculum_updated",
        "curriculum_id": curriculum["id"],
        "scope": "curriculum",
    }

    updated_curriculum = fake_fs.fs.get_curriculum(curriculum["id"])
    assert updated_curriculum["title"] == "Google SWE Interview Prep — 3-Week Plan"
    assert updated_curriculum["emoji"] == "\U0001F4BB"

    updated_conversation = fake_fs.fs.get_conversation(conv["id"])
    assert updated_conversation["title"] == "Google SWE Interview Prep — 3-Week Plan"


@pytest.mark.asyncio
async def test_set_curriculum_title_without_emoji_does_not_clear_existing_emoji(fake_fs):
    """Verify calling the tool with `emoji=None` leaves a previously-set emoji intact,
    since the field is omitted from the update rather than explicitly cleared.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "placeholder title", "prep me for consulting case interviews", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.update_curriculum(curriculum["id"], {"emoji": "\U0001F4BC"})

    tool = SetCurriculumTitleTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    await tool.execute(SetCurriculumTitleInput(title="Consulting Case Interview Mastery", emoji=None), ctx)

    updated_curriculum = fake_fs.fs.get_curriculum(curriculum["id"])
    assert updated_curriculum["title"] == "Consulting Case Interview Mastery"
    # emoji field wasn't included in the update at all, so the prior value survives.
    assert updated_curriculum["emoji"] == "\U0001F4BC"


def test_set_curriculum_title_rejects_titles_over_80_chars():
    """Verify the input model's length validation rejects titles longer than 80 chars."""
    with pytest.raises(Exception):
        SetCurriculumTitleInput(title="x" * 81)


def test_set_curriculum_title_registered_and_always_available():
    """Verify `set_curriculum_title` is registered, marked always-available, and shows
    up in the tool specs for every agent phase.
    """
    from app.agent.tools.registry import ToolRegistry, _ALWAYS_AVAILABLE

    registry = ToolRegistry()
    assert "set_curriculum_title" in registry._tools
    assert "set_curriculum_title" in _ALWAYS_AVAILABLE
    for phase in ["intake", "deep_research", "outline_planning", "writing", "refinement"]:
        names = {s.name for s in registry.specs_for_phase(phase)}
        assert "set_curriculum_title" in names
