"""DuckDuckGo search provider via the `ddgs` package.

`ddgs` (the current name of the former `duckduckgo_search` package) is synchronous, so we
run it in a thread executor to keep the async interface. DuckDuckGo has no official API
and occasionally rate-limits; we apply a short backoff + one retry before giving up.
"""

from __future__ import annotations

import asyncio

from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException

from app.core.logging import get_logger
from app.services.search.base import SearchResult

logger = get_logger(__name__)

_RETRY_DELAY_SECONDS = 2.0


def _search_sync(query: str, max_results: int) -> list[SearchResult]:
    """Run a blocking DuckDuckGo text search via `ddgs` and normalize the results.

    This is synchronous because the `ddgs` package has no native async API; callers
    must run it via an executor to avoid blocking the event loop.

    Args:
        query (str): The search query string.
        max_results (int): The maximum number of results to request from `ddgs`.

    Returns:
        list[SearchResult]: Normalized results, skipping any raw item that has neither
            an `href` nor `url` field (i.e. nothing usable as a citation source).

    Raises:
        ddgs.exceptions.RatelimitException: If DuckDuckGo rate-limits the request.
        ddgs.exceptions.DDGSException: For other `ddgs` failures.
    """
    with DDGS() as ddgs:
        raw = list(ddgs.text(query, max_results=max_results))
    return [
        SearchResult(
            title=item.get("title", ""),
            url=item.get("href", item.get("url", "")),
            snippet=item.get("body", ""),
        )
        for item in raw
        if item.get("href") or item.get("url")
    ]


class DuckDuckGoSearchProvider:
    """Keyless, free web search backed by DuckDuckGo."""

    async def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        """Run a DuckDuckGo search, retrying once on rate limit and degrading to [] on failure.

        Delegates the actual (blocking) search to `_search_sync` via a thread executor
        to keep this method non-blocking. On a rate limit, waits `_RETRY_DELAY_SECONDS`
        and retries exactly once before giving up.

        Args:
            query (str): The search query string.
            max_results (int): The maximum number of results to return.

        Returns:
            list[SearchResult]: The search results, or an empty list if DuckDuckGo
                rate-limited the retry or otherwise failed (search failures are logged
                as warnings, not raised, so callers can degrade gracefully).
        """
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, _search_sync, query, max_results)
        except RatelimitException:
            logger.warning("duckduckgo rate limited, retrying once", extra={"extra_fields": {"query": query}})
            await asyncio.sleep(_RETRY_DELAY_SECONDS)
            try:
                return await loop.run_in_executor(None, _search_sync, query, max_results)
            except DDGSException as exc:
                logger.warning("duckduckgo search failed after retry", extra={"extra_fields": {"error": str(exc)}})
                return []
        except DDGSException as exc:
            logger.warning("duckduckgo search failed", extra={"extra_fields": {"error": str(exc)}})
            return []
