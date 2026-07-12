"""Settings API: GET/PUT /api/settings, including the explicit-null-clears-override semantics.

Covers the "Server default" bug fix — sending `{"field": null}` on PUT must clear a
previously-set override back to the server default rather than being silently dropped.
`UserSettings` now only carries `theme` (LLM model / search provider selection moved to
per-conversation composer chips — see `app/models/conversation.py`), so these tests
exercise the null-clears-override semantics on `theme` instead of the removed
`llm_provider`/`search_provider` fields.
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
    """Verify GET /api/settings returns the model default theme when the user has no
    stored settings.
    """
    authed = _authed_client(client)
    response = authed.get("/api/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["theme"] == "system"


def test_put_settings_sets_theme(client, fake_fs):
    """Verify PUT with theme="dark" is reflected in the response and a subsequent GET."""
    authed = _authed_client(client)
    put_response = authed.put(
        "/api/settings",
        json={"theme": "dark"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert put_response.status_code == 200
    assert put_response.json()["theme"] == "dark"

    get_response = authed.get("/api/settings")
    assert get_response.json()["theme"] == "dark"


def test_put_settings_explicit_null_clears_theme_override(client, fake_fs):
    """Verify explicit null clears a previously-set theme override back to the server
    default ("system").
    """
    authed = _authed_client(client)
    authed.put(
        "/api/settings",
        json={"theme": "dark"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    clear_response = authed.put(
        "/api/settings",
        json={"theme": None},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert clear_response.status_code == 200
    assert clear_response.json()["theme"] == "system"

    get_response = authed.get("/api/settings")
    assert get_response.json()["theme"] == "system"


def test_put_settings_omitted_field_left_unchanged(client, fake_fs):
    """Verify a PUT that omits `theme` entirely leaves its previously-set value unchanged
    (only an explicit null clears it — see the test above)."""
    authed = _authed_client(client)
    authed.put(
        "/api/settings",
        json={"theme": "light"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    # Empty body: theme is omitted (not nulled), so it must survive untouched.
    response = authed.put(
        "/api/settings",
        json={},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    assert response.json()["theme"] == "light"
