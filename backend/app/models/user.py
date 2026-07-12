"""User + settings models (mirrors `users/{uid}` Firestore doc)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import EmailStr, Field

from app.models.common import ApiModel

Theme = Literal["system", "light", "dark"]


class UserSettings(ApiModel):
    """Per-user overridable settings. None means "use server default".

    Embedded in the `users/{uid}` Firestore document under the `settings` field. LLM
    model and search provider are no longer per-user settings — they're picked
    per-conversation via the composer chips (see `conversations/{convId}.selected_model`/
    `search_provider` in `app/models/conversation.py`). `ApiModel` ignores unknown
    fields on parse, so stored docs still carrying the old `llm_provider`/
    `search_provider` keys deserialize fine (the keys are just dropped).

    Attributes:
        theme (Theme): UI theme preference ("system", "light", or "dark").
    """

    theme: Theme = "system"


class UserSettingsUpdate(ApiModel):
    """Partial update payload for PUT /api/settings.

    All fields are optional so the client can send only the settings it wants to change.

    Attributes:
        theme (Theme | None): New theme preference, or None to leave unchanged.
    """

    theme: Theme | None = None


class UserRecord(ApiModel):
    """Full internal representation of `users/{uid}`.

    Mirrors the `users/{uid}` Firestore document in its entirety, including fields that
    are never exposed to the client (e.g. `google_sub`).

    Attributes:
        uid (str): Firebase/Google-derived unique user id; also the Firestore doc id.
        email (EmailStr): User's email address, from the verified Google ID token.
        name (str): Display name, from the verified Google ID token.
        picture (str | None): Profile picture URL, if provided by Google.
        google_sub (str): Google's stable subject identifier for the account.
        created_at (dt.datetime): Timestamp the user record was first created.
        last_login_at (dt.datetime): Timestamp of the most recent successful login.
        settings (UserSettings): Per-user overridable settings (currently just theme).
        onboarding_completed (bool): Whether the user has finished the onboarding wizard.
    """

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
    """Public-facing user shape returned by auth endpoints.

    A trimmed view of `UserRecord` that omits internal-only fields such as `google_sub`.

    Attributes:
        uid (str): Firebase/Google-derived unique user id.
        email (EmailStr): User's email address.
        name (str): Display name.
        picture (str | None): Profile picture URL, if any.
        settings (UserSettings): Per-user overridable settings.
        onboarding_completed (bool): Whether onboarding has been completed.
    """

    uid: str
    email: EmailStr
    name: str
    picture: str | None = None
    settings: UserSettings
    onboarding_completed: bool


class GoogleAuthRequest(ApiModel):
    """Request body for the Google sign-in endpoint.

    Attributes:
        id_token (str): The raw Google Identity Services ID token to be verified
            server-side before minting the session JWT.
    """

    id_token: str
