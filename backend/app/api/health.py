"""Unauthenticated health check route."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/api/healthz")
async def healthz() -> dict:
    """Simple liveness probe; no auth required.

    Used by Cloud Run (and local monitoring) to confirm the process is up and serving
    requests; does not check downstream dependencies like Firestore or the LLM provider.

    Returns:
        dict: `{"status": "ok"}` if the process is alive enough to handle the request.
    """
    return {"status": "ok"}
