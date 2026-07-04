"""Tavily search provider (search API tuned for LLM/agent use cases)."""

from __future__ import annotations

import httpx

from app.core.logging import get_logger
from app.services.search.base import SearchResult

logger = get_logger(__name__)

_ENDPOINT = "https://api.tavily.com/search"


class TavilySearchProvider:
    """Web search via the Tavily REST API."""

    def __init__(self, api_key: str) -> None:
        """Initialize the provider with a Tavily API key.

        Args:
            api_key (str): The Tavily API key.

        Raises:
            ValueError: If `api_key` is falsy.
        """
        if not api_key:
            raise ValueError("TAVILY_API_KEY is required to use the tavily provider")
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        """Run a Tavily search query and normalize the results.

        Args:
            query (str): The search query string.
            max_results (int): The maximum number of results to request from Tavily.

        Returns:
            list[SearchResult]: The search results, or an empty list if the request
                fails (errors are logged as warnings, not raised, so callers can
                degrade gracefully) or Tavily returns no results.
        """
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max_results,
            "include_raw_content": False,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(_ENDPOINT, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("tavily search failed", extra={"extra_fields": {"error": str(exc)}})
            return []

        results = data.get("results", [])
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                # Tavily's `content` field is the closest analogue to a search snippet.
                snippet=item.get("content", ""),
            )
            for item in results
            if item.get("url")
        ]
