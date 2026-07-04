"""Unauthenticated health check route."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/api/healthz")
async def healthz() -> dict:
    """Simple liveness probe; no auth required."""
    return {"status": "ok"}
