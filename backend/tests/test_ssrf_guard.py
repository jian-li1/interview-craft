"""SSRF guard (`_guard_url`/`_is_blocked_ip`) and `_fetch_page_markdown` error handling.

No network access needed — `_is_blocked_ip` is pure, and `_guard_url` resolution of
localhost/loopback names is deterministic without going out to the network. Fetch-error
paths are exercised by monkeypatching httpx rather than making real requests.
"""

from __future__ import annotations

import httpx
import pytest

from app.agent.tools.research import _fetch_page_markdown, _guard_url, _is_blocked_ip


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.1.1",  # link-local
        "::1",  # loopback v6
        "0.0.0.0",
    ],
)
def test_is_blocked_ip_true_for_private_ranges(ip):
    """Verify loopback, private, link-local, and unspecified IPs are all blocked."""
    assert _is_blocked_ip(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
def test_is_blocked_ip_false_for_public_ips(ip):
    """Verify ordinary public IP addresses are not blocked."""
    assert _is_blocked_ip(ip) is False


def test_is_blocked_ip_unparsable_defaults_to_blocked():
    """Verify a string that isn't a valid IP address fails closed (treated as blocked)."""
    assert _is_blocked_ip("not-an-ip") is True


def test_guard_url_rejects_non_http_scheme():
    """Verify non-http(s) schemes like ftp:// are rejected with a "scheme" error."""
    with pytest.raises(ValueError, match="scheme"):
        _guard_url("ftp://example.com/file")


def test_guard_url_rejects_file_scheme():
    """Verify the file:// scheme is rejected with a "scheme" error."""
    with pytest.raises(ValueError, match="scheme"):
        _guard_url("file:///etc/passwd")


def test_guard_url_rejects_loopback_hostname():
    """Verify the hostname "localhost" is rejected as private/internal."""
    with pytest.raises(ValueError, match="private/internal"):
        _guard_url("http://localhost/admin")


def test_guard_url_rejects_loopback_ip_literal():
    """Verify a loopback IP literal (127.0.0.1) is rejected as private/internal."""
    with pytest.raises(ValueError, match="private/internal"):
        _guard_url("http://127.0.0.1:8080/")


def test_guard_url_rejects_no_hostname():
    """Verify a URL with no hostname component is rejected with a "hostname" error."""
    with pytest.raises(ValueError, match="hostname"):
        _guard_url("http:///path-only")


@pytest.mark.asyncio
async def test_fetch_page_markdown_returns_fetch_error_for_blocked_target():
    """`_fetch_page_markdown` must return a structured error dict, never raise.

    Verifies fetching a loopback-IP URL surfaces a `fetch_error` mentioning
    "private/internal" rather than propagating an exception.
    """
    result = await _fetch_page_markdown("http://127.0.0.1/secret")
    assert "fetch_error" in result
    assert "private/internal" in result["fetch_error"]


@pytest.mark.asyncio
async def test_fetch_page_markdown_rejects_bad_scheme_without_raising():
    """Verify a non-http scheme (e.g. javascript:) is surfaced as a fetch_error, not raised."""
    result = await _fetch_page_markdown("javascript:alert(1)")
    assert "fetch_error" in result


@pytest.mark.asyncio
async def test_fetch_page_markdown_success_includes_title_key(monkeypatch):
    """Verify a successful fetch returns the new `title` key alongside content_markdown."""

    class _Response:
        """Stand-in httpx streamed response carrying canned HTML."""

        status_code = 200
        headers = {"content-type": "text/html"}
        encoding = "utf-8"

        def raise_for_status(self):
            """No-op: simulate a 200 OK."""
            return None

        async def aread(self):
            """Return canned HTML with a <title> tag as raw bytes."""
            return b"<html><head><title>Example Page</title></head><body><p>Hi</p></body></html>"

    class _StreamCtx:
        """Async context manager wrapping the canned `_Response`."""

        async def __aenter__(self):
            """Enter the stream context manager, returning the canned response."""
            return _Response()

        async def __aexit__(self, *exc_info):
            """Exit the stream context manager; nothing to clean up."""
            return False

    class _SuccessClient:
        """Stand-in httpx.AsyncClient whose `stream` yields a successful HTML response."""

        async def __aenter__(self):
            """Enter the async context manager, returning self."""
            return self

        async def __aexit__(self, *exc_info):
            """Exit the async context manager; nothing to clean up."""
            return False

        def stream(self, method, url):
            """Return the canned streamed response context manager."""
            return _StreamCtx()

    monkeypatch.setattr("app.agent.tools.research.httpx.AsyncClient", lambda **kwargs: _SuccessClient())
    result = await _fetch_page_markdown("http://example.com/page")
    assert result["title"] == "Example Page"
    assert "Hi" in result["content_markdown"]
    assert result["content_truncated"] is False


@pytest.mark.asyncio
async def test_fetch_page_markdown_times_out_gracefully(monkeypatch):
    """Verify an httpx timeout during the actual fetch surfaces as a fetch_error, not a raise."""

    class _TimeoutClient:
        """Stand-in httpx.AsyncClient whose `stream` always times out."""

        async def __aenter__(self):
            """Enter the async context manager, returning self."""
            return self

        async def __aexit__(self, *exc_info):
            """Exit the async context manager; nothing to clean up."""
            return False

        def stream(self, method, url):
            """Raise a timeout as soon as the caller enters the stream's context manager."""
            raise httpx.TimeoutException("simulated timeout")

    monkeypatch.setattr("app.agent.tools.research.httpx.AsyncClient", lambda **kwargs: _TimeoutClient())
    result = await _fetch_page_markdown("http://example.com/slow")
    assert "fetch_error" in result
    assert "timed out" in result["fetch_error"]
