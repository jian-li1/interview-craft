"""Research tools: snippet-only web_search, standalone fetch_url, and save_sources.

Iteration 2 of the research architecture: web_search returns cheap snippets for
relevance triage only; the agent must call fetch_url to read a page's full content
before deciding whether to save it (via save_sources, with its own written summary).
Full page content never lands in the system prompt — only the agent's own summaries
do (see `memory/manager.py`'s `build_sources_memory_block`), keeping working memory
small while `content_markdown` is still persisted per source as citation evidence.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as _markdownify
from pydantic import BaseModel, Field

from app.agent.tools.base import AgentContext, Tool
from app.core.logging import get_logger
from app.services import firestore as fs

logger = get_logger(__name__)

_FETCH_TIMEOUT_SECONDS = 10.0
_ALLOWED_SCHEMES = {"http", "https"}

# Defensive per-page cap so one pathological page can't blow Firestore's 1 MiB document
# limit once saved via save_sources (Markdown is denser than raw HTML but still risky
# for very large pages).
PAGE_CONTENT_MAX_CHARS = 200_000


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


_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _html_to_title_and_markdown(html: str) -> tuple[str | None, str]:
    """Convert raw HTML to cleaned Markdown and extract the page `<title>`, in one parse pass.

    Args:
        html (str): The raw HTML document to convert.

    Returns:
        tuple[str | None, str]: `(title, markdown)`. `title` is the stripped text of the
            `<title>` tag if present, else None. `markdown` is ATX-style Markdown with
            script/style/noscript/svg content removed and runs of 3+ blank lines
            collapsed to 2; falls back to `(None, raw_html[:PAGE_CONTENT_MAX_CHARS])` if
            parsing raises.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        # Title must be read before the tag-stripping loop below (it doesn't touch
        # <title>, but keep parse-then-read order explicit for clarity).
        title = soup.title.get_text(strip=True) if soup.title else None
        # Drop tags that never contribute readable content (scripts/styles/inline SVG).
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        markdown = _markdownify(str(soup), heading_style="ATX")
        return title, _BLANK_LINES_RE.sub("\n\n", markdown)
    except Exception:
        logger.warning("html-to-markdown conversion failed; falling back to raw html")
        return None, html[:PAGE_CONTENT_MAX_CHARS]


async def _fetch_page_markdown(url: str) -> dict[str, Any]:
    """Fetch `url` and convert its HTML body to a title + capped Markdown.

    Runs the (blocking) SSRF guard in a thread executor since `_guard_url` calls
    `socket.getaddrinfo`, which would otherwise stall the event loop.

    Args:
        url (str): The absolute URL to fetch.

    Returns:
        dict[str, Any]: On success, `{"url", "title": str | None, "content_markdown",
            "content_truncated"}` (`content_truncated` is only meaningful as a bool,
            always present). On any failure (blocked URL, unsupported content-type,
            timeout, HTTP error), `{"url", "fetch_error": "..."}`.
    """
    loop = asyncio.get_running_loop()
    try:
        # Offload the blocking DNS resolution inside _guard_url to a thread.
        safe_url = await loop.run_in_executor(None, _guard_url, url)
    except ValueError as exc:
        return {"url": url, "fetch_error": str(exc)}

    try:
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "InterviewBlueprintBot/1.0 (+research agent)"},
        ) as client:
            async with client.stream("GET", safe_url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "text" not in content_type and "html" not in content_type:
                    return {"url": url, "fetch_error": f"unsupported content-type: {content_type}"}

                body = await response.aread()
                html = body.decode(response.encoding or "utf-8", errors="replace")
    except httpx.TimeoutException:
        return {"url": url, "fetch_error": f"timed out fetching {url}"}
    except httpx.HTTPStatusError as exc:
        return {"url": url, "fetch_error": f"http error {exc.response.status_code} fetching {url}"}
    except httpx.HTTPError as exc:
        return {"url": url, "fetch_error": f"failed to fetch {url}: {exc}"}

    title, markdown = _html_to_title_and_markdown(html)
    truncated = len(markdown) > PAGE_CONTENT_MAX_CHARS
    if truncated:
        markdown = markdown[:PAGE_CONTENT_MAX_CHARS]
    return {"url": url, "title": title, "content_markdown": markdown, "content_truncated": truncated}


class WebSearchInput(BaseModel):
    """Input schema for `WebSearchTool`."""

    query: str = Field(..., description="The search query string.")
    max_results: int = Field(8, ge=1, le=20, description="Maximum number of results to return.")


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web for a query and return a list of results (title, url, snippet). "
        "Use this to discover candidate sources during research. Issue diverse, specific "
        "queries rather than broad generic ones — see the research phase instructions for "
        "the query diversification strategy. Snippets are for RELEVANCE TRIAGE ONLY — "
        "deciding which results to fetch or skip. Always call fetch_url on a result and "
        "read its full content before saving it via save_sources; never save a source "
        "from a snippet alone."
    )
    input_model = WebSearchInput

    async def execute(self, input: WebSearchInput, ctx: AgentContext) -> dict[str, Any]:
        """Run a web search and return snippet-only results — no page fetching.

        Args:
            input (WebSearchInput): The validated query and max_results.
            ctx (AgentContext): The current agent run's context; `ctx.search` is the
                provider resolved from settings/user overrides.

        Returns:
            dict[str, Any]: `{"query", "results": [{"title","url","snippet"}], "count"}`.
        """
        results = await ctx.search.search(input.query, max_results=input.max_results)
        return {
            "query": input.query,
            "results": [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in results],
            "count": len(results),
        }


class FetchUrlInput(BaseModel):
    """Input schema for `FetchUrlTool`."""

    url: str = Field(..., description="The absolute URL to fetch and convert to Markdown.")


class FetchUrlTool(Tool):
    name = "fetch_url"
    description = (
        "Fetch a web page by URL and return its full content converted to Markdown "
        "(scripts/styles stripped). This is a REQUIRED step before saving a source via "
        "save_sources — search snippets alone are never enough to judge or summarize a "
        "page. Also use it to re-read the full content of a source you saved earlier "
        "(its URL is listed in your working memory). When the same URL is fetched again, "
        "earlier fetch results for it are removed from the conversation automatically, so "
        "re-fetching never duplicates context. Blocks private/internal network addresses "
        "(SSRF protection) and returns an error observation on failures — when a fetch "
        "fails, skip the source and move on to a different candidate rather than retrying "
        "the same URL."
    )
    input_model = FetchUrlInput

    async def execute(self, input: FetchUrlInput, ctx: AgentContext) -> dict[str, Any]:
        """Fetch a single URL's full content, caching it for a later save_sources call.

        Args:
            input (FetchUrlInput): The validated URL to fetch.
            ctx (AgentContext): The current agent run's context; `ctx.page_cache` is
                populated here so save_sources can persist without re-fetching.

        Returns:
            dict[str, Any]: `{"error": ...}` on fetch failure (registry maps this to
                status "error"); otherwise `{"url", "title", "content_markdown",
                "content_truncated"}`.
        """
        page = await _fetch_page_markdown(input.url)
        if "fetch_error" in page:
            return {"error": page["fetch_error"]}

        # Cache the fetched page (title falls back to the URL) so save_sources can
        # persist it later without a second network round-trip.
        ctx.page_cache[input.url] = {
            "title": page.get("title") or input.url,
            "content_markdown": page["content_markdown"],
            "content_truncated": page.get("content_truncated", False),
        }
        return {
            "url": input.url,
            "title": page.get("title") or input.url,
            "content_markdown": page["content_markdown"],
            "content_truncated": page.get("content_truncated", False),
        }


class SourceToSave(BaseModel):
    """One URL + agent-written summary pair to persist via `SaveSourcesTool`."""

    url: str = Field(..., description="A result URL whose full content you fetched and read via fetch_url.")
    summary: str = Field(
        ...,
        min_length=1,
        max_length=1500,
        description=(
            "Your own dense summary of the page, AT MOST 5 sentences: what the page "
            "contains and why it matters for this curriculum. This is what stays visible "
            "in your working memory, so make it recall the page's value at a glance."
        ),
    )


class SaveSourcesInput(BaseModel):
    """Input schema for `SaveSourcesTool`."""

    query: str = Field(..., description="The exact search query whose results these URLs came from.")
    sources: list[SourceToSave] = Field(
        ..., description="The sources genuinely worth keeping — be selective."
    )


class SaveSourcesTool(Tool):
    name = "save_sources"
    description = (
        "Pin the relevant sources you have READ (via fetch_url) into your working "
        "memory. Pass the exact query that surfaced them and, for each URL, a summary of "
        "AT MOST 5 sentences capturing what the page contains and why it matters for "
        "this curriculum — the summary (not the full page) is what stays permanently "
        "visible in your working memory, grouped under its query. Only URLs whose full "
        "content you fetched with fetch_url can be saved — a URL you never fetched is "
        "rejected with status not_fetched; fetch it first. URLs already saved earlier are "
        "skipped automatically, so duplicates are impossible. To re-read a saved page's "
        "full content later, call fetch_url on its URL."
    )
    input_model = SaveSourcesInput

    async def execute(self, input: SaveSourcesInput, ctx: AgentContext) -> dict[str, Any]:
        """Persist chosen URLs with the agent's own summary, strictly requiring a prior fetch.

        Args:
            input (SaveSourcesInput): The validated query and per-URL summaries (order
                preserved, duplicate URLs within the list collapsed — first summary wins).
            ctx (AgentContext): The current agent run's context; `ctx.curriculum_id`
                scopes storage, `ctx.page_cache` supplies content for URLs already
                fetched this run (no re-fetching fallback — read-before-save is strict).

        Returns:
            dict[str, Any]: `{"query", "results": [{"url", "status", ("error")}],
                "saved_count": int}`.
        """
        # Preserve first-appearance order while deduping by url; first summary wins.
        seen: set[str] = set()
        unique_sources: list[SourceToSave] = []
        for source in input.sources:
            if source.url not in seen:
                seen.add(source.url)
                unique_sources.append(source)

        results: dict[str, dict[str, Any]] = {}
        saved_count = 0
        for source in unique_sources:
            if fs.source_exists(ctx.curriculum_id, source.url):
                results[source.url] = {"url": source.url, "status": "duplicate_skipped"}
                continue
            cached = ctx.page_cache.get(source.url)
            if cached is None:
                # Strict read-before-save: never silently fetch on the tool's behalf.
                results[source.url] = {
                    "url": source.url,
                    "status": "not_fetched",
                    "error": "URL was never fetched this run — call fetch_url on it first, then save it",
                }
                continue
            fs.create_source(
                ctx.curriculum_id,
                {
                    "query": input.query,
                    "url": source.url,
                    "title": cached.get("title") or source.url,
                    # Agent's own distillation — the only part injected into memory.
                    "summary": source.summary,
                    # Full content persisted as citation evidence, retrievable via fetch_url.
                    "content_markdown": cached["content_markdown"],
                    "content_truncated": cached.get("content_truncated", False),
                },
            )
            results[source.url] = {"url": source.url, "status": "saved"}
            saved_count += 1

        return {
            "query": input.query,
            "results": [results[s.url] for s in unique_sources],
            "saved_count": saved_count,
        }


def strip_stale_fetch_url_outputs(conversation_id: str) -> int:
    """Rewrite every non-latest `fetch_url` tool output per URL to remove its page content.

    Called after any batch containing a successful `fetch_url` call so re-fetching the
    same URL later in a long conversation doesn't leave duplicate full-page Markdown
    sitting in the model-facing history — only the most recent fetch of a given URL
    keeps its content; earlier fetches of that URL are rewritten to a short note.

    Args:
        conversation_id (str): The conversation whose messages to scan and rewrite.

    Returns:
        int: The number of messages whose `tool_calls` were rewritten (0 on any
            internal failure — this function never raises).
    """
    updated_count = 0
    try:
        messages = fs.list_messages(conversation_id)

        # Pass 1: find, for each URL, the (message_index, tool_call_index) of its LAST
        # fetch_url occurrence — chronological message order, then call order within a
        # message — so pass 2 knows which occurrence to leave untouched.
        last_occurrence: dict[str, tuple[int, int]] = {}
        parsed_outputs: dict[tuple[int, int], dict[str, Any]] = {}
        for msg_idx, msg in enumerate(messages):
            for tc_idx, tc in enumerate(msg.get("tool_calls") or []):
                if tc.get("name") != "fetch_url":
                    continue
                try:
                    output = json.loads(tc.get("output_full") or "{}")
                except Exception:
                    continue
                if not isinstance(output, dict) or "content_markdown" not in output:
                    continue
                url = output.get("url")
                if not url:
                    continue
                parsed_outputs[(msg_idx, tc_idx)] = output
                last_occurrence[url] = (msg_idx, tc_idx)

        # Pass 2: rewrite every occurrence that isn't the last one for its URL.
        for msg_idx, msg in enumerate(messages):
            tool_calls = msg.get("tool_calls") or []
            changed = False
            new_tool_calls = []
            for tc_idx, tc in enumerate(tool_calls):
                output = parsed_outputs.get((msg_idx, tc_idx))
                if output is None or last_occurrence.get(output["url"]) == (msg_idx, tc_idx):
                    new_tool_calls.append(tc)
                    continue
                stripped_output = {
                    "url": output["url"],
                    "note": (
                        "full page content removed — this URL was re-fetched later in the "
                        "conversation; the latest fetch_url result carries the content"
                    ),
                }
                new_tool_calls.append({**tc, "output_full": json.dumps(stripped_output)})
                changed = True
            if changed:
                fs.update_message(conversation_id, msg["id"], {"tool_calls": new_tool_calls})
                updated_count += 1
    except Exception:
        logger.warning("failed to strip stale fetch_url outputs", exc_info=True)
        return updated_count
    return updated_count
