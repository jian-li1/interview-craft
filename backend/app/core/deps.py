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
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        return token
    # WS fallback handled separately in app/ws/chat.py; for REST we only use the cookie.
    return None


async def get_current_user(
    request: Request, settings: Settings = Depends(get_settings)
) -> CurrentUser:
    """Resolve the authenticated user from the `ic_session` cookie.

    Raises 401 if the cookie is missing or invalid.
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
    """Like get_current_user but returns None instead of raising (for public-ish routes)."""
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
    originated from our own frontend JS.
    """
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="missing X-Requested-With header",
        )


def require_owner(owner_uid: str, user: CurrentUser) -> None:
    """Raise 404 (not 403, to avoid leaking existence) if `user` does not own the resource."""
    if owner_uid != user.uid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


def get_owned_curriculum(curriculum_id: str, user: CurrentUser) -> dict:
    """Fetch a curriculum by id and enforce ownership; raises 404 if missing or not owned."""
    curriculum = fs.get_curriculum(curriculum_id)
    if curriculum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    require_owner(curriculum["owner_uid"], user)
    return curriculum


def get_owned_conversation(conversation_id: str, user: CurrentUser) -> dict:
    """Fetch a conversation by id and enforce ownership; raises 404 if missing or not owned."""
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
    capacity: int
    refill_per_second: float
    tokens: float = field(default=0.0)
    last_refill: float = field(default_factory=time.monotonic)

    def consume(self, amount: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
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
        self._capacity = capacity
        self._refill_per_second = refill_per_second
        self._buckets: dict[str, _TokenBucket] = defaultdict(
            lambda: _TokenBucket(capacity=capacity, refill_per_second=refill_per_second, tokens=capacity)
        )

    def allow(self, uid: str) -> bool:
        return self._buckets[uid].consume()


# Shared instance for agent-triggering endpoints (new conversation, WS chat turns).
agent_rate_limiter = RateLimiter(capacity=20, refill_per_second=0.2)


def enforce_rate_limit(user: CurrentUser) -> None:
    if not agent_rate_limiter.allow(user.uid):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded, please slow down",
        )
