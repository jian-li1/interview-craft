"""Onboarding profile models (mirrors `users/{uid}/profile/main`)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from app.models.common import ApiModel

ExperienceLevel = Literal["student", "entry", "mid", "senior", "career_change"]


class ProfileIn(ApiModel):
    """Payload for PUT /api/onboarding — user-editable onboarding fields."""

    bio: str = ""
    background: str = ""
    target_roles: list[str] = Field(default_factory=list)
    experience_level: ExperienceLevel = "entry"
    skills: list[str] = Field(default_factory=list)
    goals: str = ""
    learning_style: str = ""
    timeline: str = ""
    onboarding_completed: bool = False


class ProfileOut(ProfileIn):
    """Full profile returned to the client, including derived/AI fields."""

    resume_filename: str | None = None
    resume_text: str | None = None
    synthesized_profile: str | None = None
    updated_at: dt.datetime | None = None


class ResumeUploadOut(ApiModel):
    resume_filename: str
    resume_text: str


class SynthesizeProfileOut(ApiModel):
    synthesized_profile: str
