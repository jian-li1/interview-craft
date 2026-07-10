"""User settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, get_current_user, require_csrf_header
from app.models.user import UserSettings, UserSettingsUpdate
from app.services import firestore as fs

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=UserSettings)
async def get_settings_route(user: CurrentUser = Depends(get_current_user)) -> UserSettings:
    """Return the current user's settings.

    Args:
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.

    Returns:
        UserSettings: The user's settings (e.g. provider overrides), defaulted if the
            user has never customized them.
    """
    data = fs.get_user(user.uid) or {}
    return UserSettings(**(data.get("settings") or {}))


@router.put("", response_model=UserSettings, dependencies=[Depends(require_csrf_header)])
async def put_settings(
    body: UserSettingsUpdate, user: CurrentUser = Depends(get_current_user)
) -> UserSettings:
    """Partially update the current user's settings.

    Requires the `X-Requested-With` CSRF header (enforced by the router-level
    dependency). Only fields explicitly set on `body` are merged into the stored
    settings (`exclude_unset=True`), so omitted fields are left untouched rather than
    reset to their model defaults. Fields explicitly sent as null clear the stored
    override back to the server default.

    Args:
        body (UserSettingsUpdate): Partial settings update; unset fields are ignored.
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.

    Returns:
        UserSettings: The full settings object after merging the update.
    """
    merged = fs.update_user_settings(user.uid, body.model_dump(exclude_unset=True))
    return UserSettings(**merged)
