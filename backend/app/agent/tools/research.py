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
_ALLOWED_SCHEMES = {"http", "https"}


class WebSearchInput(BaseModel):
    """Input schema for `WebSearchTool`."""

    query: str = Field(..., description="The search query string.")
    max_results: int = Field(8, ge=1, le=20, description="Maximum number of results to return.")


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web for a query and return a list of results (title, url, snippet). "
        "Use this to discover candidate sources during research. Issue diverse, specific "
        "queries rather than broad generic ones — see research_phase.md for the query "
        "diversification strategy. Snippets returned here are for RELEVANCE TRIAGE ONLY — "
        "deciding which results to fetch or skip. Always call fetch_url on a result before "
        "saving a research note about it; never save a note from a snippet alone."
    )
    input_model = WebSearchInput

    async def execute(self, input: WebSearchInput, ctx: AgentContext) -> dict[str, Any]:
        """Run a web search via the configured `ctx.search` provider and return raw results.

        Args:
            input (WebSearchInput): The validated query and max_results.
            ctx (AgentContext): The current agent run's context; `ctx.search` is the
                provider resolved from settings/user overrides (DuckDuckGo/Google/Tavily).

        Returns:
            dict[str, Any]: `{"results": [...], "count": int}`, where each result has
                `title`, `url`, and `snippet` fields for relevance triage only.
        """
        results = await ctx.search.search(input.query, max_results=input.max_results)
        return {
            "results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet} for r in results
            ],
            "count": len(results),
        }


class FetchUrlInput(BaseModel):
    """Input schema for `FetchUrlTool`."""

    url: str = Field(..., description="The absolute URL to fetch and extract readable text from.")


def _is_blocked_ip(ip_str: str) -> bool:
    """Check whether `ip_str` is a private/internal address that must not be fetched (SSRF guard).

    Args:
        ip_str (str): A textual IP address (IPv4 or IPv6) to classify.

    Returns:
        bool: True if the address is private, loopback, link-local, multicast,
            reserved, unspecified, or fails to parse as an IP at all (unparsable
            addresses are blocked defensively rather than allowed through).
    """
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

    Args:
        url (str): The candidate URL to validate.

    Returns:
        str: The same `url`, unmodified, once validated as safe to fetch.

    Raises:
        ValueError: If the scheme isn't http/https, the URL has no hostname, the
            hostname can't be resolved, or any resolved address is private/internal
            (per `_is_blocked_ip`).
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

    # Check every resolved address (a hostname can resolve to multiple A/AAAA records),
    # not just the first — an attacker-controlled DNS response could otherwise slip a
    # private address past a check that only looked at the first result.
    for info in addr_infos:
        ip_str = info[4][0]
        if _is_blocked_ip(ip_str):
            raise ValueError(f"refusing to fetch private/internal address: {host} -> {ip_str}")

    return url


def _html_to_text(html: str) -> str:
    """Very small, dependency-light HTML→text cleaner: strips scripts/styles/tags.

    Args:
        html (str): The raw HTML document to convert to plain text.

    Returns:
        str: Whitespace-collapsed plain text extracted from the document, with
            script/style/noscript/svg contents excluded and block-level tags turned into
            newline breaks. Falls back to the raw HTML if parsing itself raises
            (malformed markup).
    """
    from html.parser import HTMLParser

    class _TextExtractor(HTMLParser):
        """Minimal HTMLParser subclass collecting visible text chunks, skipping non-content tags."""

        def __init__(self) -> None:
            """Initialize with an empty chunk list and non-content-tag skip counter."""
            super().__init__()
            self.chunks: list[str] = []
            self._skip_depth = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            """Enter a skip region for non-content tags; insert a newline for block tags.

            Args:
                tag (str): The lowercased tag name being opened.
                attrs (list[tuple[str, str | None]]): The tag's attributes (unused).
            """
            if tag in ("script", "style", "noscript", "svg"):
                self._skip_depth += 1
            if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"):
                self.chunks.append("\n")

        def handle_endtag(self, tag: str) -> None:
            """Exit a skip region when a non-content tag closes.

            Args:
                tag (str): The lowercased tag name being closed.
            """
            if tag in ("script", "style", "noscript", "svg") and self._skip_depth > 0:
                self._skip_depth -= 1

        def handle_data(self, data: str) -> None:
            """Collect non-whitespace text data, unless inside a skip region.

            Args:
                data (str): The raw text content between tags.
            """
            if self._skip_depth == 0 and data.strip():
                self.chunks.append(data.strip())

    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        logger.warning("html parsing failed; returning raw content")
        return html
    text = " ".join(parser.chunks)
    # Collapse excessive whitespace.
    return " ".join(text.split())


class FetchUrlTool(Tool):
    name = "fetch_url"
    description = (
        "Fetch a web page by URL and return cleaned, readable text content (scripts/styles "
        "stripped; the full page text is returned untruncated). This is a REQUIRED step before "
        "save_research_note for any source you intend to keep — search snippets alone are "
        "never enough to write a note from. Blocks private/internal/loopback network "
        "addresses (SSRF protection) and times out gracefully on slow or unreachable pages — "
        "such failures return an error observation rather than crashing; when a fetch fails, "
        "skip that source entirely (do not write a note from the snippet as a fallback) and "
        "move on to a different candidate rather than retrying the same URL."
    )
    input_model = FetchUrlInput

    async def execute(self, input: FetchUrlInput, ctx: AgentContext) -> dict[str, Any]:
        """Fetch `input.url`, guard against SSRF, and return cleaned readable text.

        Args:
            input (FetchUrlInput): The validated URL to fetch.
            ctx (AgentContext): The current agent run's context (unused directly here;
                required by the `Tool.execute` signature).

        Returns:
            dict[str, Any]: On success, `{"url", "text", "truncated", "length_chars"}`
                with the full cleaned page text (`truncated` is always False, kept for
                schema stability). On failure (disallowed URL, unsupported content-type,
                timeout, or HTTP error), `{"error": "..."}`.
        """
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

                    # Read the entire body — no byte cap, so the full page is returned.
                    body = await response.aread()
                    html = body.decode(response.encoding or "utf-8", errors="replace")
        except httpx.TimeoutException:
            return {"error": f"timed out fetching {input.url}"}
        except httpx.HTTPStatusError as exc:
            return {"error": f"http error {exc.response.status_code} fetching {input.url}"}
        except httpx.HTTPError as exc:
            return {"error": f"failed to fetch {input.url}: {exc}"}

        text = _html_to_text(html)
        # Return the full cleaned text untruncated; `truncated` stays for schema stability.
        return {
            "url": input.url,
            "text": text,
            "truncated": False,
            "length_chars": len(text),
        }


class SaveResearchNoteInput(BaseModel):
    """Input schema for `SaveResearchNoteTool`."""

    query: str = Field(..., description="The search query that surfaced this source.")
    url: str = Field(..., description="The source URL.")
    title: str = Field(..., description="The source's title.")
    summary: str = Field(
        ...,
        description=(
            "A comprehensive, multi-paragraph distillation of the FETCHED FULL CONTENT "
            "(via fetch_url), in your own words — not a 2-5 sentence teaser, and not a raw "
            "copy-paste of page text. Cover all key ideas, concepts, frameworks, process "
            "details, example questions, and advice the source contains, scaled to the "
            "richness of the source (roughly 150-500+ words for a substantial source). The "
            "writing phase must be able to write curriculum content from this summary alone, "
            "without re-fetching the source."
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
        "Save a comprehensive research note distilled from a source's FETCHED FULL CONTENT — "
        "the source must have been retrieved with fetch_url first; do not call this based on "
        "a web_search snippet alone. Summaries must be thorough, multi-paragraph distillations "
        "in your own words, not raw copies. Every note's url is preserved for later citation."
    )
    input_model = SaveResearchNoteInput

    async def execute(self, input: SaveResearchNoteInput, ctx: AgentContext) -> dict[str, Any]:
        """Persist a new research note document for this curriculum.

        Args:
            input (SaveResearchNoteInput): The validated note fields (query, url, title,
                summary, key_facts, relevance).
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes the note to the right curriculum's Firestore subcollection.

        Returns:
            dict[str, Any]: `{"note_id": str}`, the id of the newly created note doc.
        """
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
    """Input schema for `SearchResearchNotesTool`."""

    keywords: str = Field(..., description="Keywords to match against saved research notes.")


def _score_note(note: dict[str, Any], keywords: list[str]) -> int:
    """Score a research note's relevance to `keywords` by simple case-insensitive substring counting.

    Args:
        note (dict[str, Any]): A research note document (summary, key_facts, relevance,
            title fields are searched).
        keywords (list[str]): The keyword tokens to search for (already split/cleaned by
            the caller).

    Returns:
        int: The total number of keyword occurrences found across the note's searchable
            text fields; higher is more relevant. Falsy/empty keyword tokens contribute
            nothing.
    """
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
        """Rank saved research notes by keyword match count and return the top 15.

        Args:
            input (SearchResearchNotesInput): The validated keyword string (split on
                whitespace/commas into individual tokens).
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes which notes are searched.

        Returns:
            dict[str, Any]: `{"matches": [...], "count": int}` — notes with zero keyword
                matches are excluded entirely, and results are sorted by score descending,
                capped at the top 15.
        """
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
    """Input schema for `ListResearchNotesTool` (no fields — takes no arguments)."""

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
        """List all research notes for the curriculum in compact (non-summary) form.

        Args:
            input (ListResearchNotesInput): Empty input (no fields).
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes which notes are listed.

        Returns:
            dict[str, Any]: `{"notes": [...], "count": int}`, each note reduced to
                `id`, `title`, `url`, and `relevance` (full summaries are omitted to
                keep this listing cheap — fetch full notes via `search_research_notes`).
        """
        notes = fs.list_research_notes(ctx.curriculum_id)
        return {
            "notes": [
                {"id": n["id"], "title": n.get("title"), "url": n.get("url"), "relevance": n.get("relevance")}
                for n in notes
            ],
            "count": len(notes),
        }
