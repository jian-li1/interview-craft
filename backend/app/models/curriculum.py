"""Curriculum, module, section, plan and research-note models.

Mirrors the Firestore collections described in docs/specs/01-architecture-and-contracts.md §5:
  curricula/{id}
  curricula/{id}/modules/{moduleId}
  curricula/{id}/modules/{mid}/sections/{sectionId}
  curricula/{id}/plan/main
  curricula/{id}/research/{noteId}
  curricula/{id}/state/main
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from app.models.common import ApiModel

CurriculumStatus = Literal[
    "researching", "planning", "awaiting_approval", "writing", "ready", "error"
]
ModuleStatus = Literal["planned", "writing", "complete"]
SectionStatus = Literal["planned", "writing", "complete"]
PlanStatus = Literal["proposed", "approved", "revising"]
TaskStatus = Literal["pending", "in_progress", "done"]
AgentPhase = Literal[
    "intake",
    "deep_research",
    "outline_planning",
    "awaiting_approval",
    "writing",
    "review",
    "ready",
    "refinement",
]


class Citation(ApiModel):
    """A single footnoted source, embedded in a `Section`'s `citations` list.

    Citations are non-negotiable per project policy: every cited fact must trace back
    to a real URL fetched during research — no fabricated sources.

    Attributes:
        id (int): Footnote number (`[^n]`) referenced from the section's markdown body.
        url (str): Source URL that was fetched during research.
        title (str): Title of the source page/document.
        accessed_at (dt.datetime): Timestamp the source was fetched.
    """

    id: int
    url: str
    title: str
    accessed_at: dt.datetime


class CurriculumProgress(ApiModel):
    """Coarse progress indicator surfaced to the client while a curriculum is built.

    Embedded in the `curricula/{id}` document under the `progress` field.

    Attributes:
        phase (str): Human-readable label for the agent's current phase.
        completed_tasks (int): Number of plan tasks completed so far.
        total_tasks (int): Total number of plan tasks.
        detail (str): Free-text status detail (e.g. current research query).
    """

    phase: str = "intake"
    completed_tasks: int = 0
    total_tasks: int = 0
    detail: str = ""


class Curriculum(ApiModel):
    """Full internal representation of a `curricula/{id}` Firestore document.

    Does not include the `modules` subcollection — see `CurriculumFull` for the
    fully-hydrated shape used when the client needs the entire tree.

    Attributes:
        id (str): Curriculum id (Firestore doc id).
        owner_uid (str): uid of the user who owns this curriculum.
        title (str): Display title for the curriculum.
        user_prompt (str): Original user prompt that requested this curriculum.
        emoji (str | None): Optional emoji used as a visual icon on the dashboard.
        status (CurriculumStatus): Current lifecycle stage of the curriculum.
        overview (str): Short AI-generated overview/summary of the curriculum content.
        progress (CurriculumProgress): Coarse progress indicator for in-progress runs.
        conversation_id (str): Id of the conversation that is building/owns this
            curriculum.
        module_count (int): Denormalized count of modules, for list views.
        section_count (int): Denormalized count of sections, for list views.
        tags (list[str]): Free-form tags for categorization/search.
        created_at (dt.datetime): Timestamp the curriculum was created.
        updated_at (dt.datetime): Timestamp of the most recent update.
    """

    id: str
    owner_uid: str
    title: str
    user_prompt: str
    emoji: str | None = None
    status: CurriculumStatus = "researching"
    overview: str = ""
    progress: CurriculumProgress = Field(default_factory=CurriculumProgress)
    conversation_id: str
    module_count: int = 0
    section_count: int = 0
    tags: list[str] = Field(default_factory=list)
    created_at: dt.datetime
    updated_at: dt.datetime


class CurriculumSummary(ApiModel):
    """Lightweight curriculum shape used for dashboard/list views.

    Mirrors the same fields as `Curriculum` (minus module/section subcollections) but
    with progress and status required rather than defaulted, since list views always
    read an existing document.

    Attributes:
        id (str): Curriculum id.
        owner_uid (str): uid of the user who owns this curriculum.
        title (str): Display title for the curriculum.
        user_prompt (str): Original user prompt that requested this curriculum.
        emoji (str | None): Optional emoji used as a visual icon.
        status (CurriculumStatus): Current lifecycle stage of the curriculum.
        overview (str): Short AI-generated overview/summary.
        progress (CurriculumProgress): Coarse progress indicator.
        conversation_id (str): Id of the owning conversation.
        tags (list[str]): Free-form tags for categorization/search.
        module_count (int): Denormalized count of modules.
        section_count (int): Denormalized count of sections.
        created_at (dt.datetime): Timestamp the curriculum was created.
        updated_at (dt.datetime): Timestamp of the most recent update.
    """

    id: str
    owner_uid: str
    title: str
    user_prompt: str
    emoji: str | None = None
    status: CurriculumStatus
    overview: str = ""
    progress: CurriculumProgress
    conversation_id: str
    tags: list[str] = Field(default_factory=list)
    module_count: int = 0
    section_count: int = 0
    created_at: dt.datetime
    updated_at: dt.datetime


class Section(ApiModel):
    """A single interview-prep section, mirroring `curricula/{id}/modules/{mid}/sections/{sectionId}`.

    Attributes:
        id (str): Section id.
        order (int): Display order of this section within its parent module.
        title (str): Section title.
        content_markdown (str): Fully-cited markdown body content for the section.
        citations (list[Citation]): Footnoted sources referenced from `content_markdown`.
        status (SectionStatus): Whether the section is planned, being written, or done.
    """

    id: str
    order: int
    title: str
    content_markdown: str = ""
    citations: list[Citation] = Field(default_factory=list)
    status: SectionStatus = "planned"


class Module(ApiModel):
    """A curriculum module, mirroring `curricula/{id}/modules/{moduleId}`.

    Attributes:
        id (str): Module id.
        order (int): Display order of this module within the curriculum.
        title (str): Module title.
        summary (str): Short description of the module's content.
        objectives (list[str]): Learning objectives for the module.
        status (ModuleStatus): Whether the module is planned, being written, or done.
        estimated_minutes (int): Estimated time to complete the module, in minutes.
        sections (list[Section]): Sections that make up this module, in `order`.
    """

    id: str
    order: int
    title: str
    summary: str = ""
    objectives: list[str] = Field(default_factory=list)
    status: ModuleStatus = "planned"
    estimated_minutes: int = 0
    sections: list[Section] = Field(default_factory=list)


class CurriculumFull(Curriculum):
    """`Curriculum` hydrated with its full `modules` subcollection tree.

    Used when the client needs the entire curriculum content in one response (e.g. the
    studio reader view), rather than the summary shape used for list views.

    Attributes:
        modules (list[Module]): All modules belonging to this curriculum, in order.
    """

    modules: list[Module] = Field(default_factory=list)


class PlanTask(ApiModel):
    """A single task within a curriculum build `Plan`.

    Attributes:
        id (str): Task id.
        title (str): Short task title.
        description (str): Longer free-text description of the task.
        module_ref (str | None): Id of the module this task produces/relates to, if any.
        status (TaskStatus): Whether the task is pending, in progress, or done.
    """

    id: str
    title: str
    description: str = ""
    module_ref: str | None = None
    status: TaskStatus = "pending"


class Plan(ApiModel):
    """The agent's proposed build plan, mirroring `curricula/{id}/plan/main`.

    Presented to the user for approval via the `propose_task_plan` HITL tool before the
    agent proceeds to the writing phase.

    Attributes:
        version (int): Plan revision number, incremented each time the plan is revised.
        outline_markdown (str): Human-readable markdown outline of the proposed plan.
        tasks (list[PlanTask]): Structured list of tasks that make up the plan.
        status (PlanStatus): Whether the plan is proposed, approved, or being revised.
        user_feedback (list[str]): History of user feedback messages given while
            revising the plan.
    """

    version: int = 1
    outline_markdown: str = ""
    tasks: list[PlanTask] = Field(default_factory=list)
    status: PlanStatus = "proposed"
    user_feedback: list[str] = Field(default_factory=list)


class ResearchNote(ApiModel):
    """A single research finding, mirroring `curricula/{id}/research/{noteId}`.

    Research notes are pulled on demand via tools during writing (never injected
    wholesale into the LLM context) and back citations in the final sections.

    Attributes:
        id (str): Research note id.
        query (str): Search query that produced this note.
        url (str): Source URL the note was extracted from.
        title (str): Title of the source page/document.
        summary (str): Summary of the relevant content found at the source.
        key_facts (list[str]): Discrete facts extracted from the source.
        relevance (str): Free-text note on why/how this source is relevant.
        created_at (dt.datetime): Timestamp the note was created.
    """

    id: str
    query: str
    url: str
    title: str
    summary: str
    key_facts: list[str] = Field(default_factory=list)
    relevance: str = ""
    created_at: dt.datetime


class AgentState(ApiModel):
    """The ReAct orchestrator's persisted state, mirroring `curricula/{id}/state/main`.

    Persisted so a HITL pause (via `propose_task_plan`/`request_user_input`) or a
    process restart can resume the run from where it left off.

    Attributes:
        phase (AgentPhase): Current phase of the agent's workflow state machine.
        task_queue (list[str]): Ids of plan tasks still to be processed.
        current_task_id (str | None): Id of the task currently being worked on, if any.
        scratchpad (str): Free-text working memory the agent uses between iterations.
        iteration_count (int): Number of ReAct loop iterations executed so far.
        updated_at (dt.datetime | None): Timestamp of the most recent state update.
    """

    phase: AgentPhase = "intake"
    task_queue: list[str] = Field(default_factory=list)
    current_task_id: str | None = None
    scratchpad: str = ""
    iteration_count: int = 0
    updated_at: dt.datetime | None = None
