"""Provider-agnostic web search abstraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class SearchResult:
    """A single web search hit, in a provider-neutral shape.

    Attributes:
        title (str): The result's page title.
        url (str): The result's absolute URL, used as the citation source.
        snippet (str): A short excerpt/summary of the page content shown for the result.
    """

    title: str
    url: str
    snippet: str


@runtime_checkable
class SearchProvider(Protocol):
    """Protocol every web search provider implementation must satisfy."""

    async def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        """Run a web search and return normalized results.

        Args:
            query (str): The search query string.
            max_results (int): The maximum number of results to return; providers may
                cap this lower based on their API's own limits.

        Returns:
            list[SearchResult]: The search results, in provider-neutral form. An empty
                list on failure is an acceptable outcome for implementations that
                degrade gracefully rather than raising.
        """
        ...
