"""propose_task_plan: binding id contract validation (`_validate_plan`).

Covers each rejection path (bad id format, module_ref mismatch, duplicate ids,
non-contiguous module/section numbering, invalid `modules` list, missing/mismatched
outline "Section X.Y" labels) plus the accept path for a fully valid plan — asserting
both the error observation shape and that no plan is persisted on rejection.
"""

from __future__ import annotations

import pytest

from app.agent.tools.base import AgentContext
from app.agent.tools.planning import (
    PlanModuleInput,
    PlanTaskInput,
    ProposeTaskPlanInput,
    ProposeTaskPlanTool,
)
from app.core.config import get_settings


def _make_ctx(curriculum_id: str, conversation_id: str) -> AgentContext:
    """Build a minimal `AgentContext` for exercising `ProposeTaskPlanTool` in isolation.

    Args:
        curriculum_id (str): Curriculum id to scope the context to.
        conversation_id (str): Conversation id to scope the context to.

    Returns:
        AgentContext: Context with a fixed owner uid, real settings, and placeholder
            (non-functional) LLM/search clients — sufficient since this tool only
            touches Firestore via the `fake_fs` fixture.
    """
    return AgentContext(
        curriculum_id=curriculum_id,
        conversation_id=conversation_id,
        owner_uid="uid1",
        settings=get_settings(),
        llm=object(),
        small_llm=object(),
        search=object(),
        phase="outline_planning",
    )


def _valid_outline() -> str:
    """Return an outline_markdown whose "Section X.Y" labels match the valid 3-task plan below."""
    return (
        "# Outline\n\n"
        "## Module 1\n"
        "Section 1.1: Intro\n"
        "Section 1.2: Fundamentals\n\n"
        "## Module 2\n"
        "Section 2.1: Practice\n"
    )


def _valid_tasks() -> list[dict]:
    """Return a valid 3-task plan (m1-s1, m1-s2, m2-s1) matching `_valid_outline`."""
    return [
        {"id": "m1-s1", "title": "Intro", "module_ref": "m1"},
        {"id": "m1-s2", "title": "Fundamentals", "module_ref": "m1"},
        {"id": "m2-s1", "title": "Practice", "module_ref": "m2"},
    ]


def _modules_for(tasks: list[dict]) -> list[dict]:
    """Auto-derive a valid `modules` list (one placeholder-titled/described entry per
    distinct module_ref, in first-appearance order) matching the module set used by
    `tasks` — keeps tests that aren't specifically about `modules` validation from
    tripping it.
    """
    seen: dict[str, None] = {}
    for t in tasks:
        ref = t.get("module_ref")
        if ref and ref not in seen:
            seen[ref] = None
    return [
        {"id": ref, "title": f"Module Title {ref}", "description": f"Description for {ref}."}
        for ref in seen
    ]


async def _run(
    fake_fs,
    outline_markdown: str,
    tasks: list[dict],
    modules: list[dict] | None = None,
    description: str = "A curriculum covering the essentials for interview prep.",
):
    """Set up a curriculum/conversation and execute propose_task_plan with the given input.

    Args:
        fake_fs: The `fake_fs` fixture (in-memory Firestore fake).
        outline_markdown (str): The outline_markdown to submit.
        tasks (list[dict]): Raw task dicts to submit as `PlanTaskInput`s.
        modules (list[dict] | None): Raw module dicts to submit as `PlanModuleInput`s;
            defaults to `_modules_for(tasks)` when omitted so tests unrelated to
            `modules` validation don't need to construct it manually.
        description (str): Curriculum-level `description` to submit; defaults to a
            valid placeholder so tests unrelated to description validation don't need
            to construct it manually.

    Returns:
        tuple: (result dict from tool.execute, curriculum_id) for further assertions.
    """
    conv = fake_fs.fs.create_conversation("uid1", "New conversation", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "prep for interviews", "prep for interviews", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})

    tool = ProposeTaskPlanTool()
    ctx = _make_ctx(curriculum["id"], conv["id"])
    result = await tool.execute(
        ProposeTaskPlanInput(
            outline_markdown=outline_markdown,
            description=description,
            tasks=[PlanTaskInput(**t) for t in tasks],
            modules=[PlanModuleInput(**m) for m in (modules if modules is not None else _modules_for(tasks))],
        ),
        ctx,
    )
    return result, curriculum["id"]


@pytest.mark.asyncio
async def test_propose_task_plan_accepts_valid_plan(fake_fs):
    """A plan with contiguous m{X}-s{Y} ids matching module_ref and an outline whose
    "Section X.Y" labels match 1:1 is accepted and persisted.
    """
    result, curriculum_id = await _run(fake_fs, _valid_outline(), _valid_tasks())
    assert result["status"] == "proposed"
    assert fake_fs.fs.get_plan(curriculum_id) is not None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_bad_id_format(fake_fs):
    """A slug task id (not matching 'm{X}-s{Y}') is rejected and nothing is persisted."""
    tasks = [{"id": "beyond-star", "title": "Intro", "module_ref": "m1"}]
    result, curriculum_id = await _run(fake_fs, "Section 1.1: Intro", tasks)
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_module_ref_mismatch(fake_fs):
    """A task whose module_ref doesn't match its own id prefix is rejected."""
    tasks = [{"id": "m1-s1", "title": "Intro", "module_ref": "m2"}]
    result, curriculum_id = await _run(fake_fs, "Section 1.1: Intro", tasks)
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_duplicate_ids(fake_fs):
    """Two tasks sharing the same id are rejected."""
    tasks = [
        {"id": "m1-s1", "title": "Intro", "module_ref": "m1"},
        {"id": "m1-s1", "title": "Intro again", "module_ref": "m1"},
    ]
    result, curriculum_id = await _run(fake_fs, "Section 1.1: Intro", tasks)
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_non_contiguous_module_numbering(fake_fs):
    """Modules jumping from m1 straight to m3 (skipping m2) are rejected."""
    tasks = [
        {"id": "m1-s1", "title": "Intro", "module_ref": "m1"},
        {"id": "m3-s1", "title": "Advanced", "module_ref": "m3"},
    ]
    outline = "Section 1.1: Intro\nSection 3.1: Advanced"
    result, curriculum_id = await _run(fake_fs, outline, tasks)
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_non_contiguous_section_numbering(fake_fs):
    """A module whose sections jump from s1 to s3 (skipping s2) is rejected."""
    tasks = [
        {"id": "m1-s1", "title": "Intro", "module_ref": "m1"},
        {"id": "m1-s3", "title": "Advanced", "module_ref": "m1"},
    ]
    outline = "Section 1.1: Intro\nSection 1.3: Advanced"
    result, curriculum_id = await _run(fake_fs, outline, tasks)
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_outline_without_section_labels(fake_fs):
    """An outline with no 'Section X.Y' labels at all is rejected with a specific message
    instructing the model to label every section line.
    """
    result, curriculum_id = await _run(fake_fs, "# Outline\n\n## Module 1\n- Intro", _valid_tasks()[:1])
    assert "error" in result
    assert "Section X.Y" in result["error"]
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_outline_tasks_mismatch(fake_fs):
    """An outline claiming more sections than tasks covers (e.g. 4 sections/module vs.
    1 task/module) is rejected, naming the missing-from-tasks section explicitly.
    """
    tasks = [{"id": "m1-s1", "title": "Intro", "module_ref": "m1"}]
    # Outline promises Section 1.2 but tasks only has m1-s1.
    outline = "Section 1.1: Intro\nSection 1.2: Fundamentals"
    result, curriculum_id = await _run(fake_fs, outline, tasks)
    assert "error" in result
    assert "1.2" in result["error"] or "m1-s2" in result["error"]
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_missing_module_ref():
    """module_ref is required — pydantic validation rejects a task omitting it entirely
    (the overview is no longer represented as a module_ref=None task).
    """
    with pytest.raises(Exception):
        PlanTaskInput(id="m1-s1", title="Overview", description="", module_ref=None)


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_modules_missing_a_module(fake_fs):
    """A `modules` list missing an entry for a module_ref used by tasks (m2) is rejected."""
    tasks = _valid_tasks()  # spans m1, m2
    modules = [{"id": "m1", "title": "Foundations", "description": "Covers the basics."}]  # missing m2 entirely
    result, curriculum_id = await _run(fake_fs, _valid_outline(), tasks, modules)
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_modules_wrong_order(fake_fs):
    """A `modules` list with the right ids but out of module-number order is rejected."""
    tasks = _valid_tasks()  # spans m1, m2
    modules = [
        {"id": "m2", "title": "Practice", "description": "Practice drills."},
        {"id": "m1", "title": "Foundations", "description": "Covers the basics."},
    ]
    result, curriculum_id = await _run(fake_fs, _valid_outline(), tasks, modules)
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_blank_module_title(fake_fs):
    """A `modules` entry with a whitespace-only title is rejected."""
    tasks = [{"id": "m1-s1", "title": "Intro", "module_ref": "m1"}]
    modules = [{"id": "m1", "title": "   ", "description": "Covers the basics."}]
    result, curriculum_id = await _run(fake_fs, "Section 1.1: Intro", tasks, modules)
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_module_title_too_long(fake_fs):
    """A `modules` entry with a title over 80 chars is rejected."""
    tasks = [{"id": "m1-s1", "title": "Intro", "module_ref": "m1"}]
    modules = [{"id": "m1", "title": "x" * 81, "description": "Covers the basics."}]
    result, curriculum_id = await _run(fake_fs, "Section 1.1: Intro", tasks, modules)
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_blank_module_description(fake_fs):
    """A `modules` entry with a whitespace-only description is rejected."""
    tasks = [{"id": "m1-s1", "title": "Intro", "module_ref": "m1"}]
    modules = [{"id": "m1", "title": "Foundations", "description": "   "}]
    result, curriculum_id = await _run(fake_fs, "Section 1.1: Intro", tasks, modules)
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_module_description_too_long(fake_fs):
    """A `modules` entry with a description over 300 chars is rejected."""
    tasks = [{"id": "m1-s1", "title": "Intro", "module_ref": "m1"}]
    modules = [{"id": "m1", "title": "Foundations", "description": "x" * 301}]
    result, curriculum_id = await _run(fake_fs, "Section 1.1: Intro", tasks, modules)
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_blank_curriculum_description(fake_fs):
    """A whitespace-only curriculum-level `description` is rejected."""
    result, curriculum_id = await _run(fake_fs, _valid_outline(), _valid_tasks(), description="   ")
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_rejects_curriculum_description_too_long(fake_fs):
    """A curriculum-level `description` over 300 chars is rejected."""
    result, curriculum_id = await _run(fake_fs, _valid_outline(), _valid_tasks(), description="x" * 301)
    assert "error" in result
    assert fake_fs.fs.get_plan(curriculum_id) is None


@pytest.mark.asyncio
async def test_propose_task_plan_accepted_plan_persists_modules(fake_fs):
    """A valid plan with a proper `modules` list persists `modules` verbatim on the plan doc."""
    tasks = _valid_tasks()
    modules = [
        {"id": "m1", "title": "Foundations", "description": "Covers the basics."},
        {"id": "m2", "title": "Practice Drills", "description": "Hands-on practice questions."},
    ]
    result, curriculum_id = await _run(fake_fs, _valid_outline(), tasks, modules)
    assert result["status"] == "proposed"
    saved_plan = fake_fs.fs.get_plan(curriculum_id)
    assert saved_plan is not None
    assert saved_plan["modules"] == modules


@pytest.mark.asyncio
async def test_propose_task_plan_writes_description_onto_curriculum_and_plan(fake_fs):
    """A successful propose_task_plan writes `description` onto both the curriculum doc
    (so the dashboard card can render it immediately) and the plan doc.
    """
    description = "A focused prep plan for backend interview loops."
    result, curriculum_id = await _run(fake_fs, _valid_outline(), _valid_tasks(), description=description)
    assert result["status"] == "proposed"
    saved_plan = fake_fs.fs.get_plan(curriculum_id)
    assert saved_plan["description"] == description
    curriculum = fake_fs.fs.get_curriculum(curriculum_id)
    assert curriculum["description"] == description
