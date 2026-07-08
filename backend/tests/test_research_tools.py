"""Research tools: snippet-only web_search, standalone fetch_url (+ page cache), and
save_sources (strict read-before-save + agent-written summaries), plus the supporting
`_html_to_title_and_markdown`/`strip_stale_fetch_url_outputs` helpers. No real network
access — `ctx.search` and `_fetch_page_markdown` are mocked.
"""

from __future__ import annotations

import json

import pytest

from app.agent.tools.base import AgentContext
from app.agent.tools.research import (
    FetchUrlInput,
    FetchUrlTool,
    SaveSourcesInput,
    SaveSourcesTool,
    SourceToSave,
    WebSearchInput,
    WebSearchTool,
    _html_to_title_and_markdown,
    strip_stale_fetch_url_outputs,
)
from app.services.search.base import SearchResult


def _make_ctx(phase: str = "deep_research") -> AgentContext:
    """Build a minimal `AgentContext` with a fresh `page_cache` for tool-level tests.

    Args:
        phase (str): Agent phase to scope the context to (unused by these tools'
            `execute` methods, but required by the dataclass).

    Returns:
        AgentContext: Context with placeholder providers and an empty page_cache.
    """
    from app.core.config import get_settings

    return AgentContext(
        curriculum_id="cur1",
        conversation_id="conv1",
        owner_uid="uid1",
        settings=get_settings(),
        llm=object(),
        small_llm=object(),
        search=object(),
        phase=phase,
    )


class _StubSearch:
    """Fake search provider returning a fixed list of results, ignoring the query."""

    def __init__(self, results: list[SearchResult]) -> None:
        """Store the canned results to return from every `search` call."""
        self._results = results

    async def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        """Return the canned results regardless of query/max_results."""
        return self._results


@pytest.mark.asyncio
async def test_web_search_returns_snippets_only_and_does_not_touch_cache():
    """Verify web_search returns title/url/snippet only — no fetching, no page_cache writes."""
    ctx = _make_ctx()
    ctx.search = _StubSearch(
        [
            SearchResult(title="Guide", url="https://example.com/guide", snippet="A guide"),
            SearchResult(title="Other", url="https://example.com/other", snippet="Other page"),
        ]
    )

    tool = WebSearchTool()
    output = await tool.execute(WebSearchInput(query="system design"), ctx)

    assert output["query"] == "system design"
    assert output["count"] == 2
    assert output["results"] == [
        {"title": "Guide", "url": "https://example.com/guide", "snippet": "A guide"},
        {"title": "Other", "url": "https://example.com/other", "snippet": "Other page"},
    ]
    # web_search must never populate the page cache — that's fetch_url's job now.
    assert ctx.page_cache == {}


@pytest.mark.asyncio
async def test_fetch_url_success_populates_cache_and_returns_title_and_markdown(monkeypatch):
    """Verify a successful fetch_url call caches the page and returns title/markdown."""
    ctx = _make_ctx()

    async def fake_fetch(url: str) -> dict:
        """Return canned success with a title."""
        return {"url": url, "title": "Guide Title", "content_markdown": "# Guide content", "content_truncated": False}

    monkeypatch.setattr("app.agent.tools.research._fetch_page_markdown", fake_fetch)

    tool = FetchUrlTool()
    output = await tool.execute(FetchUrlInput(url="https://example.com/guide"), ctx)

    assert output == {
        "url": "https://example.com/guide",
        "title": "Guide Title",
        "content_markdown": "# Guide content",
        "content_truncated": False,
    }
    assert ctx.page_cache["https://example.com/guide"] == {
        "title": "Guide Title",
        "content_markdown": "# Guide content",
        "content_truncated": False,
    }


@pytest.mark.asyncio
async def test_fetch_url_failure_returns_error_and_does_not_cache(monkeypatch):
    """Verify a failed fetch_url call returns {"error": ...} and leaves the cache empty."""
    ctx = _make_ctx()

    async def fake_fetch(url: str) -> dict:
        """Simulate a fetch failure."""
        return {"url": url, "fetch_error": "timed out fetching " + url}

    monkeypatch.setattr("app.agent.tools.research._fetch_page_markdown", fake_fetch)

    tool = FetchUrlTool()
    output = await tool.execute(FetchUrlInput(url="https://example.com/broken"), ctx)

    assert output == {"error": "timed out fetching https://example.com/broken"}
    assert ctx.page_cache == {}


@pytest.mark.asyncio
async def test_fetch_url_falls_back_to_url_when_no_title(monkeypatch):
    """Verify a page with no <title> caches/returns the URL itself as the title."""
    ctx = _make_ctx()

    async def fake_fetch(url: str) -> dict:
        """Return canned success with no title."""
        return {"url": url, "title": None, "content_markdown": "content", "content_truncated": False}

    monkeypatch.setattr("app.agent.tools.research._fetch_page_markdown", fake_fetch)

    tool = FetchUrlTool()
    output = await tool.execute(FetchUrlInput(url="https://example.com/untitled"), ctx)

    assert output["title"] == "https://example.com/untitled"
    assert ctx.page_cache["https://example.com/untitled"]["title"] == "https://example.com/untitled"


@pytest.mark.asyncio
async def test_save_sources_saves_from_cache_with_agent_summary(fake_fs):
    """Verify a URL present in ctx.page_cache (from a prior fetch_url) is saved with the
    agent's own summary plus the cached title/content_markdown — no re-fetching.
    """
    ctx = _make_ctx()
    ctx.page_cache["https://example.com/guide"] = {
        "title": "Guide",
        "content_markdown": "# Guide content",
        "content_truncated": False,
    }

    tool = SaveSourcesTool()
    output = await tool.execute(
        SaveSourcesInput(
            query="system design",
            sources=[SourceToSave(url="https://example.com/guide", summary="A concise guide summary.")],
        ),
        ctx,
    )

    assert output["saved_count"] == 1
    assert output["results"] == [{"url": "https://example.com/guide", "status": "saved"}]

    saved = fake_fs.fs.list_sources("cur1")
    assert len(saved) == 1
    assert saved[0]["content_markdown"] == "# Guide content"
    assert saved[0]["title"] == "Guide"
    assert saved[0]["summary"] == "A concise guide summary."


@pytest.mark.asyncio
async def test_save_sources_never_refetches_on_cache_miss(fake_fs):
    """Verify a URL not in ctx.page_cache is rejected as not_fetched — save_sources must
    never fetch on its own; the read-before-save rule is enforced strictly.
    """
    ctx = _make_ctx()

    tool = SaveSourcesTool()
    output = await tool.execute(
        SaveSourcesInput(
            query="system design",
            sources=[SourceToSave(url="https://example.com/unfetched", summary="Some summary.")],
        ),
        ctx,
    )

    assert output["saved_count"] == 0
    assert output["results"] == [
        {
            "url": "https://example.com/unfetched",
            "status": "not_fetched",
            "error": "URL was never fetched this run — call fetch_url on it first, then save it",
        }
    ]
    assert fake_fs.fs.list_sources("cur1") == []


@pytest.mark.asyncio
async def test_save_sources_dedupes_within_list_and_against_existing(fake_fs):
    """Verify duplicate URLs within the input list collapse to one save (first summary
    wins), and a URL already saved in a prior call is reported as `duplicate_skipped`.
    """
    ctx = _make_ctx()
    ctx.page_cache["https://example.com/a"] = {
        "title": "A",
        "content_markdown": "content A",
        "content_truncated": False,
    }

    tool = SaveSourcesTool()
    # First call saves it.
    first = await tool.execute(
        SaveSourcesInput(
            query="q1", sources=[SourceToSave(url="https://example.com/a", summary="First summary.")]
        ),
        ctx,
    )
    assert first["saved_count"] == 1

    # Second call: same URL repeated twice in the input list, plus already saved from
    # the first call — everything should collapse to a single duplicate_skipped entry.
    second = await tool.execute(
        SaveSourcesInput(
            query="q1",
            sources=[
                SourceToSave(url="https://example.com/a", summary="Second summary A."),
                SourceToSave(url="https://example.com/a", summary="Second summary B."),
            ],
        ),
        ctx,
    )
    assert second["saved_count"] == 0
    assert second["results"] == [{"url": "https://example.com/a", "status": "duplicate_skipped"}]

    # Still only one source document persisted overall, with the first-call summary.
    saved = fake_fs.fs.list_sources("cur1")
    assert len(saved) == 1
    assert saved[0]["summary"] == "First summary."


def test_strip_stale_fetch_url_outputs_keeps_last_across_messages(fake_fs):
    """Verify two fetch_url calls for the same URL in different messages: the earlier
    one loses content_markdown, the later one keeps it untouched.
    """
    conv = fake_fs.fs.create_conversation("uid1", "chat", curriculum_id="cur1")
    first_output = json.dumps({"url": "https://example.com/x", "title": "X", "content_markdown": "old content"})
    fake_fs.fs.append_message(
        conv["id"],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "tc1", "name": "fetch_url", "output_full": first_output, "output_preview": "..."},
            ],
        },
    )
    second_output = json.dumps({"url": "https://example.com/x", "title": "X", "content_markdown": "new content"})
    fake_fs.fs.append_message(
        conv["id"],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "tc2", "name": "fetch_url", "output_full": second_output, "output_preview": "..."},
            ],
        },
    )

    updated = strip_stale_fetch_url_outputs(conv["id"])
    assert updated == 1  # only the first message was rewritten

    messages = fake_fs.fs.list_messages(conv["id"])
    first_tc = messages[0]["tool_calls"][0]
    rewritten = json.loads(first_tc["output_full"])
    assert "content_markdown" not in rewritten
    assert rewritten["url"] == "https://example.com/x"

    second_tc = messages[1]["tool_calls"][0]
    kept = json.loads(second_tc["output_full"])
    assert kept["content_markdown"] == "new content"


def test_strip_stale_fetch_url_outputs_same_message_keeps_last_call(fake_fs):
    """Verify two fetch_url calls for the same URL within ONE message: the earlier
    tool_call index is stripped, the later one (higher index) keeps its content.
    """
    conv = fake_fs.fs.create_conversation("uid1", "chat", curriculum_id="cur1")
    older = json.dumps({"url": "https://example.com/y", "content_markdown": "old"})
    newer = json.dumps({"url": "https://example.com/y", "content_markdown": "new"})
    fake_fs.fs.append_message(
        conv["id"],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "tc1", "name": "fetch_url", "output_full": older, "output_preview": "..."},
                {"id": "tc2", "name": "fetch_url", "output_full": newer, "output_preview": "..."},
            ],
        },
    )

    updated = strip_stale_fetch_url_outputs(conv["id"])
    assert updated == 1

    messages = fake_fs.fs.list_messages(conv["id"])
    tool_calls = {tc["id"]: tc for tc in messages[0]["tool_calls"]}
    assert "content_markdown" not in json.loads(tool_calls["tc1"]["output_full"])
    assert json.loads(tool_calls["tc2"]["output_full"])["content_markdown"] == "new"


def test_strip_stale_fetch_url_outputs_leaves_non_fetch_calls_and_single_fetch_alone(fake_fs):
    """Verify non-fetch_url calls are untouched, and a URL fetched only once keeps content."""
    conv = fake_fs.fs.create_conversation("uid1", "chat", curriculum_id="cur1")
    fetch_output = json.dumps({"url": "https://example.com/z", "content_markdown": "content"})
    other_output = json.dumps({"note_id": "abc123"})
    fake_fs.fs.append_message(
        conv["id"],
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "tc1", "name": "fetch_url", "output_full": fetch_output, "output_preview": "..."},
                {"id": "tc2", "name": "set_module_status", "output_full": other_output, "output_preview": "..."},
            ],
        },
    )

    updated = strip_stale_fetch_url_outputs(conv["id"])
    assert updated == 0  # single fetch of /z — nothing to strip

    messages = fake_fs.fs.list_messages(conv["id"])
    tool_calls = {tc["id"]: tc for tc in messages[0]["tool_calls"]}
    assert json.loads(tool_calls["tc1"]["output_full"])["content_markdown"] == "content"
    assert tool_calls["tc2"]["output_full"] == other_output


def test_strip_stale_fetch_url_outputs_no_matching_messages_returns_zero(fake_fs):
    """Verify a conversation with no fetch_url-with-content messages updates nothing."""
    conv = fake_fs.fs.create_conversation("uid1", "chat", curriculum_id="cur1")
    fake_fs.fs.append_message(conv["id"], {"role": "user", "content": "hi"})
    assert strip_stale_fetch_url_outputs(conv["id"]) == 0


def test_html_to_title_and_markdown_extracts_title_strips_script_and_style():
    """Verify the <title> is extracted, script/style content excluded, and headings
    become ATX-style Markdown.
    """
    html = """
    <html>
      <head><title>My Page Title</title><style>body { color: red; }</style></head>
      <body>
        <script>alert('should not appear');</script>
        <h1>Main Title</h1>
        <p>Some paragraph text.</p>
      </body>
    </html>
    """
    title, markdown = _html_to_title_and_markdown(html)
    assert title == "My Page Title"
    assert "color: red" not in markdown
    assert "should not appear" not in markdown
    assert "# Main Title" in markdown
    assert "Some paragraph text." in markdown


def test_html_to_title_and_markdown_no_title_tag_returns_none():
    """Verify a page with no <title> tag yields title=None without raising."""
    html = "<html><body><p>No title here.</p></body></html>"
    title, markdown = _html_to_title_and_markdown(html)
    assert title is None
    assert "No title here." in markdown
