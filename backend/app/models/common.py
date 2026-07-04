"""Shared small types used across model modules."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base class for all API-facing pydantic models.

    Uses a shared config so we can tighten validation defaults in one place.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)
