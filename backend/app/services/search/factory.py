"""Factory for constructing/resolving the active SearchProvider.

Search provider selection is per-conversation (composer chips — see docs/specs/01 §7),
not a server-wide env default. `resolve_search_provider` validates a requested name
against what's actually configured, falling back to DuckDuckGo (always available,
keyless) when the request is missing/unknown/unavailable.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.search.base import SearchProvider

# DuckDuckGo is keyless and always available — the universal fallback for both the
# resolver and the "no provider requested" default.
DEFAULT_SEARCH_PROVIDER = "duckduckgo"


def available_search_providers(settings: Settings) -> list[str]:
    """List every search provider name the composer's search chip may offer.

    Args:
        settings (Settings): Application settings supplying provider API credentials.

    Returns:
        list[str]: Always includes "duckduckgo"; plus "google" when both
            `google_cse_api_key` and `google_cse_engine_id` are set; plus "tavily" when
            `tavily_api_key` is set.
    """
    providers = [DEFAULT_SEARCH_PROVIDER]
    if settings.google_cse_api_key and settings.google_cse_engine_id:
        providers.append("google")
    if settings.tavily_api_key:
        providers.append("tavily")
    return providers


def resolve_search_provider(name: str | None, settings: Settings) -> str:
    """Validate a requested search provider name, falling back to the default.

    Args:
        name (str | None): The requested provider name (e.g. from a WS frame or the
            conversation doc's persisted `search_provider`), or None.
        settings (Settings): Application settings supplying provider API credentials,
            used to check the requested provider is actually usable.

    Returns:
        str: `name` if it's one of `available_search_providers(settings)`, otherwise
            `DEFAULT_SEARCH_PROVIDER`.
    """
    if name in available_search_providers(settings):
        return name
    return DEFAULT_SEARCH_PROVIDER


@lru_cache
def _build_provider(name: str) -> SearchProvider:
    """Construct (and cache) the SearchProvider instance for a given provider name.

    Cached via `lru_cache` keyed on `name` since providers are stateless aside from
    their configured client, avoiding repeated client construction across requests.

    Args:
        name (str): The provider identifier: "duckduckgo", "google", or "tavily".

    Returns:
        SearchProvider: The constructed provider instance.

    Raises:
        ValueError: If `name` is not a recognized provider, or if required
            provider-specific API credentials are missing.
    """
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


def get_search_provider(name: str | None = None, settings: Settings | None = None) -> SearchProvider:
    """Return the SearchProvider to use for a given requested name, resolved with fallback.

    Args:
        name (str | None): The requested provider name (e.g. the conversation's
            selected search provider); resolved via `resolve_search_provider`. None
            falls back to `DEFAULT_SEARCH_PROVIDER`.
        settings (Settings | None): The settings instance to resolve against; defaults
            to the process-wide cached settings.

    Returns:
        SearchProvider: The resolved (and cached) provider instance to use for this call.
    """
    settings = settings or get_settings()
    resolved_name = resolve_search_provider(name, settings)
    return _build_provider(resolved_name)
