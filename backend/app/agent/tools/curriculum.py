"""Curriculum content tools: structure listing, section read/write/update, overview, status."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.tools.base import AgentContext, Tool
from app.services import firestore as fs


class ListCurriculumStructureInput(BaseModel):
    """Input schema for `ListCurriculumStructureTool` (no fields — takes no arguments)."""

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
        """Build a compact modules/sections tree with statuses, without any content.

        Args:
            input (ListCurriculumStructureInput): Empty input (no fields).
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes which curriculum's structure is listed.

        Returns:
            dict[str, Any]: `{"modules": [...]}`, where each module dict has `id`,
                `order`, `title`, `status`, and a nested `sections` list (each with `id`,
                `order`, `title`, `status`) — `content_markdown`/`citations` are omitted.
        """
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
    """A single citation entry mirroring one `[^n]` footnote marker in section content."""

    id: int = Field(..., description="Sequential citation number matching the [^n] marker.")
    url: str
    title: str


class WriteSectionInput(BaseModel):
    """Input schema for `WriteSectionTool`."""

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
        """Create or overwrite a section's content, enforcing the citation requirement.

        This is the main code-level enforcement point for citations (per
        `app/agent/CLAUDE.md`): content over 400 stripped characters with no citations
        is rejected with an error observation rather than being written, forcing the
        model to either add citations or trim the content.

        Args:
            input (WriteSectionInput): The validated section fields (module_id,
                section_id, title, content_markdown, citations).
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes the write.

        Returns:
            dict[str, Any]: On success, `{"status": "written", "module_id",
                "section_id", "_ws_events": [...]}` — the `_ws_events` list carries a
                `curriculum_updated` (scope "section") and a `progress` event that the
                orchestrator pops and forwards to the client. As a side effect, also
                refreshes the parent module's derived `status` (planned/writing/complete,
                from its sections) and `estimated_minutes` (~200 wpm over written
                content) via `_refresh_module_status`. On the citation-guard failure,
                `{"error": "..."}` instead (no write performed).
        """
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

        # Preserve the existing order on overwrite; only assign a fresh order (append
        # to the end of the module) when this section id doesn't exist yet.
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
        # Derive the parent module's status/estimated_minutes from its sections now
        # that this write may have changed the picture (e.g. last planned section done).
        _refresh_module_status(ctx.curriculum_id, input.module_id)
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
    """Input schema for `ReadSectionTool`."""

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
        """Fetch a section's full stored document.

        Args:
            input (ReadSectionInput): The validated module_id/section_id to look up.
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes the lookup.

        Returns:
            dict[str, Any]: The full section document (order, title, content_markdown,
                citations, status) on success, or `{"error": "..."}` if not found.
        """
        section = fs.get_section(ctx.curriculum_id, input.module_id, input.section_id)
        if not section:
            return {"error": f"section {input.section_id} not found in module {input.module_id}"}
        return section


class UpdateSectionInput(BaseModel):
    """Input schema for `UpdateSectionTool`."""

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
        """Overwrite an existing section's content during refinement (requires prior existence).

        Unlike `WriteSectionTool`, this tool refuses to create a new section — it is
        strictly for revising a section already produced during writing/review.

        Args:
            input (UpdateSectionInput): The validated revised content, citations, and a
                required plain-language change_note.
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes the update.

        Returns:
            dict[str, Any]: On success, `{"status": "updated", "change_note",
                "_ws_events": [...]}` with a `curriculum_updated` (scope "section")
                event for the orchestrator to forward. Also refreshes the parent
                module's derived `status`/`estimated_minutes` via
                `_refresh_module_status`, since edited content changes reading time.
                `{"error": "..."}` if the section doesn't exist yet.
        """
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
        # Content edits change word count, so re-derive the module's reading time too.
        _refresh_module_status(ctx.curriculum_id, input.module_id)
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
    """Input schema for `WriteCurriculumOverviewTool`."""

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
        """Set the curriculum's overview markdown, emoji, and tags.

        Args:
            input (WriteCurriculumOverviewInput): The validated overview markdown,
                optional emoji, and tags list.
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                identifies which curriculum document to update.

        Returns:
            dict[str, Any]: `{"status": "updated", "_ws_events": [...]}` with a
                `curriculum_updated` (scope "overview") event for the orchestrator to
                forward to the client.
        """
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
    """Input schema for `SetCurriculumTitleTool`."""

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
        """Rename the curriculum, updating both the curriculum doc and conversation title.

        Args:
            input (SetCurriculumTitleInput): The validated new title (<=80 chars) and
                optional emoji.
            ctx (AgentContext): The current agent run's context; both `ctx.curriculum_id`
                and `ctx.conversation_id` are updated so the dashboard/sidebar stay
                in sync with the curriculum document.

        Returns:
            dict[str, Any]: `{"status": "updated", "title", "_ws_event": {...}}` with a
                `curriculum_updated` (scope "curriculum") event for the orchestrator to
                forward.
        """
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
    """Input schema for `SetModuleStatusTool`."""

    module_id: str = Field(..., description="The module id.")
    status: Literal["planned", "writing", "complete"] = Field(..., description="New status for the module.")


class SetModuleStatusTool(Tool):
    name = "set_module_status"
    description = (
        "Update a module's status (planned/writing/complete). Use as an internal bookkeeping "
        "helper when starting or finishing work on a module's sections as a whole. Emits a "
        "curriculum_updated event (scope 'module') so the frontend refreshes."
    )
    input_model = SetModuleStatusInput

    async def execute(self, input: SetModuleStatusInput, ctx: AgentContext) -> dict[str, Any]:
        """Update a module's status field and notify the client to refetch.

        Args:
            input (SetModuleStatusInput): The validated module_id and new status.
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes the lookup/update.

        Returns:
            dict[str, Any]: `{"status": "updated", "module_id", "new_status",
                "_ws_event": {...}}` on success — the `_ws_event` carries a
                `curriculum_updated` (scope "module") event that the orchestrator pops
                and forwards, so a manual status change refreshes the frontend. Returns
                `{"error": "..."}` if the module doesn't exist.
        """
        module = fs.get_module(ctx.curriculum_id, input.module_id)
        if not module:
            return {"error": f"module {input.module_id} not found"}
        fs.update_module(ctx.curriculum_id, input.module_id, {"status": input.status})
        return {
            "status": "updated",
            "module_id": input.module_id,
            "new_status": input.status,
            "_ws_event": {
                "type": "curriculum_updated",
                "curriculum_id": ctx.curriculum_id,
                "scope": "module",
                "module_id": input.module_id,
            },
        }


# --------------------------------------------------------------------------------------
# internal helpers
# --------------------------------------------------------------------------------------


def _next_section_order(curriculum_id: str, module_id: str) -> int:
    """Compute the next append-order index for a new section within a module.

    Args:
        curriculum_id (str): The curriculum containing the module.
        module_id (str): The module to count existing sections for.

    Returns:
        int: The count of existing sections in the module, used as the new section's
            `order` value (i.e. sections are ordered by creation/append order).
    """
    sections = fs.list_sections(curriculum_id, module_id)
    return len(sections)


def _mark_task_done(curriculum_id: str, task_id: str) -> None:
    """Mark the plan task matching `task_id` as done and remove it from the working task_queue.

    No-ops silently if there is no plan yet, or if no task in the plan matches
    `task_id` (e.g. a section written outside the normal plan-driven flow).

    Args:
        curriculum_id (str): The curriculum whose plan/state to update.
        task_id (str): The task id to mark done — by convention this equals the
            section_id, since each planned task maps 1:1 to a section stub.
    """
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

    # Advance the working-memory task queue: drop the now-done task and point
    # current_task_id at whatever is next (or None if the queue is now empty).
    state = fs.get_agent_state(curriculum_id) or {}
    queue = [t for t in state.get("task_queue", []) if t != task_id]
    fs.set_agent_state(curriculum_id, {"task_queue": queue, "current_task_id": queue[0] if queue else None})


def _task_progress(curriculum_id: str) -> tuple[int, int]:
    """Compute (completed, total) task counts from the curriculum's plan.

    Args:
        curriculum_id (str): The curriculum whose plan to inspect.

    Returns:
        tuple[int, int]: `(completed_count, total_count)`, or `(0, 0)` if no plan
            exists yet.
    """
    plan = fs.get_plan(curriculum_id)
    if not plan:
        return 0, 0
    tasks = plan.get("tasks", [])
    completed = sum(1 for t in tasks if t.get("status") == "done")
    return completed, len(tasks)


def _refresh_curriculum_counts(curriculum_id: str) -> None:
    """Recompute and persist the curriculum's cached module_count/section_count fields.

    Args:
        curriculum_id (str): The curriculum to recount and update.
    """
    modules = fs.list_modules(curriculum_id)
    section_count = sum(len(fs.list_sections(curriculum_id, m["id"])) for m in modules)
    fs.update_curriculum(curriculum_id, {"module_count": len(modules), "section_count": section_count})


def _refresh_module_status(curriculum_id: str, module_id: str) -> None:
    """Derive and persist a module's `status` and `estimated_minutes` from its sections.

    Called after any section write/update so the UI never shows a stale "planned"/
    "0m" module even if the LLM never explicitly calls `set_module_status`. No-ops if
    the module has no sections yet (nothing to derive from).

    Args:
        curriculum_id (str): The curriculum containing the module.
        module_id (str): The module whose derived fields to recompute.

    Returns:
        None: Persists via `fs.update_module`; nothing is returned.
    """
    sections = fs.list_sections(curriculum_id, module_id)
    if not sections:
        return

    # Status: complete only when every section is complete; writing if any section
    # is in-progress or already done; otherwise still fully planned.
    statuses = {s.get("status") for s in sections}
    if statuses == {"complete"}:
        status = "complete"
    elif "complete" in statuses or "writing" in statuses:
        status = "writing"
    else:
        status = "planned"

    # Reading time: ~200 words/minute over all sections' written content, rounded up.
    word_count = sum(len(s.get("content_markdown", "").split()) for s in sections)
    estimated_minutes = (word_count + 199) // 200 if word_count else 0

    fs.update_module(curriculum_id, module_id, {"status": status, "estimated_minutes": estimated_minutes})
