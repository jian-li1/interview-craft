"""GET /api/models: read-only route backing the dashboard prompt box's chip options.

Mirrors `available_models`/`available_search_providers` (see test_llm_search_factories.py)
but asserts the actual HTTP response shape, plus the Gemini-gating-on-API-key behavior
via a real request instead of calling the factory functions directly.
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


def test_get_models_requires_auth(client):
    """An unauthenticated request to GET /api/models is rejected with 401."""
    response = client.get("/api/models")
    assert response.status_code == 401


def test_get_models_returns_expected_shape(client, monkeypatch):
    """Verify the response mirrors `available_models`/`available_search_providers` plus
    both defaults, with Gemini models excluded when GEMINI_API_KEY is unset.
    """
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", None)

    authed = _authed_client(client)
    response = authed.get("/api/models")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "models": [
            {"id": "gpt-4o", "provider": "openai"},
            {"id": "gpt-4o-mini", "provider": "openai"},
        ],
        "default_model": "gpt-4o",
        "search_providers": ["duckduckgo"],
        "default_search_provider": "duckduckgo",
    }


def test_get_models_includes_gemini_when_key_set(client, monkeypatch):
    """Gemini models appear in the response once GEMINI_API_KEY is configured."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.5-pro")

    authed = _authed_client(client)
    response = authed.get("/api/models")

    assert response.status_code == 200
    body = response.json()
    assert {"id": "gemini-2.5-pro", "provider": "gemini"} in body["models"]
