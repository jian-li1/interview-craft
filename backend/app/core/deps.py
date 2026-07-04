"""FastAPI dependencies: current-user auth, CSRF check, and per-user rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.core.security import SESSION_COOKIE_NAME, InvalidSessionTokenError, decode_session_jwt
from app.services import firestore as fs


@dataclass(frozen=True)
class CurrentUser:
    """Resolved identity for the current request."""

    uid: str


def _extract_session_token(request: Request) -> str | None:
    """Read the session JWT from the `ic_session` cookie on an HTTP request.

    Args:
        request (Request): The incoming FastAPI/Starlette request.

    Returns:
        str | None: The raw session token string if the cookie is present, otherwise None.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        return token
    # WS fallback handled separately in app/ws/chat.py; for REST we only use the cookie.
    return None


async def get_current_user(
    request: Request, settings: Settings = Depends(get_settings)
) -> CurrentUser:
    """Resolve the authenticated user from the `ic_session` cookie.

    Intended for use as a FastAPI dependency (`Depends(get_current_user)`) on any route
    that requires authentication.

    Args:
        request (Request): The incoming request, used to read the session cookie.
        settings (Settings): Application settings, providing the JWT signing secret.
            Injected via `Depends(get_settings)`.

    Returns:
        CurrentUser: The resolved identity (uid) for the request.

    Raises:
        HTTPException: 401 if the `ic_session` cookie is missing, or if the token it
            contains is invalid/expired.
    """
    token = _extract_session_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    try:
        uid = decode_session_jwt(token, settings)
    except InvalidSessionTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session") from exc
    return CurrentUser(uid=uid)


async def get_optional_user(
    request: Request, settings: Settings = Depends(get_settings)
) -> CurrentUser | None:
    """Like get_current_user but returns None instead of raising (for public-ish routes).

    Args:
        request (Request): The incoming request, used to read the session cookie.
        settings (Settings): Application settings, providing the JWT signing secret.
            Injected via `Depends(get_settings)`.

    Returns:
        CurrentUser | None: The resolved identity if a valid session cookie is present,
            otherwise None (never raises for missing/invalid auth).
    """
    token = _extract_session_token(request)
    if not token:
        return None
    try:
        uid = decode_session_jwt(token, settings)
    except InvalidSessionTokenError:
        return None
    return CurrentUser(uid=uid)


def require_csrf_header(request: Request) -> None:
    """Enforce the `X-Requested-With: XMLHttpRequest` header on mutating routes.

    Mitigates CSRF alongside SameSite=Lax cookies: a cross-site form/script cannot set
    custom headers on a simple request, so this header's presence proves the request
    originated from our own frontend JS. Registered as a router-level dependency on
    mutating routes; note that it is resolved before `get_current_user`, so a request
    with neither a valid session nor this header gets 403 (not 401) — this ordering is
    intentional (see backend/CLAUDE.md gotchas) and is asserted by
    tests/test_auth_and_csrf.py.

    Args:
        request (Request): The incoming request, whose headers are checked.

    Returns:
        None: Returns nothing on success; raises on failure.

    Raises:
        HTTPException: 403 if the `X-Requested-With` header is missing or has an
            unexpected value.
    """
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="missing X-Requested-With header",
        )


def require_owner(owner_uid: str, user: CurrentUser) -> None:
    """Raise 404 (not 403, to avoid leaking existence) if `user` does not own the resource.

    Using 404 instead of 403 for ownership failures prevents an attacker from
    distinguishing "resource exists but isn't yours" from "resource doesn't exist" —
    both cases look identical to the caller.

    Args:
        owner_uid (str): The uid stored on the resource as its owner.
        user (CurrentUser): The currently authenticated user attempting access.

    Returns:
        None: Returns nothing on success; raises on failure.

    Raises:
        HTTPException: 404 if `owner_uid` does not match `user.uid`.
    """
    if owner_uid != user.uid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


def get_owned_curriculum(curriculum_id: str, user: CurrentUser) -> dict:
    """Fetch a curriculum by id and enforce ownership; raises 404 if missing or not owned.

    Centralizes the "fetch + ownership check" pattern required before any curriculum
    access, since `app/services/firestore.py` performs no ownership checks itself.

    Args:
        curriculum_id (str): The Firestore document id of the curriculum to fetch.
        user (CurrentUser): The currently authenticated user, checked against the
            curriculum's `owner_uid`.

    Returns:
        dict: The raw curriculum document data.

    Raises:
        HTTPException: 404 if no curriculum exists with that id, or if it exists but is
            not owned by `user`.
    """
    curriculum = fs.get_curriculum(curriculum_id)
    if curriculum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    require_owner(curriculum["owner_uid"], user)
    return curriculum


def get_owned_conversation(conversation_id: str, user: CurrentUser) -> dict:
    """Fetch a conversation by id and enforce ownership; raises 404 if missing or not owned.

    Centralizes the "fetch + ownership check" pattern required before any conversation
    access, since `app/services/firestore.py` performs no ownership checks itself.

    Args:
        conversation_id (str): The Firestore document id of the conversation to fetch.
        user (CurrentUser): The currently authenticated user, checked against the
            conversation's `owner_uid`.

    Returns:
        dict: The raw conversation document data.

    Raises:
        HTTPException: 404 if no conversation exists with that id, or if it exists but is
            not owned by `user`.
    """
    conversation = fs.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    require_owner(conversation["owner_uid"], user)
    return conversation


# ------------------------------------------------------------------------------------
# Simple in-memory per-user rate limiting (token bucket) for agent-triggering routes.
# ------------------------------------------------------------------------------------


@dataclass
class _TokenBucket:
    """A single per-user token bucket used to throttle agent-triggering requests.

    Tokens refill continuously over time (up to `capacity`) rather than in fixed
    intervals, giving smooth rate limiting without a background refill task.

    Attributes:
        capacity (int): Maximum number of tokens the bucket can hold.
        refill_per_second (float): Tokens added back per elapsed second.
        tokens (float): Current token count; defaults to 0.0 (callers typically
            initialize it to `capacity` so a fresh bucket starts full).
        last_refill (float): Monotonic timestamp of the last refill computation.
    """

    capacity: int
    refill_per_second: float
    tokens: float = field(default=0.0)
    last_refill: float = field(default_factory=time.monotonic)

    def consume(self, amount: float = 1.0) -> bool:
        """Attempt to consume tokens from the bucket, refilling based on elapsed time first.

        Args:
            amount (float): Number of tokens to consume for this request. Defaults to 1.0.

        Returns:
            bool: True if enough tokens were available and have been deducted, False if
                the request should be rejected (rate limited).
        """
        now = time.monotonic()
        elapsed = now - self.last_refill
        # Lazy refill: compute how many tokens would have accrued since the last check,
        # capped at capacity, instead of running a periodic timer.
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.last_refill = now
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False


class RateLimiter:
    """Per-user in-memory token bucket rate limiter.

    Not distributed (fine for a single-process/dev deployment as called for in spec 01 §8:
    "in-memory token bucket is fine"). Buckets are created lazily per uid.
    """

    def __init__(self, capacity: int = 20, refill_per_second: float = 0.2) -> None:
        """Initialize the rate limiter with shared bucket parameters.

        Args:
            capacity (int): Maximum tokens (burst size) each per-user bucket can hold.
                Defaults to 20.
            refill_per_second (float): Tokens added back per second per user. Defaults
                to 0.2 (i.e. one token every 5 seconds).

        Returns:
            None:
        """
        self._capacity = capacity
        self._refill_per_second = refill_per_second
        # defaultdict lazily creates a full bucket for each new uid on first access, so
        # no explicit registration/cleanup step is needed per user.
        self._buckets: dict[str, _TokenBucket] = defaultdict(
            lambda: _TokenBucket(capacity=capacity, refill_per_second=refill_per_second, tokens=capacity)
        )

    def allow(self, uid: str) -> bool:
        """Check whether the given user may perform another rate-limited action now.

        Args:
            uid (str): The user id whose bucket should be checked/consumed.

        Returns:
            bool: True if a token was available and consumed, False if the user should
                be rate limited.
        """
        return self._buckets[uid].consume()


# Shared instance for agent-triggering endpoints (new conversation, WS chat turns).
agent_rate_limiter = RateLimiter(capacity=20, refill_per_second=0.2)


def enforce_rate_limit(user: CurrentUser) -> None:
    """Raise 429 if the current user has exceeded the shared agent rate limit.

    Intended to be called explicitly (not as a FastAPI dependency) at the top of
    handlers that trigger expensive agent/LLM work, e.g. starting a new conversation or
    synthesizing a profile.

    Args:
        user (CurrentUser): The currently authenticated user to check against the shared
            `agent_rate_limiter`.

    Returns:
        None: Returns nothing on success; raises on failure.

    Raises:
        HTTPException: 429 if the user's token bucket is empty.
    """
    if not agent_rate_limiter.allow(user.uid):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded, please slow down",
        )
