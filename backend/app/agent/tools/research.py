"""Research tools: web_search, fetch_url (with SSRF guard), save/search/list research notes."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from app.agent.tools.base import AgentContext, Tool
from app.core.logging import get_logger
from app.services import firestore as fs

logger = get_logger(__name__)

_FETCH_TIMEOUT_SECONDS = 10.0
_MAX_FETCH_BYTES = 2_000_000
_TRUNCATE_CHARS = 32_000  # ~8k tokens at ~4 chars/token
_ALLOWED_SCHEMES = {"http", "https"}


class WebSearchInput(BaseModel):
    query: str = Field(..., description="The search query string.")
    max_results: int = Field(8, ge=1, le=20, description="Maximum number of results to return.")


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web for a query and return a list of results (title, url, snippet). "
        "Use this to discover candidate sources during research. Issue diverse, specific "
        "queries rather than broad generic ones — see research_phase.md for the query "
        "diversification strategy. Does not fetch full page content; follow up with "
        "fetch_url on the most promising results."
    )
    input_model = WebSearchInput

    async def execute(self, input: WebSearchInput, ctx: AgentContext) -> dict[str, Any]:
        results = await ctx.search.search(input.query, max_results=input.max_results)
        return {
            "results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet} for r in results
            ],
            "count": len(results),
        }


class FetchUrlInput(BaseModel):
    url: str = Field(..., description="The absolute URL to fetch and extract readable text from.")


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparsable -> block defensively
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _guard_url(url: str) -> str:
    """Validate `url` is safe to fetch: http(s) scheme, resolves to a public IP.

    Raises ValueError with a user-safe message if the URL is disallowed. Returns the
    normalized URL on success.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no hostname")

    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"could not resolve host: {host}") from exc

    for info in addr_infos:
        ip_str = info[4][0]
        if _is_blocked_ip(ip_str):
            raise ValueError(f"refusing to fetch private/internal address: {host} -> {ip_str}")

    return url


def _html_to_text(html: str) -> str:
    """Very small, dependency-light HTML→text cleaner: strips scripts/styles/tags."""
    from html.parser import HTMLParser

    class _TextExtractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.chunks: list[str] = []
            self._skip_depth = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in ("script", "style", "noscript", "svg"):
                self._skip_depth += 1
            if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"):
                self.chunks.append("\n")

        def handle_endtag(self, tag: str) -> None:
            if tag in ("script", "style", "noscript", "svg") and self._skip_depth > 0:
                self._skip_depth -= 1

        def handle_data(self, data: str) -> None:
            if self._skip_depth == 0 and data.strip():
                self.chunks.append(data.strip())

    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        logger.warning("html parsing failed; returning raw truncated content")
        return html[:_TRUNCATE_CHARS]
    text = " ".join(parser.chunks)
    # Collapse excessive whitespace.
    return " ".join(text.split())


class FetchUrlTool(Tool):
    name = "fetch_url"
    description = (
        "Fetch a web page by URL and return cleaned, readable text content (scripts/styles "
        "stripped, truncated to roughly 8k tokens). Use this on the most promising web_search "
        "results before writing a research note. Blocks private/internal/loopback network "
        "addresses (SSRF protection) and times out gracefully on slow or unreachable pages — "
        "such failures return an error observation rather than crashing; treat that as a "
        "signal to move on to a different source rather than retrying the same URL."
    )
    input_model = FetchUrlInput

    async def execute(self, input: FetchUrlInput, ctx: AgentContext) -> dict[str, Any]:
        try:
            safe_url = _guard_url(input.url)
        except ValueError as exc:
            return {"error": str(exc)}

        try:
            async with httpx.AsyncClient(
                timeout=_FETCH_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": "InterviewCraftBot/1.0 (+research agent)"},
            ) as client:
                async with client.stream("GET", safe_url) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "text" not in content_type and "html" not in content_type:
                        return {"error": f"unsupported content-type: {content_type}"}

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_FETCH_BYTES:
                            break
                    html = body.decode(response.encoding or "utf-8", errors="replace")
        except httpx.TimeoutException:
            return {"error": f"timed out fetching {input.url}"}
        except httpx.HTTPStatusError as exc:
            return {"error": f"http error {exc.response.status_code} fetching {input.url}"}
        except httpx.HTTPError as exc:
            return {"error": f"failed to fetch {input.url}: {exc}"}

        text = _html_to_text(html)
        truncated = text[:_TRUNCATE_CHARS]
        return {
            "url": input.url,
            "text": truncated,
            "truncated": len(text) > _TRUNCATE_CHARS,
            "length_chars": len(truncated),
        }


class SaveResearchNoteInput(BaseModel):
    query: str = Field(..., description="The search query that surfaced this source.")
    url: str = Field(..., description="The source URL.")
    title: str = Field(..., description="The source's title.")
    summary: str = Field(
        ...,
        description=(
            "A dense distillation of the useful content, in your own words (2-5 sentences). "
            "Must NOT be a raw copy/paste of page text."
        ),
    )
    key_facts: list[str] = Field(
        default_factory=list, description="Short list of concrete, checkable facts/points from the source."
    )
    relevance: str = Field(
        "", description="Which outline/coverage area(s) this note supports."
    )


class SaveResearchNoteTool(Tool):
    name = "save_research_note"
    description = (
        "Save a distilled research note derived from a source you found via web_search/"
        "fetch_url. Summaries must be dense distillations in your own words, not raw copies. "
        "Every note's url is preserved for later citation. Aim for 12-25 quality notes total "
        "covering the 6 research coverage areas before moving on from deep_research."
    )
    input_model = SaveResearchNoteInput

    async def execute(self, input: SaveResearchNoteInput, ctx: AgentContext) -> dict[str, Any]:
        note_id = fs.create_research_note(
            ctx.curriculum_id,
            {
                "query": input.query,
                "url": input.url,
                "title": input.title,
                "summary": input.summary,
                "key_facts": input.key_facts,
                "relevance": input.relevance,
            },
        )
        return {"note_id": note_id}


class SearchResearchNotesInput(BaseModel):
    keywords: str = Field(..., description="Keywords to match against saved research notes.")


def _score_note(note: dict[str, Any], keywords: list[str]) -> int:
    haystack = " ".join(
        [
            note.get("summary", ""),
            " ".join(note.get("key_facts", [])),
            note.get("relevance", ""),
            note.get("title", ""),
        ]
    ).lower()
    return sum(haystack.count(kw.lower()) for kw in keywords if kw)


class SearchResearchNotesTool(Tool):
    name = "search_research_notes"
    description = (
        "Search previously saved research notes for this curriculum by keyword, ranked by "
        "relevance. Use this before writing any section to ground content in prior research, "
        "and before starting a new web search to check whether you already have relevant notes."
    )
    input_model = SearchResearchNotesInput

    async def execute(self, input: SearchResearchNotesInput, ctx: AgentContext) -> dict[str, Any]:
        notes = fs.list_research_notes(ctx.curriculum_id)
        keywords = [k for k in input.keywords.replace(",", " ").split() if k]
        scored = [(_score_note(n, keywords), n) for n in notes]
        scored = [pair for pair in scored if pair[0] > 0]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[:15]
        return {
            "matches": [
                {
                    "id": n["id"],
                    "title": n.get("title"),
                    "url": n.get("url"),
                    "summary": n.get("summary"),
                    "key_facts": n.get("key_facts", []),
                    "relevance": n.get("relevance"),
                }
                for _, n in top
            ],
            "count": len(top),
        }


class ListResearchNotesInput(BaseModel):
    pass


class ListResearchNotesTool(Tool):
    name = "list_research_notes"
    description = (
        "List all saved research notes for this curriculum in compact form (id, title, url, "
        "relevance) for orientation — use this to check overall research coverage before "
        "deciding whether to keep researching or move to outline_planning."
    )
    input_model = ListResearchNotesInput

    async def execute(self, input: ListResearchNotesInput, ctx: AgentContext) -> dict[str, Any]:
        notes = fs.list_research_notes(ctx.curriculum_id)
        return {
            "notes": [
                {"id": n["id"], "title": n.get("title"), "url": n.get("url"), "relevance": n.get("relevance")}
                for n in notes
            ],
            "count": len(notes),
        }
