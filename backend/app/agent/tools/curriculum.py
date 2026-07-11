"""Curriculum content tools: structure listing, section read/write/update, overview, status."""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.tools.base import AgentContext, Tool
from app.core.logging import get_logger
from app.services import firestore as fs

logger = get_logger(__name__)

# Matches numbered module/section doc ids ("m1", "s12", ...) so create_module and
# write_section's ready/refinement guards can compute the expected next sequential id.
_NUMBERED_MODULE_ID_RE = re.compile(r"^m(\d+)$")
_NUMBERED_SECTION_ID_RE = re.compile(r"^s(\d+)$")

# Tool names whose calls carry a section's content_markdown somewhere in their
# input/output and are therefore in scope for strip_stale_section_content.
_SECTION_CONTENT_TOOLS = ("read_section", "write_section", "update_section")

# Replacement text for a stripped content_markdown input — also serves as the
# idempotence sentinel so a re-run doesn't treat stripped calls as content-bearing.
_SECTION_CONTENT_STRIPPED_NOTE = (
    "section content removed — this section was read or written again later in the "
    "conversation; the latest read_section/write_section/update_section call for this "
    "section carries the current content (re-read with read_section if needed)"
)


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
        "Write a curriculum section's full content. During writing/review, this ONLY accepts "
        "module_id/section_id already materialized from the approved plan (e.g. 'm1'/'s1') and "
        "overwrites that planned stub — any other id is rejected with an error observation "
        "naming the existing ids; never invent a new module or section here, and the curriculum "
        "overview is never a section, use write_curriculum_overview. During ready/refinement, "
        "write_section ONLY creates a brand-new section within an ALREADY-EXISTING module, at "
        "exactly the next sequential id ('s{K+1}', K = the module's current highest section "
        "number) — an arbitrary or gapped section id is rejected, and so is a section id that "
        "already exists (edit existing content with update_section instead, never write_section). "
        "write_section NEVER creates a module in any phase — to add a brand-new module, call "
        "create_module first (id 'm{N+1}', a title, and a description), then write_section its "
        "sections starting at 's1'. Validates that citations are non-empty for research-based "
        "content (raises an error observation if you submit substantial content with zero "
        "citations — add citations or explicitly keep the section citation-free only when it "
        "truly makes no factual claims). Marks the corresponding task done if one exists, marks "
        "the section/module status, and emits curriculum_updated + progress events to the client."
    )
    input_model = WriteSectionInput

    async def execute(self, input: WriteSectionInput, ctx: AgentContext) -> dict[str, Any]:
        """Create (or, during writing/review, overwrite) a section's content, enforcing citations.

        This is the main code-level enforcement point for citations (per
        `app/agent/CLAUDE.md`): content over 400 stripped characters with no
        citations is rejected with an error observation rather than being written,
        forcing the model to fix the issue and resubmit the full corrected content.

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
                content) via `_refresh_module_status`, and persists task progress onto
                the curriculum doc's `progress` field via `_refresh_curriculum_progress`
                (so REST readers like the dashboard see it, not just live WS clients).
                On the citation-guard failure, `{"error": "..."}` instead (no write
                performed). Also `{"error": "..."}` if the target guard rejects
                module_id/section_id (see `_validate_write_target`) — checked first since
                a wrong target invalidates everything else; in particular, during ready/
                refinement this now also rejects an already-existing section (use
                update_section) and a missing module (create it first with create_module).
        """
        # Target guard: catch invented/phantom module or section ids, and (in ready/
        # refinement) already-existing sections, before any other check.
        target_error = _validate_write_target(ctx.curriculum_id, ctx.phase, input.module_id, input.section_id)
        if target_error:
            return {"error": target_error}

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

        _mark_task_done(ctx.curriculum_id, input.module_id, input.section_id)
        _refresh_curriculum_counts(ctx.curriculum_id)
        # Derive the parent module's status/estimated_minutes from its sections now
        # that this write may have changed the picture (e.g. last planned section done).
        _refresh_module_status(ctx.curriculum_id, input.module_id)
        # Persist progress onto the curriculum doc (not just the transient WS event) so
        # REST readers like the dashboard card see live progress, not just live sockets.
        completed, total = _refresh_curriculum_progress(
            ctx.curriculum_id, ctx.phase, f"Wrote section: {input.title}"
        )

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
                `{"error": "..."}` if the section doesn't exist yet (no update
                performed).
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


class CreateModuleInput(BaseModel):
    """Input schema for `CreateModuleTool`."""

    module_id: str = Field(
        ...,
        description=(
            "The new module's id — must be exactly the next sequential id 'm{N+1}' (N = the "
            "current highest numbered module id); arbitrary slugs or gapped numbers are rejected "
            "with an error naming the expected id."
        ),
    )
    title: str = Field(
        ...,
        description="The module's real display title, non-empty, at most 80 characters.",
    )
    description: str = Field(
        ...,
        description=(
            "1-2 sentence summary of what this module covers, shown under its title on the "
            "workflow node card, the reader module header, and the dashboard. Plain prose, "
            "non-empty, at most 300 characters — never a restatement of the title."
        ),
    )


class CreateModuleTool(Tool):
    name = "create_module"
    description = (
        "Create a brand-new module during ready/refinement, when a request needs a genuinely "
        "new top-level module rather than a new section in an existing one. module_id must be "
        "exactly the next sequential id 'm{N+1}' (N = the current highest numbered module id) — "
        "arbitrary slugs are rejected with an error naming the expected id, and an already-"
        "existing module id is rejected too (use update_module for metadata edits instead). "
        "title is the module's real display title (<=80 chars); description is a real 1-2 "
        "sentence summary (<=300 chars, same quality bar as plan-time module descriptions) shown "
        "on the workflow node card, reader module header, and dashboard — never a copy of the "
        "title. After creating the module, add its content with write_section starting at 's1' "
        "(write_section itself never creates modules). To edit an existing module's title/"
        "description, use update_module instead of create_module."
    )
    input_model = CreateModuleInput

    async def execute(self, input: CreateModuleInput, ctx: AgentContext) -> dict[str, Any]:
        """Create a new module doc at the next sequential id, with a validated title/description.

        Args:
            input (CreateModuleInput): The validated module_id, title, and description.
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes the write.

        Returns:
            dict[str, Any]: On success, `{"status": "created", "module_id", "title",
                "_ws_event": {...}}` with a `curriculum_updated` (scope "module") event
                for the orchestrator to forward. `{"error": "..."}` if title/description
                fail bounds validation, the module_id already exists (use update_module
                instead), or module_id isn't the next sequential id.
        """
        # Bounds-check title/description first — same limits as propose_task_plan's
        # module validation, since both render on the same workflow node card.
        title_error = _validate_module_title(input.title)
        if title_error:
            return {"error": title_error}
        description_error = _validate_module_description(input.description)
        if description_error:
            return {"error": description_error}

        # Single fs.list_modules call feeds both the existence check and the expected-id
        # computation below.
        existing_modules = fs.list_modules(ctx.curriculum_id)
        if any(m["id"] == input.module_id for m in existing_modules):
            return {
                "error": (
                    f"module {input.module_id!r} already exists — create_module only creates "
                    f"brand-new modules. To edit its title/description, use update_module instead."
                )
            }

        max_n = 0
        for m in existing_modules:
            match = _NUMBERED_MODULE_ID_RE.match(m["id"])
            if match:
                max_n = max(max_n, int(match.group(1)))
        expected = f"m{max_n + 1}"
        if input.module_id != expected:
            return {
                "error": (
                    f"module_id {input.module_id!r} is not the next sequential module id. "
                    f"create_module requires exactly {expected!r} — arbitrary module ids are "
                    f"rejected."
                )
            }

        # Same doc shape as legacy write_section auto-creation (order/objectives/status/
        # estimated_minutes defaults), but with a real caller-provided title/description.
        fs.create_module(
            ctx.curriculum_id,
            input.module_id,
            {
                "order": len(existing_modules),
                "title": input.title,
                "description": input.description,
                "objectives": [],
                "status": "planned",
                "estimated_minutes": 0,
            },
        )
        _refresh_curriculum_counts(ctx.curriculum_id)

        return {
            "status": "created",
            "module_id": input.module_id,
            "title": input.title,
            "_ws_event": {
                "type": "curriculum_updated",
                "curriculum_id": ctx.curriculum_id,
                "scope": "module",
                "module_id": input.module_id,
            },
        }


class UpdateModuleInput(BaseModel):
    """Input schema for `UpdateModuleTool`."""

    module_id: str = Field(..., description="The existing module id to update.")
    title: str | None = Field(
        None, description="New display title (<=80 chars). Omit to leave the current title unchanged."
    )
    description: str | None = Field(
        None,
        description="New 1-2 sentence summary (<=300 chars). Omit to leave the current description unchanged.",
    )


class UpdateModuleTool(Tool):
    name = "update_module"
    description = (
        "Update an existing module's display title and/or description during ready/refinement "
        "— e.g. the user asks to rename a module, or its description has gone stale after "
        "content changes elsewhere in the module. Provide at least one of title/description; "
        "whichever you omit is left unchanged. Does NOT touch the module's sections, status, or "
        "ordering — use write_section/update_section for content and set_module_status for "
        "status. To create a brand-new module instead, use create_module."
    )
    input_model = UpdateModuleInput

    async def execute(self, input: UpdateModuleInput, ctx: AgentContext) -> dict[str, Any]:
        """Update whichever of a module's title/description fields were provided.

        Args:
            input (UpdateModuleInput): The validated module_id and optional new title/
                description (at least one must be set).
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes the update.

        Returns:
            dict[str, Any]: On success, `{"status": "updated", "module_id",
                "updated_fields": [...], "_ws_event": {...}}` with a `curriculum_updated`
                (scope "module") event for the orchestrator to forward. `{"error": "..."}`
                if the module doesn't exist, if neither field was provided, or if a
                provided field fails bounds validation (no write performed in any case).
        """
        module = fs.get_module(ctx.curriculum_id, input.module_id)
        if not module:
            existing_ids = sorted(m["id"] for m in fs.list_modules(ctx.curriculum_id))
            return {
                "error": (
                    f"module {input.module_id!r} not found. Existing module ids: {existing_ids}. "
                    f"To create a new module, use create_module instead."
                )
            }

        if input.title is None and input.description is None:
            return {"error": "provide at least one of title/description to update."}

        # Only validate/include the fields actually provided — merge update, not overwrite.
        fields: dict[str, Any] = {}
        if input.title is not None:
            title_error = _validate_module_title(input.title)
            if title_error:
                return {"error": title_error}
            fields["title"] = input.title
        if input.description is not None:
            description_error = _validate_module_description(input.description)
            if description_error:
                return {"error": description_error}
            fields["description"] = input.description

        fs.update_module(ctx.curriculum_id, input.module_id, fields)

        return {
            "status": "updated",
            "module_id": input.module_id,
            "updated_fields": list(fields.keys()),
            "_ws_event": {
                "type": "curriculum_updated",
                "curriculum_id": ctx.curriculum_id,
                "scope": "module",
                "module_id": input.module_id,
            },
        }


def strip_stale_section_content(conversation_id: str) -> int:
    """Rewrite every non-latest read/write/update_section call per section to drop its content.

    Mirrors `strip_stale_fetch_url_outputs` in `app/agent/tools/research.py`: called after
    any batch containing a `write_section`/`update_section` call or a successful
    `read_section` call, so re-reading or re-revising the same section later in a long
    conversation doesn't leave duplicate full section Markdown sitting in the model-facing
    history — only the most recent content-bearing occurrence of a given (module_id,
    section_id) keeps its content; earlier occurrences are rewritten to a short note.

    Args:
        conversation_id (str): The conversation whose messages to scan and rewrite.

    Returns:
        int: The number of messages whose `tool_calls` were rewritten (0 on any
            internal failure — this function never raises).
    """
    updated_count = 0
    try:
        messages = fs.list_messages(conversation_id)

        # Pass 1: find, for each (module_id, section_id), the (message_index,
        # tool_call_index) of its LAST content-bearing occurrence across read/write/update
        # calls — chronological message order, then call order within a message — so
        # pass 2 knows which occurrence to leave untouched.
        last_occurrence: dict[tuple[str, str], tuple[int, int]] = {}
        # Cache per-occurrence bookkeeping needed by pass 2: which key it belongs to and
        # whether it's a read (output rewrite) or a write/update (input rewrite).
        occurrence_kind: dict[tuple[int, int], tuple[tuple[str, str], str]] = {}
        for msg_idx, msg in enumerate(messages):
            for tc_idx, tc in enumerate(msg.get("tool_calls") or []):
                name = tc.get("name")
                if name not in _SECTION_CONTENT_TOOLS:
                    continue
                tc_input = tc.get("input")
                if not isinstance(tc_input, dict):
                    continue
                module_id = tc_input.get("module_id")
                section_id = tc_input.get("section_id")
                if not module_id or not section_id:
                    continue
                key = (module_id, section_id)

                if name == "read_section":
                    # A read is content-bearing only if it actually returned the section
                    # doc (error observations like "not found" carry no content_markdown).
                    try:
                        output = json.loads(tc.get("output_full") or "{}")
                    except Exception:
                        continue
                    if not isinstance(output, dict) or "content_markdown" not in output:
                        continue
                else:
                    # write_section/update_section are content-bearing whenever their input
                    # carries a non-stripped content_markdown — INCLUDING error-status calls,
                    # since a rejected write's input still holds full content that must be
                    # strippable once a later call for the same section supersedes it.
                    content = tc_input.get("content_markdown")
                    if not content or content == _SECTION_CONTENT_STRIPPED_NOTE:
                        continue

                occurrence_kind[(msg_idx, tc_idx)] = (key, name)
                last_occurrence[key] = (msg_idx, tc_idx)

        # Pass 2: rewrite every occurrence that isn't the last one for its key.
        for msg_idx, msg in enumerate(messages):
            tool_calls = msg.get("tool_calls") or []
            changed = False
            new_tool_calls = []
            for tc_idx, tc in enumerate(tool_calls):
                kind = occurrence_kind.get((msg_idx, tc_idx))
                if kind is None or last_occurrence.get(kind[0]) == (msg_idx, tc_idx):
                    new_tool_calls.append(tc)
                    continue
                key, name = kind
                module_id, section_id = key
                if name == "read_section":
                    # Reads carry content in the output — rewrite output_full only, leave
                    # input/output_preview untouched (preview is UI-only).
                    stripped_output = {
                        "module_id": module_id,
                        "section_id": section_id,
                        "note": _SECTION_CONTENT_STRIPPED_NOTE,
                    }
                    new_tool_calls.append({**tc, "output_full": json.dumps(stripped_output)})
                else:
                    # Writes/updates carry content in the input — rewrite input only, keep
                    # output_full/output_preview (small status dicts, not worth stripping).
                    new_input = {**tc["input"], "content_markdown": _SECTION_CONTENT_STRIPPED_NOTE}
                    new_tool_calls.append({**tc, "input": new_input})
                changed = True
            if changed:
                fs.update_message(conversation_id, msg["id"], {"tool_calls": new_tool_calls})
                updated_count += 1
    except Exception:
        logger.warning("failed to strip stale section content", exc_info=True)
        return updated_count
    return updated_count


# --------------------------------------------------------------------------------------
# internal helpers
# --------------------------------------------------------------------------------------


def _validate_module_title(title: str) -> str | None:
    """Validate a module display title against the workflow-card bounds.

    Shared by `CreateModuleTool` and `UpdateModuleTool` (mirrors the module title check
    in `tools/planning.py`'s `_validate_plan`, since both persist onto the same field).

    Args:
        title (str): The candidate module title.

    Returns:
        str | None: An error message if blank or over 80 chars, else None.
    """
    if not title.strip() or len(title) > 80:
        return (
            f"title {title!r} is invalid — provide the module's real display title, non-empty "
            f"and at most 80 characters."
        )
    return None


def _validate_module_description(description: str) -> str | None:
    """Validate a module description against the workflow-card/dashboard bounds.

    Shared by `CreateModuleTool` and `UpdateModuleTool` (mirrors the module description
    check in `tools/planning.py`'s `_validate_plan`).

    Args:
        description (str): The candidate module description.

    Returns:
        str | None: An error message if blank or over 300 chars, else None.
    """
    if not description.strip() or len(description) > 300:
        return (
            "description is invalid — it must be non-empty and at most 300 characters, "
            "summarizing the module's content (not a copy of its title)."
        )
    return None


def _validate_write_target(curriculum_id: str, phase: str, module_id: str, section_id: str) -> str | None:
    """Guard write_section's target against invented modules and existing-section overwrites.

    The target module must already exist in EVERY phase now — write_section never
    creates a module (create_module is the sole module-creation path). During
    "writing"/"review" the plan is already approved and materialized, so module_id/
    section_id must both already exist as planned stubs (an existing section is
    overwritten by the caller). During "ready"/"refinement" (the only other phases
    write_section is registered in), write_section may only create a brand-new section
    at the next sequential id within an already-existing module — an already-existing
    section is rejected too (edits go through update_section, not write_section).

    Args:
        curriculum_id (str): The curriculum being written to.
        phase (str): The current agent phase (`ctx.phase`).
        module_id (str): The module id from the write_section call.
        section_id (str): The section id from the write_section call.

    Returns:
        str | None: An error message if the target is invalid for this phase, or None
            if the write may proceed (an existing planned stub in writing/review, or a
            brand-new next-sequential-id section in ready/refinement).
    """
    module = fs.get_module(curriculum_id, module_id)

    if phase in ("writing", "review"):
        # No new modules/sections may be invented once the plan is materialized —
        # every id here must already exist from propose_task_plan + materialization.
        if not module:
            existing_ids = sorted(m["id"] for m in fs.list_modules(curriculum_id))
            return (
                f"module {module_id!r} does not exist. During {phase}, write_section only "
                f"accepts modules already materialized from the approved plan. Existing module "
                f"ids: {existing_ids}. Call list_curriculum_structure to see the full planned "
                f"tree and only write sections that were actually planned."
            )
        section = fs.get_section(curriculum_id, module_id, section_id)
        if not section:
            existing_sections = fs.list_sections(curriculum_id, module_id)
            listing = [
                {"id": s["id"], "title": s.get("title"), "status": s.get("status")}
                for s in existing_sections
            ]
            return (
                f"section {section_id!r} was not in the approved plan for module {module_id!r} "
                f"(existing sections: {listing}). New sections may only be added during "
                f"refinement, not {phase}. The curriculum overview is never a section — use "
                f"write_curriculum_overview instead of write_section for it."
            )
        return None

    # phase in ("ready", "refinement"): a new section may be created, but only inside an
    # already-existing module — write_section never creates modules (use create_module).
    if not module:
        existing_modules = fs.list_modules(curriculum_id)
        existing_ids = sorted(m["id"] for m in existing_modules)
        max_n = 0
        for m in existing_modules:
            match = _NUMBERED_MODULE_ID_RE.match(m["id"])
            if match:
                max_n = max(max_n, int(match.group(1)))
        return (
            f"module {module_id!r} does not exist. Existing module ids: {existing_ids}. "
            f"write_section never creates modules — create the module first with create_module "
            f"(the next sequential id is 'm{max_n + 1}'), then write its sections."
        )

    # An already-existing section may not be overwritten via write_section in ready/
    # refinement — that path is update_section now, so this only ever creates.
    section = fs.get_section(curriculum_id, module_id, section_id)
    if section:
        return (
            f"section {section_id!r} already exists in module {module_id!r}. During {phase}, "
            f"write_section only creates new sections — use update_section to edit existing "
            f"content."
        )

    existing_sections = fs.list_sections(curriculum_id, module_id)
    max_k = 0
    for s in existing_sections:
        match = _NUMBERED_SECTION_ID_RE.match(s["id"])
        if match:
            max_k = max(max_k, int(match.group(1)))
    expected = f"s{max_k + 1}"
    if section_id != expected:
        return (
            f"section {section_id!r} does not exist in module {module_id!r} and is not the "
            f"next sequential section id. To add a new section, use exactly {expected!r} — "
            f"arbitrary slugs are rejected."
        )
    return None


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


def _mark_task_done(curriculum_id: str, module_id: str, section_id: str) -> None:
    """Mark the plan task for (module_id, section_id) as done and pop it from task_queue.

    Matches a task by either of two id forms so both new and legacy curricula work:
    the canonical composite id `f"{module_id}-{section_id}"` (e.g. writing module `m1`
    section `s1` matches task id `m1-s1`), or the legacy form where the section doc id
    IS the full task id (`t["id"] == section_id`, from curricula materialized before the
    `m{X}-s{Y}` convention). No-ops silently if there is no plan yet, or if no task
    matches either form (e.g. a section written outside the normal plan-driven flow).

    Args:
        curriculum_id (str): The curriculum whose plan/state to update.
        module_id (str): The module id the written section belongs to.
        section_id (str): The section id that was just written.
    """
    composite_id = f"{module_id}-{section_id}"
    plan = fs.get_plan(curriculum_id)
    if not plan:
        return
    tasks = plan.get("tasks", [])
    changed = False
    for t in tasks:
        # New convention: task id == "{module_id}-{section_id}". Legacy fallback: task
        # id == section_id verbatim (pre-dates the composite id convention).
        if t.get("id") in (composite_id, section_id) and t.get("status") != "done":
            t["status"] = "done"
            changed = True
    if changed:
        fs.set_plan(curriculum_id, {"tasks": tasks})

    # Advance the working-memory task queue: drop the now-done task (either id form)
    # and point current_task_id at whatever is next (or None if the queue is now empty).
    state = fs.get_agent_state(curriculum_id) or {}
    queue = [t for t in state.get("task_queue", []) if t not in (composite_id, section_id)]
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


def _refresh_curriculum_progress(curriculum_id: str, phase: str, detail: str) -> tuple[int, int]:
    """Recompute task progress and persist it onto the curriculum doc's `progress` field.

    The WS `progress` event reaches only clients connected to the live socket; readers
    that hit the REST layer instead (e.g. the dashboard curriculum cards) need the same
    numbers persisted on the document itself, so this writes them there too.

    Args:
        curriculum_id (str): The curriculum whose plan/progress to recompute and persist.
        phase (str): The current agent phase, stored verbatim as `progress.phase`.
        detail (str): A short human-readable description of the triggering action.

    Returns:
        tuple[int, int]: `(completed, total)` task counts, same as `_task_progress`.
    """
    completed, total = _task_progress(curriculum_id)
    fs.update_curriculum(curriculum_id, {
        "progress": {"phase": phase, "completed_tasks": completed, "total_tasks": total, "detail": detail},
    })
    return completed, total


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
