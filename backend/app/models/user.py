"""User + settings models (mirrors `users/{uid}` Firestore doc)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import EmailStr, Field

from app.models.common import ApiModel

Theme = Literal["system", "light", "dark"]


class UserSettings(ApiModel):
    """Per-user overridable settings. None means "use server default"."""

    theme: Theme = "system"
    llm_provider: str | None = None
    search_provider: str | None = None


class UserSettingsUpdate(ApiModel):
    """Partial update payload for PUT /api/settings."""

    theme: Theme | None = None
    llm_provider: str | None = None
    search_provider: str | None = None


class UserRecord(ApiModel):
    """Full internal representation of `users/{uid}`."""

    uid: str
    email: EmailStr
    name: str
    picture: str | None = None
    google_sub: str
    created_at: dt.datetime
    last_login_at: dt.datetime
    settings: UserSettings = Field(default_factory=UserSettings)
    onboarding_completed: bool = False


class UserOut(ApiModel):
    """Public-facing user shape returned by auth endpoints."""

    uid: str
    email: EmailStr
    name: str
    picture: str | None = None
    settings: UserSettings
    onboarding_completed: bool


class GoogleAuthRequest(ApiModel):
    id_token: str
