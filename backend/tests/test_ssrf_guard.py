"""fetch_url SSRF guard: blocks private/loopback/link-local/reserved addresses.

No network access needed — `_is_blocked_ip` is pure, and `_guard_url` resolution of
localhost/loopback names is deterministic without going out to the network.
"""

from __future__ import annotations

import pytest

from app.agent.tools.research import FetchUrlInput, FetchUrlTool, _guard_url, _is_blocked_ip


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
    assert _is_blocked_ip(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
def test_is_blocked_ip_false_for_public_ips(ip):
    assert _is_blocked_ip(ip) is False


def test_is_blocked_ip_unparsable_defaults_to_blocked():
    assert _is_blocked_ip("not-an-ip") is True


def test_guard_url_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="scheme"):
        _guard_url("ftp://example.com/file")


def test_guard_url_rejects_file_scheme():
    with pytest.raises(ValueError, match="scheme"):
        _guard_url("file:///etc/passwd")


def test_guard_url_rejects_loopback_hostname():
    with pytest.raises(ValueError, match="private/internal"):
        _guard_url("http://localhost/admin")


def test_guard_url_rejects_loopback_ip_literal():
    with pytest.raises(ValueError, match="private/internal"):
        _guard_url("http://127.0.0.1:8080/")


def test_guard_url_rejects_no_hostname():
    with pytest.raises(ValueError, match="hostname"):
        _guard_url("http:///path-only")


@pytest.mark.asyncio
async def test_fetch_url_tool_returns_error_observation_for_blocked_target():
    """The tool must return a structured error dict, never raise, per spec 02 §3."""
    tool = FetchUrlTool()
    ctx = object()  # execute() doesn't touch ctx for the guard-rejection path
    result = await tool.execute(FetchUrlInput(url="http://127.0.0.1/secret"), ctx)
    assert "error" in result
    assert "private/internal" in result["error"]


@pytest.mark.asyncio
async def test_fetch_url_tool_rejects_bad_scheme_without_raising():
    tool = FetchUrlTool()
    result = await tool.execute(FetchUrlInput(url="javascript:alert(1)"), object())
    assert "error" in result
