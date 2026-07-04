"""Onboarding profile models (mirrors `users/{uid}/profile/main`)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from app.models.common import ApiModel

ExperienceLevel = Literal["student", "entry", "mid", "senior", "career_change"]


class ProfileIn(ApiModel):
    """Payload for PUT /api/onboarding — user-editable onboarding fields.

    Mirrors the user-editable subset of `users/{uid}/profile/main`.

    Attributes:
        bio (str): Free-text short bio supplied by the user.
        background (str): Free-text description of the user's professional background.
        target_roles (list[str]): Job roles/titles the user is preparing to interview for.
        experience_level (ExperienceLevel): Coarse career stage bucket.
        skills (list[str]): Self-reported skills/technologies.
        goals (str): Free-text description of the user's interview-prep goals.
        learning_style (str): Free-text description of how the user prefers to learn.
        timeline (str): Free-text description of the user's prep timeline/urgency.
        onboarding_completed (bool): Whether the user has finished the onboarding wizard.
    """

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
    """Full profile returned to the client, including derived/AI fields.

    Extends `ProfileIn` with fields derived server-side (resume text, synthesized
    profile) that are stored in `users/{uid}/profile/main` but not directly editable.

    Attributes:
        resume_filename (str | None): Original filename of the uploaded resume, if any.
        resume_text (str | None): Extracted plain text from the uploaded resume.
        synthesized_profile (str | None): AI-generated synthesis of the user's profile,
            used as a memory layer input for the agent.
        updated_at (dt.datetime | None): Timestamp of the last profile update.
    """

    resume_filename: str | None = None
    resume_text: str | None = None
    synthesized_profile: str | None = None
    updated_at: dt.datetime | None = None


class ResumeUploadOut(ApiModel):
    """Response body after a resume file has been uploaded and parsed.

    Attributes:
        resume_filename (str): Original filename of the uploaded resume.
        resume_text (str): Extracted plain text content of the resume.
    """

    resume_filename: str
    resume_text: str


class SynthesizeProfileOut(ApiModel):
    """Response body for the AI profile-synthesis endpoint.

    Attributes:
        synthesized_profile (str): AI-generated synthesis of the user's onboarding
            answers and resume, persisted to `users/{uid}/profile/main`.
    """

    synthesized_profile: str
