"""User settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, get_current_user, require_csrf_header
from app.models.user import UserSettings, UserSettingsUpdate
from app.services import firestore as fs

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=UserSettings)
async def get_settings_route(user: CurrentUser = Depends(get_current_user)) -> UserSettings:
    """Return the current user's settings."""
    data = fs.get_user(user.uid) or {}
    return UserSettings(**(data.get("settings") or {}))


@router.put("", response_model=UserSettings, dependencies=[Depends(require_csrf_header)])
async def put_settings(
    body: UserSettingsUpdate, user: CurrentUser = Depends(get_current_user)
) -> UserSettings:
    """Partially update the current user's settings."""
    merged = fs.update_user_settings(user.uid, body.model_dump(exclude_unset=True))
    return UserSettings(**merged)
