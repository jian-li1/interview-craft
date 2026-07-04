"""Session JWT issuing/verification and Google ID token verification.

The backend never trusts the frontend directly: Google ID tokens are verified
server-side, and the backend then mints its own short-lived-ish session JWT that is
set as an httpOnly cookie (`ic_session`). All subsequent requests are authenticated
via that cookie.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.core.config import Settings

SESSION_COOKIE_NAME = "ic_session"
_JWT_ALGORITHM = "HS256"

# Reused across verification calls; google-auth handles its own internal caching of certs.
_google_request = google_requests.Request()


@dataclass(frozen=True)
class GoogleUserInfo:
    """Minimal claims extracted from a verified Google ID token."""

    sub: str
    email: str
    name: str
    picture: str | None


class InvalidGoogleTokenError(Exception):
    """Raised when a Google ID token fails verification."""


class InvalidSessionTokenError(Exception):
    """Raised when the session JWT is missing, malformed, expired, or invalid."""


def verify_google_id_token(id_token_str: str, settings: Settings) -> GoogleUserInfo:
    """Verify a Google Identity Services ID token server-side.

    Checks signature, expiry, audience (== GOOGLE_OAUTH_CLIENT_ID) and issuer. This is the
    only point where the backend trusts a Google-issued token; everything downstream
    (session cookie, Firestore user doc) is derived from the verified claims, never from
    unverified client input.

    Args:
        id_token_str (str): The raw Google ID token (JWT) obtained from Google Identity
            Services on the frontend.
        settings (Settings): Application settings, used for the expected OAuth client id
            (audience).

    Returns:
        GoogleUserInfo: The verified subject id, email, display name, and optional
            picture URL extracted from the token claims.

    Raises:
        InvalidGoogleTokenError: If the token fails google-auth's signature/expiry/audience
            checks, has an unexpected issuer, or is missing the `sub`/`email` claims.
    """
    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_str,
            _google_request,
            settings.google_oauth_client_id,
        )
    except Exception as exc:  # google-auth raises several exception types
        raise InvalidGoogleTokenError(str(exc)) from exc

    # Defense in depth: verify_oauth2_token already validates signature/expiry/audience,
    # but we additionally pin the issuer to Google's two known values to reject tokens
    # from any other (even validly-signed) issuer.
    issuer = claims.get("iss")
    if issuer not in ("accounts.google.com", "https://accounts.google.com"):
        raise InvalidGoogleTokenError(f"unexpected issuer: {issuer}")

    sub = claims.get("sub")
    email = claims.get("email")
    if not sub or not email:
        raise InvalidGoogleTokenError("token missing sub/email claims")

    return GoogleUserInfo(
        sub=sub,
        email=email,
        name=claims.get("name") or email,
        picture=claims.get("picture"),
    )


def create_session_jwt(uid: str, settings: Settings) -> str:
    """Mint a signed session JWT carrying {sub: uid, exp}.

    This is the backend's own credential, issued after a Google ID token has been
    verified; it is what gets stored in the `ic_session` httpOnly cookie and used to
    authenticate all subsequent requests, so the frontend never needs to re-present the
    Google token.

    Args:
        uid (str): The user's stable unique identifier (the Google `sub` claim), used as
            the JWT `sub` claim.
        settings (Settings): Application settings, providing the signing secret and
            expiry duration.

    Returns:
        str: The encoded, signed JWT string.
    """
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": uid,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=settings.session_jwt_expires_min)).timestamp()),
    }
    return jwt.encode(payload, settings.session_jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_session_jwt(token: str, settings: Settings) -> str:
    """Decode and validate a session JWT, returning the uid (`sub` claim).

    Args:
        token (str): The session JWT, typically read from the `ic_session` cookie (or
            the WebSocket `?token=` query-param fallback).
        settings (Settings): Application settings, providing the signing secret used to
            verify the token's signature.

    Returns:
        str: The user id (`sub` claim) encoded in the token.

    Raises:
        InvalidSessionTokenError: If the token is missing, malformed, expired, has an
            invalid signature, or lacks a `sub` claim.
    """
    try:
        payload = jwt.decode(token, settings.session_jwt_secret, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidSessionTokenError(str(exc)) from exc

    uid = payload.get("sub")
    if not uid or not isinstance(uid, str):
        raise InvalidSessionTokenError("session token missing sub claim")
    return uid
