"""Curriculum tools: set_curriculum_title updates both curriculum + conversation;
write_section/update_section auto-derive parent module status/estimated_minutes;
set_module_status emits a curriculum_updated WS event; write_section and
complete_phase persist progress onto the curriculum doc for REST readers;
write_section/update_section reject broken Mermaid diagrams at write time.
"""

from __future__ import annotations

import pytest

from app.agent.tools.base import AgentContext
from app.agent.tools.control import CompletePhaseInput, CompletePhaseTool
from app.agent.tools.curriculum import (
    SetCurriculumTitleInput,
    SetCurriculumTitleTool,
    SetModuleStatusInput,
    SetModuleStatusTool,
    UpdateSectionInput,
    UpdateSectionTool,
    WriteSectionInput,
    WriteSectionTool,
)
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


@pytest.mark.asyncio
async def test_write_section_derives_module_status_writing_then_complete(fake_fs):
    """Writing one of two planned sections flips the module to "writing" with
    estimated_minutes > 0; writing the second flips it to "complete".
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep for a system design interview", "prep for a system design interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.create_module(curriculum["id"], "mod1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})
    # Two planned section stubs with empty content, matching orchestrator plan materialization.
    fake_fs.fs.create_section(curriculum["id"], "mod1", "sec1", {"order": 0, "title": "Section 1", "content_markdown": "", "citations": [], "status": "planned"})
    fake_fs.fs.create_section(curriculum["id"], "mod1", "sec2", {"order": 1, "title": "Section 2", "content_markdown": "", "citations": [], "status": "planned"})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])

    # Keep content short (<=400 chars) so the citation guard doesn't trip.
    await tool.execute(
        WriteSectionInput(module_id="mod1", section_id="sec1", title="Section 1", content_markdown="Short content. " * 5, citations=[]),
        ctx,
    )
    module_after_first = fake_fs.fs.get_module(curriculum["id"], "mod1")
    assert module_after_first["status"] == "writing"
    assert module_after_first["estimated_minutes"] > 0

    await tool.execute(
        WriteSectionInput(module_id="mod1", section_id="sec2", title="Section 2", content_markdown="Short content. " * 5, citations=[]),
        ctx,
    )
    module_after_second = fake_fs.fs.get_module(curriculum["id"], "mod1")
    assert module_after_second["status"] == "complete"
    assert module_after_second["estimated_minutes"] > 0


@pytest.mark.asyncio
async def test_set_module_status_emits_ws_event_and_persists(fake_fs):
    """SetModuleStatusTool returns a curriculum_updated _ws_event (scope "module") and
    persists the new status on the module document.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep for behavioral interviews", "prep for behavioral interviews", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.create_module(curriculum["id"], "mod1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})

    tool = SetModuleStatusTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    result = await tool.execute(SetModuleStatusInput(module_id="mod1", status="writing"), ctx)

    assert result["status"] == "updated"
    assert result["new_status"] == "writing"
    assert result["_ws_event"] == {
        "type": "curriculum_updated",
        "curriculum_id": curriculum["id"],
        "scope": "module",
        "module_id": "mod1",
    }

    updated_module = fake_fs.fs.get_module(curriculum["id"], "mod1")
    assert updated_module["status"] == "writing"


@pytest.mark.asyncio
async def test_write_section_persists_progress_onto_curriculum_doc(fake_fs):
    """write_section must persist completed/total task counts onto the curriculum doc's
    `progress` field (not just emit the transient WS event) so REST readers (e.g. the
    dashboard card) see live progress even without an open socket.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep for a system design interview", "prep for a system design interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.create_module(curriculum["id"], "mod1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})
    fake_fs.fs.create_section(curriculum["id"], "mod1", "sec1", {"order": 0, "title": "Section 1", "content_markdown": "", "citations": [], "status": "planned"})
    # Plan with two tasks (one matching sec1's id) so _task_progress has something to count.
    fake_fs.fs.set_plan(curriculum["id"], {"tasks": [{"id": "sec1", "status": "pending"}, {"id": "sec2", "status": "pending"}]})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "writing"  # simulate the orchestrator running write_section in the writing phase

    await tool.execute(
        WriteSectionInput(module_id="mod1", section_id="sec1", title="Section 1", content_markdown="Short content. " * 5, citations=[]),
        ctx,
    )

    updated_curriculum = fake_fs.fs.get_curriculum(curriculum["id"])
    # sec1's task flips to "done" as a write_section side effect, so 1 of 2 tasks complete.
    assert updated_curriculum["progress"] == {
        "phase": "writing",
        "completed_tasks": 1,
        "total_tasks": 2,
        "detail": "Wrote section: Section 1",
    }


@pytest.mark.asyncio
async def test_complete_phase_review_to_ready_sets_status_and_progress(fake_fs):
    """complete_phase("ready") from "review" must set curriculum status to "ready" and
    sync progress.phase/detail — this is the fix for the dashboard card stuck on
    "writing" forever, since review previously had no path to "ready" at all.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep for a system design interview", "prep for a system design interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.update_curriculum(curriculum["id"], {
        "status": "writing",
        "progress": {"phase": "review", "completed_tasks": 3, "total_tasks": 3, "detail": "Wrote section: X"},
    })

    tool = CompletePhaseTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "review"  # transition validation requires the current phase to be "review"

    result = await tool.execute(CompletePhaseInput(next_phase="ready", reason="all sections reviewed"), ctx)

    assert result["status"] == "transitioned"
    updated_curriculum = fake_fs.fs.get_curriculum(curriculum["id"])
    assert updated_curriculum["status"] == "ready"
    assert updated_curriculum["progress"]["phase"] == "ready"
    assert updated_curriculum["progress"]["detail"] == "Curriculum complete"
    # completed_tasks/total_tasks carry over untouched from the pre-existing progress blob.
    assert updated_curriculum["progress"]["completed_tasks"] == 3
    assert updated_curriculum["progress"]["total_tasks"] == 3


@pytest.mark.asyncio
async def test_write_section_rejects_broken_mermaid_and_does_not_write(fake_fs):
    """write_section with a broken mermaid block (unquoted parens in a label) returns
    {"error": ...} and the section is NOT created at all.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep for a system design interview", "prep for a system design interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.create_module(curriculum["id"], "mod1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    broken_content = "Intro text.\n\n```mermaid\nflowchart TD\n    A[Review (Optional)] --> B\n```\n"

    result = await tool.execute(
        WriteSectionInput(module_id="mod1", section_id="sec1", title="Section 1", content_markdown=broken_content, citations=[]),
        ctx,
    )

    assert "error" in result
    assert fake_fs.fs.get_section(curriculum["id"], "mod1", "sec1") is None


@pytest.mark.asyncio
async def test_write_section_accepts_valid_mermaid(fake_fs):
    """write_section with a correctly-quoted mermaid block succeeds and persists the section."""
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep for a system design interview", "prep for a system design interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.create_module(curriculum["id"], "mod1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    valid_content = 'Intro text.\n\n```mermaid\nflowchart TD\n    A["Screen"] --> B["Onsite"]\n```\n'

    result = await tool.execute(
        WriteSectionInput(module_id="mod1", section_id="sec1", title="Section 1", content_markdown=valid_content, citations=[]),
        ctx,
    )

    assert result["status"] == "written"
    written = fake_fs.fs.get_section(curriculum["id"], "mod1", "sec1")
    assert written["content_markdown"] == valid_content


@pytest.mark.asyncio
async def test_update_section_rejects_broken_mermaid_and_leaves_content_untouched(fake_fs):
    """update_section with a broken mermaid block returns {"error": ...} and leaves the
    section's prior content_markdown unchanged.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep for a system design interview", "prep for a system design interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.create_module(curriculum["id"], "mod1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})
    original_content = "Original content, no diagrams."
    fake_fs.fs.create_section(
        curriculum["id"], "mod1", "sec1",
        {"order": 0, "title": "Section 1", "content_markdown": original_content, "citations": [], "status": "complete"},
    )

    tool = UpdateSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    broken_content = "```mermaid\nflowchart TD\n    A[Bad (Label)] --> B\n```\n"

    result = await tool.execute(
        UpdateSectionInput(module_id="mod1", section_id="sec1", content_markdown=broken_content, citations=[], change_note="add diagram"),
        ctx,
    )

    assert "error" in result
    unchanged = fake_fs.fs.get_section(curriculum["id"], "mod1", "sec1")
    assert unchanged["content_markdown"] == original_content
