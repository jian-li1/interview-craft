"""Settings API: GET/PUT /api/settings, including the explicit-null-clears-override semantics.

Covers the "Server default" bug fix — sending `{"field": null}` on PUT must clear a
previously-set override back to the server default rather than being silently dropped.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(fake_fs):
    """Build a `TestClient` against the real app with Firestore calls faked out.

    Args:
        fake_fs: The `fake_fs` fixture from conftest.py, depended on here purely for
            its monkeypatching side effect.

    Returns:
        TestClient: A FastAPI test client wrapping `app.main.app`.
    """
    from app.main import app

    return TestClient(app)


def _authed_client(client) -> TestClient:
    """Mint a session JWT for uid "uid1" and attach it to the client as a cookie.

    Args:
        client (TestClient): The test client to authenticate in place.

    Returns:
        TestClient: The same client instance, now carrying a valid `ic_session` cookie.
    """
    from app.core.config import get_settings
    from app.core.security import create_session_jwt

    settings = get_settings()
    token = create_session_jwt("uid1", settings)
    client.cookies.set("ic_session", token)
    return client


def test_get_settings_returns_defaults_for_fresh_user(client, fake_fs):
    """Verify GET /api/settings returns model defaults when the user has no stored settings."""
    authed = _authed_client(client)
    response = authed.get("/api/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["theme"] == "system"
    assert body["llm_provider"] is None
    assert body["search_provider"] is None


def test_put_settings_sets_llm_provider(client, fake_fs):
    """Verify PUT with llm_provider="gemini" is reflected in the response and a subsequent GET."""
    authed = _authed_client(client)
    put_response = authed.put(
        "/api/settings",
        json={"llm_provider": "gemini"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert put_response.status_code == 200
    assert put_response.json()["llm_provider"] == "gemini"

    get_response = authed.get("/api/settings")
    assert get_response.json()["llm_provider"] == "gemini"


def test_put_settings_explicit_null_clears_override(client, fake_fs):
    """Verify explicit null clears a previously-set override back to server default,
    leaving an unrelated, separately-set field untouched.
    """
    authed = _authed_client(client)
    # Set both providers first so we can confirm only llm_provider gets cleared.
    authed.put(
        "/api/settings",
        json={"llm_provider": "gemini", "search_provider": "tavily"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    clear_response = authed.put(
        "/api/settings",
        json={"llm_provider": None},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert clear_response.status_code == 200
    cleared_body = clear_response.json()
    assert cleared_body["llm_provider"] is None
    assert cleared_body["search_provider"] == "tavily"

    get_response = authed.get("/api/settings")
    get_body = get_response.json()
    assert get_body["llm_provider"] is None
    assert get_body["search_provider"] == "tavily"


def test_put_settings_omitted_field_left_unchanged(client, fake_fs):
    """Verify a PUT that omits a field leaves its previously-set value unchanged."""
    authed = _authed_client(client)
    # Set both providers first.
    authed.put(
        "/api/settings",
        json={"llm_provider": "gemini", "search_provider": "tavily"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    # PUT only search_provider; llm_provider is omitted, not nulled, so it must survive.
    response = authed.put(
        "/api/settings",
        json={"search_provider": "google"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["search_provider"] == "google"
    assert body["llm_provider"] == "gemini"
