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
    id: int
    url: str
    title: str
    accessed_at: dt.datetime


class CurriculumProgress(ApiModel):
    phase: str = "intake"
    completed_tasks: int = 0
    total_tasks: int = 0
    detail: str = ""


class Curriculum(ApiModel):
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
    id: str
    order: int
    title: str
    content_markdown: str = ""
    citations: list[Citation] = Field(default_factory=list)
    status: SectionStatus = "planned"


class Module(ApiModel):
    id: str
    order: int
    title: str
    summary: str = ""
    objectives: list[str] = Field(default_factory=list)
    status: ModuleStatus = "planned"
    estimated_minutes: int = 0
    sections: list[Section] = Field(default_factory=list)


class CurriculumFull(Curriculum):
    modules: list[Module] = Field(default_factory=list)


class PlanTask(ApiModel):
    id: str
    title: str
    description: str = ""
    module_ref: str | None = None
    status: TaskStatus = "pending"


class Plan(ApiModel):
    version: int = 1
    outline_markdown: str = ""
    tasks: list[PlanTask] = Field(default_factory=list)
    status: PlanStatus = "proposed"
    user_feedback: list[str] = Field(default_factory=list)


class ResearchNote(ApiModel):
    id: str
    query: str
    url: str
    title: str
    summary: str
    key_facts: list[str] = Field(default_factory=list)
    relevance: str = ""
    created_at: dt.datetime


class AgentState(ApiModel):
    phase: AgentPhase = "intake"
    task_queue: list[str] = Field(default_factory=list)
    current_task_id: str | None = None
    scratchpad: str = ""
    iteration_count: int = 0
    updated_at: dt.datetime | None = None
