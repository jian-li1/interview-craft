"""Auth routes: Google ID token exchange, logout, current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core.config import Settings, get_settings
from app.core.deps import CurrentUser, get_current_user, require_csrf_header
from app.core.security import (
    SESSION_COOKIE_NAME,
    InvalidGoogleTokenError,
    create_session_jwt,
    verify_google_id_token,
)
from app.models.user import GoogleAuthRequest, UserOut, UserSettings
from app.services import firestore as fs

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """Attach the signed session JWT to the response as an httpOnly cookie.

    Cookie flags are deliberate security choices: `httponly=True` blocks JS access
    (mitigates XSS token theft), `samesite="lax"` blocks the cookie being sent on
    cross-site POSTs (mitigates CSRF, paired with `require_csrf_header`), and
    `secure` is tied to the environment so local HTTP development still works while
    production requires HTTPS.

    Args:
        response (Response): The outgoing FastAPI response to attach the cookie to.
        token (str): The signed session JWT to store.
        settings (Settings): Application settings, providing the expiry duration and
            production flag (for the `secure` attribute).

    Returns:
        None:
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.session_jwt_expires_min * 60,
        path="/",
    )


def _to_user_out(uid: str, data: dict) -> UserOut:
    """Convert a raw Firestore user document into the API's `UserOut` response model.

    Args:
        uid (str): The user's unique id (Firestore document id / Google `sub`).
        data (dict): The raw user document fields as stored in Firestore.

    Returns:
        UserOut: The public-facing user representation, with nested settings defaulted
            when absent.
    """
    settings_data = data.get("settings", {}) or {}
    return UserOut(
        uid=uid,
        email=data["email"],
        name=data["name"],
        picture=data.get("picture"),
        settings=UserSettings(**settings_data),
        onboarding_completed=data.get("onboarding_completed", False),
    )


@router.post("/google", response_model=UserOut, dependencies=[Depends(require_csrf_header)])
async def google_login(
    body: GoogleAuthRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> UserOut:
    """Verify a Google ID token and mint a session cookie for the corresponding user.

    On success, upserts the user's login record in Firestore (creating the user doc on
    first login) and sets the `ic_session` cookie via `_set_session_cookie`. Requires the
    `X-Requested-With` CSRF header (enforced by the router-level dependency).

    Args:
        body (GoogleAuthRequest): Request body containing the raw Google ID token.
        response (Response): The outgoing response, used to set the session cookie.
        settings (Settings): Application settings, injected via `Depends(get_settings)`.

    Returns:
        UserOut: The authenticated user's public profile.

    Raises:
        HTTPException: 401 if the Google ID token fails verification.
    """
    try:
        google_user = verify_google_id_token(body.id_token, settings)
    except InvalidGoogleTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid Google ID token") from exc

    user_data = fs.upsert_user_login(
        uid=google_user.sub,
        email=google_user.email,
        name=google_user.name,
        picture=google_user.picture,
        google_sub=google_user.sub,
    )
    token = create_session_jwt(google_user.sub, settings)
    _set_session_cookie(response, token, settings)
    return _to_user_out(google_user.sub, user_data)


@router.post("/logout", dependencies=[Depends(require_csrf_header)])
async def logout(response: Response, settings: Settings = Depends(get_settings)) -> dict:
    """Clear the session cookie.

    Requires the `X-Requested-With` CSRF header (enforced by the router-level
    dependency). The cookie attributes passed to `delete_cookie` must match those used
    when setting it for the browser to actually remove it.

    Args:
        response (Response): The outgoing response, used to clear the session cookie.
        settings (Settings): Application settings, injected via `Depends(get_settings)`.

    Returns:
        dict: `{"ok": True}` on success.
    """
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", samesite="lax", secure=settings.is_production)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser = Depends(get_current_user)) -> UserOut:
    """Return the currently authenticated user.

    Args:
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)` from the session cookie.

    Returns:
        UserOut: The current user's public profile.

    Raises:
        HTTPException: 401 if no user record is found for the authenticated uid (e.g.
            deleted account with a still-valid session token).
    """
    data = fs.get_user(user.uid)
    if data is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return _to_user_out(user.uid, data)
