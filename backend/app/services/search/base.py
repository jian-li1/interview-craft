"""Provider-agnostic web search abstraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str


@runtime_checkable
class SearchProvider(Protocol):
    async def search(self, query: str, max_results: int = 8) -> list[SearchResult]: ...
