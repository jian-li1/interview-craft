"""Google Programmable Search Engine (Custom Search JSON API) provider."""

from __future__ import annotations

import httpx

from app.core.logging import get_logger
from app.services.search.base import SearchResult

logger = get_logger(__name__)

_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


class GoogleCSESearchProvider:
    """Web search via Google's Custom Search JSON API."""

    def __init__(self, api_key: str, engine_id: str) -> None:
        """Initialize the provider with Google CSE credentials.

        Args:
            api_key (str): The Google API key with Custom Search JSON API enabled.
            engine_id (str): The Programmable Search Engine ("cx") id to query.

        Raises:
            ValueError: If either `api_key` or `engine_id` is falsy.
        """
        if not api_key or not engine_id:
            raise ValueError("GOOGLE_CSE_API_KEY and GOOGLE_CSE_ENGINE_ID are required")
        self._api_key = api_key
        self._engine_id = engine_id

    async def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        """Run a Google Custom Search JSON API query and normalize the results.

        Args:
            query (str): The search query string.
            max_results (int): The desired number of results, clamped to Google CSE's
                per-request maximum of 10.

        Returns:
            list[SearchResult]: The search results, or an empty list if the request
                fails (errors are logged as warnings, not raised, so callers can
                degrade gracefully) or Google returns no items.
        """
        # Google CSE returns at most 10 results per request; cap accordingly.
        num = max(1, min(max_results, 10))
        params = {"key": self._api_key, "cx": self._engine_id, "q": query, "num": num}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(_ENDPOINT, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("google cse search failed", extra={"extra_fields": {"error": str(exc)}})
            return []

        items = data.get("items", [])
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            )
            for item in items
            if item.get("link")
        ]
