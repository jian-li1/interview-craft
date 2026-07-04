"""Curriculum content tools: structure listing, section read/write/update, overview, status."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.tools.base import AgentContext, Tool
from app.services import firestore as fs


class ListCurriculumStructureInput(BaseModel):
    pass


class ListCurriculumStructureTool(Tool):
    name = "list_curriculum_structure"
    description = (
        "List the curriculum's modules and sections tree with their statuses (compact form: "
        "ids, titles, order, status) — no full content. Use this to orient yourself before "
        "reading/writing specific sections, or to check overall completion during review."
    )
    input_model = ListCurriculumStructureInput

    async def execute(self, input: ListCurriculumStructureInput, ctx: AgentContext) -> dict[str, Any]:
        modules = fs.list_modules(ctx.curriculum_id)
        tree = []
        for m in modules:
            sections = fs.list_sections(ctx.curriculum_id, m["id"])
            tree.append(
                {
                    "id": m["id"],
                    "order": m.get("order"),
                    "title": m.get("title"),
                    "status": m.get("status"),
                    "sections": [
                        {
                            "id": s["id"],
                            "order": s.get("order"),
                            "title": s.get("title"),
                            "status": s.get("status"),
                        }
                        for s in sections
                    ],
                }
            )
        return {"modules": tree}


class CitationInput(BaseModel):
    id: int = Field(..., description="Sequential citation number matching the [^n] marker.")
    url: str
    title: str


class WriteSectionInput(BaseModel):
    module_id: str = Field(..., description="The module id this section belongs to.")
    section_id: str = Field(..., description="The section id (slug) to write/create.")
    title: str = Field(..., description="Section title.")
    content_markdown: str = Field(
        ..., description="Full rich markdown content, including [^n] citation markers and a ## Sources footnote list."
    )
    citations: list[CitationInput] = Field(
        default_factory=list, description="Citations mirroring every [^n] marker used in content_markdown."
    )


class WriteSectionTool(Tool):
    name = "write_section"
    description = (
        "Write (create or overwrite) a curriculum section's full content. Validates that "
        "citations are non-empty for research-based content (raises an error observation if "
        "you submit substantial content with zero citations — add citations or explicitly "
        "keep the section citation-free only when it truly makes no factual claims). Marks "
        "the corresponding task done if one exists, marks the section/module status, and "
        "emits curriculum_updated + progress events to the client."
    )
    input_model = WriteSectionInput

    async def execute(self, input: WriteSectionInput, ctx: AgentContext) -> dict[str, Any]:
        if len(input.content_markdown.strip()) > 400 and not input.citations:
            return {
                "error": (
                    "content_markdown looks substantial but citations is empty. "
                    "Research-grounded content must cite sources (see citation_guidelines.md). "
                    "If this section truly makes no factual claims, keep it much shorter or "
                    "explicitly note why no citation is needed."
                )
            }

        now = dt.datetime.now(dt.timezone.utc)
        citations = [
            {"id": c.id, "url": c.url, "title": c.title, "accessed_at": now} for c in input.citations
        ]

        existing = fs.get_section(ctx.curriculum_id, input.module_id, input.section_id)
        order = existing.get("order", 0) if existing else _next_section_order(ctx.curriculum_id, input.module_id)

        fields = {
            "order": order,
            "title": input.title,
            "content_markdown": input.content_markdown,
            "citations": citations,
            "status": "complete",
        }
        if existing:
            fs.update_section(ctx.curriculum_id, input.module_id, input.section_id, fields)
        else:
            fs.create_section(ctx.curriculum_id, input.module_id, input.section_id, fields)

        _mark_task_done(ctx.curriculum_id, input.section_id)
        _refresh_curriculum_counts(ctx.curriculum_id)
        completed, total = _task_progress(ctx.curriculum_id)

        return {
            "status": "written",
            "module_id": input.module_id,
            "section_id": input.section_id,
            "_ws_events": [
                {
                    "type": "curriculum_updated",
                    "curriculum_id": ctx.curriculum_id,
                    "scope": "section",
                    "module_id": input.module_id,
                    "section_id": input.section_id,
                },
                {
                    "type": "progress",
                    "completed": completed,
                    "total": total,
                    "detail": f"Wrote section: {input.title}",
                },
            ],
        }


class ReadSectionInput(BaseModel):
    module_id: str = Field(..., description="The module id.")
    section_id: str = Field(..., description="The section id.")


class ReadSectionTool(Tool):
    name = "read_section"
    description = (
        "Read a section's full current content (for explanation in chat or before making a "
        "refinement edit). Always call this before update_section — never blind-edit."
    )
    input_model = ReadSectionInput

    async def execute(self, input: ReadSectionInput, ctx: AgentContext) -> dict[str, Any]:
        section = fs.get_section(ctx.curriculum_id, input.module_id, input.section_id)
        if not section:
            return {"error": f"section {input.section_id} not found in module {input.module_id}"}
        return section


class UpdateSectionInput(BaseModel):
    module_id: str = Field(..., description="The module id.")
    section_id: str = Field(..., description="The section id.")
    content_markdown: str = Field(..., description="The full revised markdown content.")
    citations: list[CitationInput] = Field(default_factory=list)
    change_note: str = Field(..., description="Plain-language changelog entry describing what changed and why.")


class UpdateSectionTool(Tool):
    name = "update_section"
    description = (
        "Update an existing section's content during refinement. Use for targeted edits after "
        "reading the current content with read_section. Provide a clear change_note describing "
        "what changed — this is surfaced to the user as a changelog entry."
    )
    input_model = UpdateSectionInput

    async def execute(self, input: UpdateSectionInput, ctx: AgentContext) -> dict[str, Any]:
        existing = fs.get_section(ctx.curriculum_id, input.module_id, input.section_id)
        if not existing:
            return {"error": f"section {input.section_id} not found in module {input.module_id}"}

        now = dt.datetime.now(dt.timezone.utc)
        citations = [
            {"id": c.id, "url": c.url, "title": c.title, "accessed_at": now} for c in input.citations
        ]
        fs.update_section(
            ctx.curriculum_id,
            input.module_id,
            input.section_id,
            {
                "content_markdown": input.content_markdown,
                "citations": citations,
                "status": "complete",
            },
        )
        return {
            "status": "updated",
            "change_note": input.change_note,
            "_ws_events": [
                {
                    "type": "curriculum_updated",
                    "curriculum_id": ctx.curriculum_id,
                    "scope": "section",
                    "module_id": input.module_id,
                    "section_id": input.section_id,
                }
            ],
        }


class WriteCurriculumOverviewInput(BaseModel):
    overview_markdown: str = Field(..., description="Markdown overview of the whole curriculum.")
    emoji: str | None = Field(None, description="A single representative emoji for the curriculum.")
    tags: list[str] = Field(default_factory=list, description="Short topical tags for the curriculum.")


class WriteCurriculumOverviewTool(Tool):
    name = "write_curriculum_overview"
    description = (
        "Set the curriculum's overview markdown and metadata (emoji, tags). Typically called "
        "once during the writing/review phases once the curriculum's overall shape is clear."
    )
    input_model = WriteCurriculumOverviewInput

    async def execute(self, input: WriteCurriculumOverviewInput, ctx: AgentContext) -> dict[str, Any]:
        fs.update_curriculum(
            ctx.curriculum_id,
            {"overview": input.overview_markdown, "emoji": input.emoji, "tags": input.tags},
        )
        return {
            "status": "updated",
            "_ws_events": [
                {
                    "type": "curriculum_updated",
                    "curriculum_id": ctx.curriculum_id,
                    "scope": "overview",
                }
            ],
        }


class SetCurriculumTitleInput(BaseModel):
    title: str = Field(
        ...,
        max_length=80,
        description=(
            "Concise, descriptive, human-friendly curriculum title (<=80 chars), e.g. "
            "'Google SWE Interview Prep — 3-Week Plan'. Avoid generic titles like "
            "'Interview Prep' when there is enough signal to be specific."
        ),
    )
    emoji: str | None = Field(
        None, description="A single fitting emoji representing the curriculum, if you have one."
    )


class SetCurriculumTitleTool(Tool):
    name = "set_curriculum_title"
    description = (
        "Set (or rename) the curriculum's display title and optionally its emoji. Call this "
        "as one of your FIRST actions during intake to replace the placeholder title derived "
        "from the user's raw prompt with a concise, specific, human-friendly name — e.g. "
        "'Google Software Engineer Interview Prep' rather than a truncated copy of what the "
        "user typed. Updates both the curriculum document and the conversation's sidebar/"
        "dashboard title so they stay in sync. Can also be called later (e.g. during "
        "refinement) if the user asks to rename the curriculum."
    )
    input_model = SetCurriculumTitleInput

    async def execute(self, input: SetCurriculumTitleInput, ctx: AgentContext) -> dict[str, Any]:
        curriculum_fields: dict[str, Any] = {"title": input.title}
        if input.emoji:
            curriculum_fields["emoji"] = input.emoji
        fs.update_curriculum(ctx.curriculum_id, curriculum_fields)
        fs.update_conversation(ctx.conversation_id, {"title": input.title})
        return {
            "status": "updated",
            "title": input.title,
            "_ws_event": {
                "type": "curriculum_updated",
                "curriculum_id": ctx.curriculum_id,
                "scope": "curriculum",
            },
        }


class SetModuleStatusInput(BaseModel):
    module_id: str = Field(..., description="The module id.")
    status: Literal["planned", "writing", "complete"] = Field(..., description="New status for the module.")


class SetModuleStatusTool(Tool):
    name = "set_module_status"
    description = (
        "Update a module's status (planned/writing/complete). Use as an internal bookkeeping "
        "helper when starting or finishing work on a module's sections as a whole."
    )
    input_model = SetModuleStatusInput

    async def execute(self, input: SetModuleStatusInput, ctx: AgentContext) -> dict[str, Any]:
        module = fs.get_module(ctx.curriculum_id, input.module_id)
        if not module:
            return {"error": f"module {input.module_id} not found"}
        fs.update_module(ctx.curriculum_id, input.module_id, {"status": input.status})
        return {"status": "updated", "module_id": input.module_id, "new_status": input.status}


# --------------------------------------------------------------------------------------
# internal helpers
# --------------------------------------------------------------------------------------


def _next_section_order(curriculum_id: str, module_id: str) -> int:
    sections = fs.list_sections(curriculum_id, module_id)
    return len(sections)


def _mark_task_done(curriculum_id: str, task_id: str) -> None:
    plan = fs.get_plan(curriculum_id)
    if not plan:
        return
    tasks = plan.get("tasks", [])
    changed = False
    for t in tasks:
        if t.get("id") == task_id and t.get("status") != "done":
            t["status"] = "done"
            changed = True
    if changed:
        fs.set_plan(curriculum_id, {"tasks": tasks})

    state = fs.get_agent_state(curriculum_id) or {}
    queue = [t for t in state.get("task_queue", []) if t != task_id]
    fs.set_agent_state(curriculum_id, {"task_queue": queue, "current_task_id": queue[0] if queue else None})


def _task_progress(curriculum_id: str) -> tuple[int, int]:
    plan = fs.get_plan(curriculum_id)
    if not plan:
        return 0, 0
    tasks = plan.get("tasks", [])
    completed = sum(1 for t in tasks if t.get("status") == "done")
    return completed, len(tasks)


def _refresh_curriculum_counts(curriculum_id: str) -> None:
    modules = fs.list_modules(curriculum_id)
    section_count = sum(len(fs.list_sections(curriculum_id, m["id"])) for m in modules)
    fs.update_curriculum(curriculum_id, {"module_count": len(modules), "section_count": section_count})
