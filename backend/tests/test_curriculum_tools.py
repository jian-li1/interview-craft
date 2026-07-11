"""Curriculum tools: set_curriculum_title updates both curriculum + conversation;
write_section/update_section auto-derive parent module status/estimated_minutes;
set_module_status emits a curriculum_updated WS event; write_section and
transition_phase persist progress onto the curriculum doc for REST readers;
write_section's target guard rejects invented module ids in every phase and, in
ready/refinement, also rejects already-existing section ids (directing the model to
update_section) while enforcing next-sequential-id creation for brand-new sections;
create_module/update_module are the sole module-creation/metadata-edit tools in
ready/refinement (write_section no longer auto-creates modules); transition_phase's
writing->review and review->ready completeness gates block premature phase exits;
transition_phase also allows the plan-revision loop-backs awaiting_approval->deep_research
and outline_planning->deep_research; strip_stale_section_content dedups
read/write/update_section calls per (module_id, section_id) so a section's content never
occupies context twice.
"""

from __future__ import annotations

import json

import pytest

from app.agent.tools.base import AgentContext
from app.agent.tools.control import TransitionPhaseInput, TransitionPhaseTool
from app.agent.tools.curriculum import (
    _SECTION_CONTENT_STRIPPED_NOTE,
    CreateModuleInput,
    CreateModuleTool,
    SetCurriculumTitleInput,
    SetCurriculumTitleTool,
    SetModuleStatusInput,
    SetModuleStatusTool,
    UpdateModuleInput,
    UpdateModuleTool,
    UpdateSectionInput,
    UpdateSectionTool,
    WriteSectionInput,
    WriteSectionTool,
    strip_stale_section_content,
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
    # Simulate the writing phase overwriting pre-materialized planned stubs — the target
    # guard now rejects an already-existing section outside writing/review.
    ctx.phase = "writing"

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
async def test_transition_phase_review_to_ready_sets_status_and_progress(fake_fs):
    """transition_phase("ready") from "review" must set curriculum status to "ready" and
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
        "overview": "A complete overview of the curriculum.",  # required by the review->ready exit gate
        "progress": {"phase": "review", "completed_tasks": 3, "total_tasks": 3, "detail": "Wrote section: X"},
    })

    tool = TransitionPhaseTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "review"  # transition validation requires the current phase to be "review"

    result = await tool.execute(TransitionPhaseInput(next_phase="ready", reason="all sections reviewed"), ctx)

    assert result["status"] == "transitioned"
    updated_curriculum = fake_fs.fs.get_curriculum(curriculum["id"])
    assert updated_curriculum["status"] == "ready"
    assert updated_curriculum["progress"]["phase"] == "ready"
    assert updated_curriculum["progress"]["detail"] == "Curriculum complete"
    # completed_tasks/total_tasks carry over untouched from the pre-existing progress blob.
    assert updated_curriculum["progress"]["completed_tasks"] == 3
    assert updated_curriculum["progress"]["total_tasks"] == 3


@pytest.mark.asyncio
async def test_transition_phase_awaiting_approval_to_deep_research_allowed(fake_fs):
    """transition_phase("deep_research") from "awaiting_approval" must succeed — the
    agent's own revision-loop-back path when a plan-modify request needs new research.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep for a system design interview", "prep for a system design interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})

    tool = TransitionPhaseTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "awaiting_approval"  # transition validation requires this as the current phase

    result = await tool.execute(
        TransitionPhaseInput(next_phase="deep_research", reason="feedback needs new topics"), ctx
    )

    assert result["status"] == "transitioned"
    assert result["_ws_event"] == {"type": "phase_change", "phase": "deep_research", "label": "Researching"}
    updated_curriculum = fake_fs.fs.get_curriculum(curriculum["id"])
    assert updated_curriculum["status"] == "researching"


@pytest.mark.asyncio
async def test_transition_phase_outline_planning_to_deep_research_allowed(fake_fs):
    """transition_phase("deep_research") from "outline_planning" must succeed — allows
    bouncing back to research if a gap becomes apparent mid-revision.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep for a system design interview", "prep for a system design interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})

    tool = TransitionPhaseTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "outline_planning"  # transition validation requires this as the current phase

    result = await tool.execute(
        TransitionPhaseInput(next_phase="deep_research", reason="gap surfaced mid-revision"), ctx
    )

    assert result["status"] == "transitioned"
    updated_curriculum = fake_fs.fs.get_curriculum(curriculum["id"])
    assert updated_curriculum["status"] == "researching"


async def _setup_curriculum_for_write_section(fake_fs):
    """Create a bare conversation + curriculum, wired together, for write_section target-guard tests.

    Returns:
        tuple: (curriculum dict, conversation dict).
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep for a system design interview", "prep for a system design interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    return curriculum, conv


@pytest.mark.asyncio
async def test_write_section_writing_phase_rejects_unknown_module(fake_fs):
    """In the writing phase, write_section on a module id that was never materialized
    from the approved plan is rejected, listing the existing module ids.
    """
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "writing"

    result = await tool.execute(
        WriteSectionInput(module_id="overview_mod", section_id="s1", title="Phantom", content_markdown="short", citations=[]),
        ctx,
    )
    assert "error" in result
    assert "m1" in result["error"]  # existing module ids listed for orientation
    assert fake_fs.fs.get_section(curriculum["id"], "overview_mod", "s1") is None


@pytest.mark.asyncio
async def test_write_section_writing_phase_rejects_unplanned_section(fake_fs):
    """In the writing phase, write_section on a section id that wasn't materialized as a
    planned stub is rejected, listing the module's existing section ids/titles/statuses.
    """
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})
    fake_fs.fs.create_section(curriculum["id"], "m1", "s1", {"order": 0, "title": "Section 1", "content_markdown": "", "citations": [], "status": "planned"})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "writing"

    result = await tool.execute(
        WriteSectionInput(module_id="m1", section_id="beyond-star", title="Phantom", content_markdown="short", citations=[]),
        ctx,
    )
    assert "error" in result
    assert "s1" in result["error"]  # existing section ids listed for orientation
    assert fake_fs.fs.get_section(curriculum["id"], "m1", "beyond-star") is None


@pytest.mark.asyncio
async def test_write_section_writing_phase_success_marks_composite_task_done(fake_fs):
    """Writing a planned stub (module m1, section s1) in the writing phase succeeds and
    marks the matching plan task "m1-s1" done via composite-id matching.
    """
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})
    fake_fs.fs.create_section(curriculum["id"], "m1", "s1", {"order": 0, "title": "Section 1", "content_markdown": "", "citations": [], "status": "planned"})
    fake_fs.fs.set_plan(curriculum["id"], {"tasks": [{"id": "m1-s1", "title": "Section 1", "module_ref": "m1", "status": "pending"}]})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "writing"

    result = await tool.execute(
        WriteSectionInput(module_id="m1", section_id="s1", title="Section 1", content_markdown="Short content. " * 5, citations=[]),
        ctx,
    )
    assert result["status"] == "written"
    plan = fake_fs.fs.get_plan(curriculum["id"])
    assert plan["tasks"][0]["status"] == "done"


@pytest.mark.asyncio
async def test_write_section_legacy_full_task_id_section_still_marks_done(fake_fs):
    """When a section doc id equals the full legacy task id (pre-dating the m{X}-s{Y}
    convention), _mark_task_done's fallback (`t["id"] == section_id`) still matches.
    """
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})
    # Legacy materialization: the section doc id IS the full task id, not a stripped suffix.
    fake_fs.fs.create_section(curriculum["id"], "m1", "m1-s1", {"order": 0, "title": "Section 1", "content_markdown": "", "citations": [], "status": "planned"})
    fake_fs.fs.set_plan(curriculum["id"], {"tasks": [{"id": "m1-s1", "title": "Section 1", "module_ref": "m1", "status": "pending"}]})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "writing"

    result = await tool.execute(
        WriteSectionInput(module_id="m1", section_id="m1-s1", title="Section 1", content_markdown="Short content. " * 5, citations=[]),
        ctx,
    )
    assert result["status"] == "written"
    plan = fake_fs.fs.get_plan(curriculum["id"])
    assert plan["tasks"][0]["status"] == "done"


@pytest.mark.asyncio
async def test_write_section_refinement_creates_next_sequential_section(fake_fs):
    """In refinement, write_section may create a new section, but only at the next
    sequential id (s2, since s1 already exists).
    """
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})
    fake_fs.fs.create_section(curriculum["id"], "m1", "s1", {"order": 0, "title": "Section 1", "content_markdown": "x", "citations": [], "status": "complete"})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(
        WriteSectionInput(module_id="m1", section_id="s2", title="Section 2", content_markdown="Short content. " * 5, citations=[]),
        ctx,
    )
    assert result["status"] == "written"
    assert fake_fs.fs.get_section(curriculum["id"], "m1", "s2") is not None


@pytest.mark.asyncio
async def test_write_section_refinement_rejects_slug_id(fake_fs):
    """In refinement, a new section using a free-form slug (not 's{K+1}') is rejected."""
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})
    fake_fs.fs.create_section(curriculum["id"], "m1", "s1", {"order": 0, "title": "Section 1", "content_markdown": "x", "citations": [], "status": "complete"})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(
        WriteSectionInput(module_id="m1", section_id="beyond-star", title="Section 2", content_markdown="short", citations=[]),
        ctx,
    )
    assert "error" in result
    assert fake_fs.fs.get_section(curriculum["id"], "m1", "beyond-star") is None


@pytest.mark.asyncio
async def test_write_section_refinement_rejects_gapped_section_id(fake_fs):
    """In refinement, a new section id that skips ahead (s5 when only s1 exists) is
    rejected — only the immediate next sequential id is allowed.
    """
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})
    fake_fs.fs.create_section(curriculum["id"], "m1", "s1", {"order": 0, "title": "Section 1", "content_markdown": "x", "citations": [], "status": "complete"})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(
        WriteSectionInput(module_id="m1", section_id="s5", title="Section 5", content_markdown="short", citations=[]),
        ctx,
    )
    assert "error" in result
    assert fake_fs.fs.get_section(curriculum["id"], "m1", "s5") is None


@pytest.mark.asyncio
async def test_write_section_refinement_rejects_write_to_nonexistent_module(fake_fs):
    """In refinement, write_section on a module that doesn't exist is rejected (write_section
    never creates modules anymore) with an error mentioning create_module — no module doc
    is created as a side effect.
    """
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(
        WriteSectionInput(module_id="m2", section_id="s1", title="New Module: Extra Practice", content_markdown="Short content. " * 5, citations=[]),
        ctx,
    )
    assert "error" in result
    assert "create_module" in result["error"]
    assert fake_fs.fs.get_module(curriculum["id"], "m2") is None


@pytest.mark.asyncio
async def test_write_section_refinement_rejects_write_to_gapped_module(fake_fs):
    """In refinement, write_section on a module id that skips ahead (m3 when only m1
    exists) is rejected the same way as any other missing module — no module doc created.
    """
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(
        WriteSectionInput(module_id="m3", section_id="s1", title="Skip Ahead", content_markdown="short", citations=[]),
        ctx,
    )
    assert "error" in result
    assert fake_fs.fs.get_module(curriculum["id"], "m3") is None


@pytest.mark.asyncio
async def test_write_section_refinement_rejects_existing_section(fake_fs):
    """In refinement, write_section on a section id that already exists is rejected
    (write_section only creates new sections there) with an error mentioning
    update_section, and the existing content is left unchanged.
    """
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})
    fake_fs.fs.create_section(curriculum["id"], "m1", "s1", {"order": 0, "title": "Section 1", "content_markdown": "original", "citations": [], "status": "complete"})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(
        WriteSectionInput(module_id="m1", section_id="s1", title="Section 1", content_markdown="overwritten content", citations=[]),
        ctx,
    )
    assert "error" in result
    assert "update_section" in result["error"]
    unchanged = fake_fs.fs.get_section(curriculum["id"], "m1", "s1")
    assert unchanged["content_markdown"] == "original"


@pytest.mark.asyncio
async def test_create_module_happy_path(fake_fs):
    """create_module creates m2 (next sequential after m1) with the given title/
    description, "planned"/0-minute defaults, order = existing module count, returns a
    curriculum_updated _ws_event, and refreshes the curriculum's module_count.
    """
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})

    tool = CreateModuleTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(
        CreateModuleInput(module_id="m2", title="Extra Practice", description="More drills covering edge cases."),
        ctx,
    )
    assert result == {
        "status": "created",
        "module_id": "m2",
        "title": "Extra Practice",
        "_ws_event": {
            "type": "curriculum_updated",
            "curriculum_id": curriculum["id"],
            "scope": "module",
            "module_id": "m2",
        },
    }

    new_module = fake_fs.fs.get_module(curriculum["id"], "m2")
    assert new_module["order"] == 1
    assert new_module["title"] == "Extra Practice"
    assert new_module["description"] == "More drills covering edge cases."
    assert new_module["objectives"] == []
    assert new_module["status"] == "planned"
    assert new_module["estimated_minutes"] == 0

    updated_curriculum = fake_fs.fs.get_curriculum(curriculum["id"])
    assert updated_curriculum["module_count"] == 2


@pytest.mark.asyncio
async def test_create_module_rejects_gapped_id(fake_fs):
    """create_module rejects a gapped id (m3 when only m1 exists) — no module created."""
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})

    tool = CreateModuleTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(CreateModuleInput(module_id="m3", title="Skip Ahead", description="Covers advanced topics."), ctx)
    assert "error" in result
    assert "m2" in result["error"]  # names the expected id
    assert fake_fs.fs.get_module(curriculum["id"], "m3") is None


@pytest.mark.asyncio
async def test_create_module_rejects_arbitrary_slug(fake_fs):
    """create_module rejects a free-form slug id (not 'm{N+1}') — no module created."""
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})

    tool = CreateModuleTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(CreateModuleInput(module_id="extra-practice", title="Extra Practice", description="More drills."), ctx)
    assert "error" in result
    assert fake_fs.fs.get_module(curriculum["id"], "extra-practice") is None


@pytest.mark.asyncio
async def test_create_module_rejects_already_existing_id(fake_fs):
    """create_module rejects a module_id that already exists, directing the model to
    update_module for metadata edits instead."""
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "description": "Original.", "status": "complete", "estimated_minutes": 5})

    tool = CreateModuleTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(CreateModuleInput(module_id="m1", title="Replacement Title", description="Replacement description."), ctx)
    assert "error" in result
    assert "update_module" in result["error"]
    unchanged = fake_fs.fs.get_module(curriculum["id"], "m1")
    assert unchanged["title"] == "Module 1"


@pytest.mark.asyncio
async def test_create_module_rejects_blank_title(fake_fs):
    """create_module rejects a blank (whitespace-only) title with a runtime validation error."""
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)

    tool = CreateModuleTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(CreateModuleInput(module_id="m1", title="   ", description="A real description."), ctx)
    assert "error" in result
    assert fake_fs.fs.get_module(curriculum["id"], "m1") is None


@pytest.mark.asyncio
async def test_create_module_rejects_oversized_description(fake_fs):
    """create_module rejects a description over 300 chars with a runtime validation error."""
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)

    tool = CreateModuleTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(CreateModuleInput(module_id="m1", title="Module 1", description="x" * 301), ctx)
    assert "error" in result
    assert fake_fs.fs.get_module(curriculum["id"], "m1") is None


@pytest.mark.asyncio
async def test_update_module_updates_title_only_then_description_only(fake_fs):
    """update_module changes only the field(s) provided, leaving the others intact, and
    emits a curriculum_updated _ws_event each time."""
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(
        curriculum["id"], "m1",
        {"order": 0, "title": "Module 1", "description": "Original description.", "status": "complete", "estimated_minutes": 5},
    )

    tool = UpdateModuleTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    title_result = await tool.execute(UpdateModuleInput(module_id="m1", title="Renamed Module"), ctx)
    assert title_result["status"] == "updated"
    assert title_result["updated_fields"] == ["title"]
    assert title_result["_ws_event"] == {
        "type": "curriculum_updated",
        "curriculum_id": curriculum["id"],
        "scope": "module",
        "module_id": "m1",
    }
    after_title = fake_fs.fs.get_module(curriculum["id"], "m1")
    assert after_title["title"] == "Renamed Module"
    assert after_title["description"] == "Original description."  # untouched

    description_result = await tool.execute(
        UpdateModuleInput(module_id="m1", description="A fresher summary of the content."), ctx
    )
    assert description_result["updated_fields"] == ["description"]
    after_description = fake_fs.fs.get_module(curriculum["id"], "m1")
    assert after_description["title"] == "Renamed Module"  # untouched by this call
    assert after_description["description"] == "A fresher summary of the content."


@pytest.mark.asyncio
async def test_update_module_rejects_unknown_module_id(fake_fs):
    """update_module errors on an unknown module id, listing existing ids."""
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})

    tool = UpdateModuleTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(UpdateModuleInput(module_id="m9", title="New Title"), ctx)
    assert "error" in result
    assert "m1" in result["error"]


@pytest.mark.asyncio
async def test_update_module_rejects_when_neither_field_provided(fake_fs):
    """update_module errors when both title and description are omitted."""
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})

    tool = UpdateModuleTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    result = await tool.execute(UpdateModuleInput(module_id="m1"), ctx)
    assert "error" in result


@pytest.mark.asyncio
async def test_create_module_then_write_section_flow(fake_fs):
    """Flow test: create_module("m2", ...) followed by write_section(m2, s1, ...)
    succeeds — the new module exists by the time write_section's target guard runs."""
    curriculum, conv = await _setup_curriculum_for_write_section(fake_fs)
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})

    create_tool = CreateModuleTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "refinement"

    create_result = await create_tool.execute(
        CreateModuleInput(module_id="m2", title="Extra Practice", description="More drills covering edge cases."), ctx
    )
    assert create_result["status"] == "created"

    write_tool = WriteSectionTool()
    write_result = await write_tool.execute(
        WriteSectionInput(module_id="m2", section_id="s1", title="Drill 1", content_markdown="Short content. " * 5, citations=[]),
        ctx,
    )
    assert write_result["status"] == "written"
    assert fake_fs.fs.get_section(curriculum["id"], "m2", "s1") is not None


@pytest.mark.asyncio
async def test_transition_phase_writing_to_review_blocked_by_pending_task(fake_fs):
    """writing->review is blocked when a plan task with a module_ref is still pending,
    even if every materialized section happens to be complete.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum("uid1", "prep", "prep", conversation_id=conv["id"])
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.set_plan(curriculum["id"], {"tasks": [
        {"id": "m1-s1", "title": "Intro", "module_ref": "m1", "status": "pending"},
    ]})

    tool = TransitionPhaseTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "writing"

    result = await tool.execute(TransitionPhaseInput(next_phase="review", reason="done"), ctx)
    assert "error" in result
    assert fake_fs.fs.get_agent_state(curriculum["id"]) is None  # no transition applied


@pytest.mark.asyncio
async def test_transition_phase_writing_to_review_blocked_by_planned_section(fake_fs):
    """writing->review is blocked when a materialized section doc is still "planned",
    even if the plan's tasks all say "done" (a write_section call that never happened)."""
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum("uid1", "prep", "prep", conversation_id=conv["id"])
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.set_plan(curriculum["id"], {"tasks": [
        {"id": "m1-s1", "title": "Intro", "module_ref": "m1", "status": "done"},
    ]})
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})
    fake_fs.fs.create_section(curriculum["id"], "m1", "s1", {"order": 0, "title": "Intro", "content_markdown": "", "citations": [], "status": "planned"})

    tool = TransitionPhaseTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "writing"

    result = await tool.execute(TransitionPhaseInput(next_phase="review", reason="done"), ctx)
    assert "error" in result


@pytest.mark.asyncio
async def test_transition_phase_writing_to_review_allowed_when_all_done(fake_fs):
    """writing->review succeeds once every task is done and no section is "planned"."""
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum("uid1", "prep", "prep", conversation_id=conv["id"])
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.set_plan(curriculum["id"], {"tasks": [
        {"id": "m1-s1", "title": "Intro", "module_ref": "m1", "status": "done"},
    ]})
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})
    fake_fs.fs.create_section(curriculum["id"], "m1", "s1", {"order": 0, "title": "Intro", "content_markdown": "x", "citations": [], "status": "complete"})

    tool = TransitionPhaseTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "writing"

    result = await tool.execute(TransitionPhaseInput(next_phase="review", reason="done"), ctx)
    assert result["status"] == "transitioned"
    # Dashboard-facing status must be the distinct "reviewing" (not lumped into "writing").
    assert fake_fs.fs.get_curriculum(curriculum["id"])["status"] == "reviewing"


@pytest.mark.asyncio
async def test_transition_phase_review_to_ready_blocked_by_incomplete_section(fake_fs):
    """review->ready is blocked when a section doc isn't "complete", even if the
    overview has been written."""
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum("uid1", "prep", "prep", conversation_id=conv["id"])
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.update_curriculum(curriculum["id"], {"overview": "A full overview."})
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "writing", "estimated_minutes": 5})
    fake_fs.fs.create_section(curriculum["id"], "m1", "s1", {"order": 0, "title": "Intro", "content_markdown": "x", "citations": [], "status": "writing"})

    tool = TransitionPhaseTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "review"

    result = await tool.execute(TransitionPhaseInput(next_phase="ready", reason="done"), ctx)
    assert "error" in result


@pytest.mark.asyncio
async def test_transition_phase_review_to_ready_blocked_by_missing_overview(fake_fs):
    """review->ready is blocked when the curriculum overview is empty, even if every
    section is complete."""
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum("uid1", "prep", "prep", conversation_id=conv["id"])
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})
    fake_fs.fs.create_section(curriculum["id"], "m1", "s1", {"order": 0, "title": "Intro", "content_markdown": "x", "citations": [], "status": "complete"})

    tool = TransitionPhaseTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "review"

    result = await tool.execute(TransitionPhaseInput(next_phase="ready", reason="done"), ctx)
    assert "error" in result


@pytest.mark.asyncio
async def test_transition_phase_review_to_ready_allowed_when_complete(fake_fs):
    """review->ready succeeds once every section is complete and the overview is set."""
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum("uid1", "prep", "prep", conversation_id=conv["id"])
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.update_curriculum(curriculum["id"], {"overview": "A full overview."})
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "complete", "estimated_minutes": 5})
    fake_fs.fs.create_section(curriculum["id"], "m1", "s1", {"order": 0, "title": "Intro", "content_markdown": "x", "citations": [], "status": "complete"})

    tool = TransitionPhaseTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    ctx.phase = "review"

    result = await tool.execute(TransitionPhaseInput(next_phase="ready", reason="done"), ctx)
    assert result["status"] == "transitioned"


def _read_call(tc_id: str, module_id: str, section_id: str, content: str | None) -> dict:
    """Build a fake `read_section` tool_call record.

    Args:
        tc_id (str): The tool call id.
        module_id (str): Section's module id (goes in `input`).
        section_id (str): Section id (goes in `input`).
        content (str | None): If given, `output_full` is a full section doc with this
            `content_markdown` (content-bearing); if None, `output_full` is an error
            observation (not content-bearing).

    Returns:
        dict: A tool_call record shaped like the ones the orchestrator persists.
    """
    if content is None:
        output = {"error": "section s9 not found in module m9"}
        status = "error"
    else:
        output = {"module_id": module_id, "section_id": section_id, "content_markdown": content}
        status = "ok"
    return {
        "id": tc_id,
        "name": "read_section",
        "input": {"module_id": module_id, "section_id": section_id},
        "output_full": json.dumps(output),
        "output_preview": "...",
        "status": status,
    }


def _write_call(
    tc_id: str, name: str, module_id: str, section_id: str, content: str, status: str = "ok"
) -> dict:
    """Build a fake `write_section`/`update_section` tool_call record.

    Args:
        tc_id (str): The tool call id.
        name (str): Either "write_section" or "update_section".
        module_id (str): Section's module id (goes in `input`).
        section_id (str): Section id (goes in `input`).
        content (str): The `content_markdown` carried in `input`.
        status (str): The call's recorded status ("ok" or "error").

    Returns:
        dict: A tool_call record shaped like the ones the orchestrator persists.
    """
    return {
        "id": tc_id,
        "name": name,
        "input": {
            "module_id": module_id,
            "section_id": section_id,
            "title": "Intro",
            "content_markdown": content,
            "citations": [{"id": 1, "url": "https://example.com", "title": "Example"}],
        },
        "output_full": json.dumps({"status": status, "module_id": module_id, "section_id": section_id}),
        "output_preview": "...",
        "status": status,
    }


def test_strip_stale_section_content_keeps_last_read_across_messages(fake_fs):
    """Two read_section calls on the same section in separate messages: the earlier
    output is stripped to {module_id, section_id, note}, the later one keeps content;
    returns 1.
    """
    conv = fake_fs.fs.create_conversation("uid1", "chat", curriculum_id="cur1")
    fake_fs.fs.append_message(
        conv["id"],
        {"role": "assistant", "content": "", "tool_calls": [_read_call("tc1", "m1", "s1", "old content")]},
    )
    fake_fs.fs.append_message(
        conv["id"],
        {"role": "assistant", "content": "", "tool_calls": [_read_call("tc2", "m1", "s1", "new content")]},
    )

    updated = strip_stale_section_content(conv["id"])
    assert updated == 1

    messages = fake_fs.fs.list_messages(conv["id"])
    rewritten = json.loads(messages[0]["tool_calls"][0]["output_full"])
    assert rewritten == {"module_id": "m1", "section_id": "s1", "note": _SECTION_CONTENT_STRIPPED_NOTE}

    kept = json.loads(messages[1]["tool_calls"][0]["output_full"])
    assert kept["content_markdown"] == "new content"


def test_strip_stale_section_content_error_write_then_ok_write(fake_fs):
    """A rejected write_section (status error, e.g. simulated lint rejection) followed by
    a successful write_section on the same section: the earlier call's input content is
    stripped (other input fields preserved, output_full untouched), the latest input
    keeps its content.
    """
    conv = fake_fs.fs.create_conversation("uid1", "chat", curriculum_id="cur1")
    fake_fs.fs.append_message(
        conv["id"],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_write_call("tc1", "write_section", "m1", "s1", "broken ```mermaid", status="error")],
        },
    )
    fake_fs.fs.append_message(
        conv["id"],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_write_call("tc2", "write_section", "m1", "s1", "fixed content", status="ok")],
        },
    )

    updated = strip_stale_section_content(conv["id"])
    assert updated == 1

    messages = fake_fs.fs.list_messages(conv["id"])
    first_tc = messages[0]["tool_calls"][0]
    assert first_tc["input"]["content_markdown"] == _SECTION_CONTENT_STRIPPED_NOTE
    assert first_tc["input"]["title"] == "Intro"
    assert first_tc["input"]["citations"] == [{"id": 1, "url": "https://example.com", "title": "Example"}]
    # output_full is a small status dict — left untouched by the input-only rewrite.
    assert json.loads(first_tc["output_full"])["status"] == "error"

    second_tc = messages[1]["tool_calls"][0]
    assert second_tc["input"]["content_markdown"] == "fixed content"


def test_strip_stale_section_content_cross_tool_write_then_read(fake_fs):
    """write_section then read_section on the same section: the write's input content is
    stripped once the later read supersedes it, the read's output is kept.
    """
    conv = fake_fs.fs.create_conversation("uid1", "chat", curriculum_id="cur1")
    fake_fs.fs.append_message(
        conv["id"],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_write_call("tc1", "write_section", "m1", "s1", "written content")],
        },
    )
    fake_fs.fs.append_message(
        conv["id"],
        {"role": "assistant", "content": "", "tool_calls": [_read_call("tc2", "m1", "s1", "written content")]},
    )

    updated = strip_stale_section_content(conv["id"])
    assert updated == 1

    messages = fake_fs.fs.list_messages(conv["id"])
    assert messages[0]["tool_calls"][0]["input"]["content_markdown"] == _SECTION_CONTENT_STRIPPED_NOTE
    kept_read = json.loads(messages[1]["tool_calls"][0]["output_full"])
    assert kept_read["content_markdown"] == "written content"


def test_strip_stale_section_content_cross_tool_read_then_update(fake_fs):
    """read_section then update_section on the same section: the read's output is
    stripped, the update's input content is kept.
    """
    conv = fake_fs.fs.create_conversation("uid1", "chat", curriculum_id="cur1")
    fake_fs.fs.append_message(
        conv["id"],
        {"role": "assistant", "content": "", "tool_calls": [_read_call("tc1", "m1", "s1", "old content")]},
    )
    fake_fs.fs.append_message(
        conv["id"],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_write_call("tc2", "update_section", "m1", "s1", "revised content")],
        },
    )

    updated = strip_stale_section_content(conv["id"])
    assert updated == 1

    messages = fake_fs.fs.list_messages(conv["id"])
    rewritten_read = json.loads(messages[0]["tool_calls"][0]["output_full"])
    assert "content_markdown" not in rewritten_read
    assert messages[1]["tool_calls"][0]["input"]["content_markdown"] == "revised content"


def test_strip_stale_section_content_different_sections_and_non_section_calls_untouched(fake_fs):
    """Different (module_id, section_id) keys don't affect each other, a non-section tool
    call (fetch_url) is left alone, and a section read/written only once is untouched —
    returns 0.
    """
    conv = fake_fs.fs.create_conversation("uid1", "chat", curriculum_id="cur1")
    fetch_output = json.dumps({"url": "https://example.com/z", "content_markdown": "page content"})
    fake_fs.fs.append_message(
        conv["id"],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                _read_call("tc1", "m1", "s1", "section one content"),
                _write_call("tc2", "write_section", "m2", "s1", "section two content"),
                {"id": "tc3", "name": "fetch_url", "input": {"url": "https://example.com/z"},
                 "output_full": fetch_output, "output_preview": "...", "status": "ok"},
            ],
        },
    )

    updated = strip_stale_section_content(conv["id"])
    assert updated == 0

    messages = fake_fs.fs.list_messages(conv["id"])
    tool_calls = {tc["id"]: tc for tc in messages[0]["tool_calls"]}
    assert json.loads(tool_calls["tc1"]["output_full"])["content_markdown"] == "section one content"
    assert tool_calls["tc2"]["input"]["content_markdown"] == "section two content"
    assert tool_calls["tc3"]["output_full"] == fetch_output


def test_strip_stale_section_content_no_matching_messages_returns_zero(fake_fs):
    """A conversation with no section-content tool calls updates nothing."""
    conv = fake_fs.fs.create_conversation("uid1", "chat", curriculum_id="cur1")
    fake_fs.fs.append_message(conv["id"], {"role": "user", "content": "hi"})
    assert strip_stale_section_content(conv["id"]) == 0


def test_strip_stale_section_content_is_idempotent(fake_fs):
    """Calling strip_stale_section_content a second time returns 0 and changes nothing
    further — the stripped-note sentinel keeps earlier writes from being re-treated as
    content-bearing.
    """
    conv = fake_fs.fs.create_conversation("uid1", "chat", curriculum_id="cur1")
    fake_fs.fs.append_message(
        conv["id"],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_write_call("tc1", "write_section", "m1", "s1", "old content")],
        },
    )
    fake_fs.fs.append_message(
        conv["id"],
        {"role": "assistant", "content": "", "tool_calls": [_read_call("tc2", "m1", "s1", "old content")]},
    )
    fake_fs.fs.append_message(
        conv["id"],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_write_call("tc3", "update_section", "m1", "s1", "final content")],
        },
    )

    first_run = strip_stale_section_content(conv["id"])
    assert first_run == 2  # tc1's write input and tc2's read output both superseded by tc3

    before = fake_fs.fs.list_messages(conv["id"])
    second_run = strip_stale_section_content(conv["id"])
    assert second_run == 0
    after = fake_fs.fs.list_messages(conv["id"])
    assert before == after
