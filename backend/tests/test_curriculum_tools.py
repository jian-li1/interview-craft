"""Curriculum tools: set_curriculum_title updates both curriculum + conversation;
write_section/update_section auto-derive parent module status/estimated_minutes;
set_module_status emits a curriculum_updated WS event; write_section and
transition_phase persist progress onto the curriculum doc for REST readers;
write_section/update_section reject broken Mermaid diagrams at write time;
write_section's target guard rejects invented module/section ids in writing/review and
enforces next-sequential-id creation in refinement; transition_phase's writing->review and
review->ready completeness gates block premature phase exits; transition_phase also allows
the plan-revision loop-backs awaiting_approval->deep_research and
outline_planning->deep_research.
"""

from __future__ import annotations

import pytest

from app.agent.tools.base import AgentContext
from app.agent.tools.control import TransitionPhaseInput, TransitionPhaseTool
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
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    # refinement allows creating a new section at the next sequential id (s1, since
    # none exist yet) — this exercises the mermaid guard rather than the target guard.
    ctx.phase = "refinement"
    broken_content = "Intro text.\n\n```mermaid\nflowchart TD\n    A[Review (Optional)] --> B\n```\n"

    result = await tool.execute(
        WriteSectionInput(module_id="m1", section_id="s1", title="Section 1", content_markdown=broken_content, citations=[]),
        ctx,
    )

    assert "error" in result
    assert fake_fs.fs.get_section(curriculum["id"], "m1", "s1") is None


@pytest.mark.asyncio
async def test_write_section_accepts_valid_mermaid(fake_fs):
    """write_section with a correctly-quoted mermaid block succeeds and persists the section."""
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep for a system design interview", "prep for a system design interview", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    fake_fs.fs.create_module(curriculum["id"], "m1", {"order": 0, "title": "Module 1", "status": "planned", "estimated_minutes": 0})

    tool = WriteSectionTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    # refinement allows creating a new section at the next sequential id (s1).
    ctx.phase = "refinement"
    valid_content = 'Intro text.\n\n```mermaid\nflowchart TD\n    A["Screen"] --> B["Onsite"]\n```\n'

    result = await tool.execute(
        WriteSectionInput(module_id="m1", section_id="s1", title="Section 1", content_markdown=valid_content, citations=[]),
        ctx,
    )

    assert result["status"] == "written"
    written = fake_fs.fs.get_section(curriculum["id"], "m1", "s1")
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
async def test_write_section_refinement_auto_creates_next_sequential_module(fake_fs):
    """In refinement, write_section may create a brand-new module, but only at the next
    sequential id (m2, since only m1 exists) — the module doc is auto-created as a
    planned stub (write_section is the only module-creation path in refinement).
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
    assert result["status"] == "written"
    new_module = fake_fs.fs.get_module(curriculum["id"], "m2")
    assert new_module is not None
    assert new_module["title"] == "New Module"  # split(":")[0] applied to the section title
    # Auto-created as "planned", but _refresh_module_status (which runs right after,
    # same as any write_section call) immediately derives "complete" from its one
    # now-complete section — so by the time the write returns it's already "complete".
    assert new_module["status"] == "complete"


@pytest.mark.asyncio
async def test_write_section_refinement_rejects_non_sequential_new_module(fake_fs):
    """In refinement, a brand-new module id that isn't the next sequential one (m3 when
    only m1 exists, skipping m2) is rejected.
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
