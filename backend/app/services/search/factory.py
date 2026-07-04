"""Factory for constructing the active SearchProvider.

Resolution order: per-user settings override (if set) then the server-wide
`SEARCH_PROVIDER` env default.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.search.base import SearchProvider


@lru_cache
def _build_provider(name: str) -> SearchProvider:
    settings = get_settings()
    if name == "duckduckgo":
        from app.services.search.duckduckgo import DuckDuckGoSearchProvider

        return DuckDuckGoSearchProvider()
    if name == "google":
        from app.services.search.google_cse import GoogleCSESearchProvider

        return GoogleCSESearchProvider(
            api_key=settings.google_cse_api_key or "",
            engine_id=settings.google_cse_engine_id or "",
        )
    if name == "tavily":
        from app.services.search.tavily import TavilySearchProvider

        return TavilySearchProvider(api_key=settings.tavily_api_key or "")
    raise ValueError(f"Unknown search provider: {name}")


def get_search_provider(user_override: str | None = None, settings: Settings | None = None) -> SearchProvider:
    """Return the SearchProvider to use, honoring a per-user override if provided."""
    settings = settings or get_settings()
    name = user_override or settings.search_provider
    return _build_provider(name)
