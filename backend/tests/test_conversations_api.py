"""POST /api/conversations: optional `selected_model`/`search_provider` in the body are
resolved (via resolve_model/resolve_search_provider) and persisted on the new
conversation doc — the dashboard prompt box's REST path for the composer chips (see
docs/specs/01 §5/§6). Omitting them keeps the doc fields null, matching prior behavior.
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


def test_create_conversation_without_selection_persists_nulls(client, fake_fs):
    """Omitting selected_model/search_provider from the body leaves both doc fields
    null (falls back to server defaults at use time), matching prior behavior.
    """
    authed = _authed_client(client)
    response = authed.post(
        "/api/conversations",
        json={"curriculum_prompt": "prep me for a SWE interview"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    conv_id = response.json()["conversation_id"]
    doc = fake_fs.fs.get_conversation(conv_id)
    assert doc["selected_model"] is None
    assert doc["search_provider"] is None


def test_create_conversation_persists_resolved_selection(client, fake_fs):
    """A valid selected_model/search_provider in the body is resolved and persisted
    verbatim on the new conversation doc.
    """
    authed = _authed_client(client)
    response = authed.post(
        "/api/conversations",
        json={
            "curriculum_prompt": "prep me for a SWE interview",
            "selected_model": "gpt-4o-mini",
            "search_provider": "duckduckgo",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    conv_id = response.json()["conversation_id"]
    doc = fake_fs.fs.get_conversation(conv_id)
    assert doc["selected_model"] == "gpt-4o-mini"
    assert doc["search_provider"] == "duckduckgo"


def test_create_conversation_unknown_model_falls_back_to_default(client, fake_fs):
    """An unrecognized selected_model resolves (and persists) as the server default
    rather than being stored verbatim or rejected.
    """
    from app.core.config import get_settings

    settings = get_settings()

    authed = _authed_client(client)
    response = authed.post(
        "/api/conversations",
        json={"curriculum_prompt": "prep me", "selected_model": "not-a-real-model"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    conv_id = response.json()["conversation_id"]
    doc = fake_fs.fs.get_conversation(conv_id)
    assert doc["selected_model"] == settings.default_model
