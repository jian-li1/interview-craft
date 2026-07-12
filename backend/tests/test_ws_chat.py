"""WS chat endpoint: session_ready payload carries the composer's model/search options.

Covers the four new session_ready fields (available_models, selected_model,
search_providers, search_provider) added for the per-conversation composer chips, and
that a `compact` frame forwards its `model` field through to `Orchestrator.compact_now`.
No real network/credentials — Firestore is faked via `fake_fs` and the WS is driven
through Starlette's `TestClient.websocket_connect`.
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
        TestClient: The same client instance, now carrying a valid `ic_session` cookie
            (also sent on the WS upgrade request by Starlette's TestClient).
    """
    from app.core.config import get_settings
    from app.core.security import create_session_jwt

    settings = get_settings()
    token = create_session_jwt("uid1", settings)
    client.cookies.set("ic_session", token)
    return client


def _setup_conversation(fake_fs):
    """Seed a bare conversation (no curriculum) owned by "uid1".

    Args:
        fake_fs: The `fake_fs` fixture, used to seed the in-memory store directly.

    Returns:
        dict: The newly created conversation document.
    """
    return fake_fs.fs.create_conversation("uid1", "Test chat", curriculum_id=None)


def test_session_ready_carries_model_and_search_options(client, fake_fs):
    """Verify `session_ready` includes available_models/selected_model/search_providers/
    search_provider, resolved from the conversation's (unset) persisted selection down to
    the server defaults.
    """
    conv = _setup_conversation(fake_fs)
    authed = _authed_client(client)

    with authed.websocket_connect(f"/ws/chat/{conv['id']}") as ws:
        event = ws.receive_json()

    assert event["type"] == "session_ready"
    # conftest sets OPENAI_MODEL="gpt-4o,gpt-4o-mini"; no GEMINI_API_KEY -> openai only.
    assert event["available_models"] == [
        {"id": "gpt-4o", "provider": "openai"},
        {"id": "gpt-4o-mini", "provider": "openai"},
    ]
    assert event["selected_model"] == "gpt-4o"
    assert event["search_providers"] == ["duckduckgo"]
    assert event["search_provider"] == "duckduckgo"


def test_session_ready_reflects_persisted_conversation_selection(client, fake_fs):
    """Verify a conversation doc with a persisted selected_model/search_provider has
    those values resolved and echoed back on session_ready (not the defaults)."""
    conv = _setup_conversation(fake_fs)
    fake_fs.fs.update_conversation(conv["id"], {"selected_model": "gpt-4o-mini", "search_provider": "duckduckgo"})
    authed = _authed_client(client)

    with authed.websocket_connect(f"/ws/chat/{conv['id']}") as ws:
        event = ws.receive_json()

    assert event["selected_model"] == "gpt-4o-mini"
    assert event["search_provider"] == "duckduckgo"


def test_session_ready_falls_back_when_persisted_model_no_longer_available(client, fake_fs):
    """A stale persisted selection (e.g. a model removed from OPENAI_MODEL since it was
    picked) must resolve to the server default rather than being echoed back verbatim."""
    conv = _setup_conversation(fake_fs)
    fake_fs.fs.update_conversation(conv["id"], {"selected_model": "no-longer-configured-model"})
    authed = _authed_client(client)

    with authed.websocket_connect(f"/ws/chat/{conv['id']}") as ws:
        event = ws.receive_json()

    assert event["selected_model"] == "gpt-4o"


def test_compact_frame_forwards_model_to_orchestrator(client, fake_fs, monkeypatch):
    """Verify a `compact` frame's `model` field is forwarded through to
    `Orchestrator.compact_now`, driving the resolved model persisted onto the
    conversation doc.
    """
    conv = fake_fs.fs.create_conversation("uid1", "Test chat", curriculum_id=None)
    curriculum = fake_fs.fs.create_curriculum(
        "uid1", "Test curriculum", "prep me", conversation_id=conv["id"]
    )
    fake_fs.fs.update_conversation(conv["id"], {"curriculum_id": curriculum["id"]})
    # A couple of messages so build_context's >2-candidate-messages compaction guard
    # doesn't skip the pass before we can observe the persisted model.
    for i in range(3):
        fake_fs.fs.append_message(conv["id"], {"role": "user", "content": f"message {i}"})

    class _StubLLM:
        """Minimal LLMProvider stand-in whose complete() returns a canned summary."""

        async def complete(self, messages) -> str:
            """Return a fixed compaction summary regardless of input."""
            return "## Summary\n\nStub."

        async def chat_stream(self, messages, tools=None):
            """Unused by compaction; present only to satisfy the protocol."""
            raise NotImplementedError

    captured_models: list[str | None] = []

    def fake_get_llm_provider(model=None, settings=None):
        """Record the resolved model id passed to the factory and return a stub LLM."""
        captured_models.append(model)
        return _StubLLM()

    monkeypatch.setattr("app.agent.orchestrator.get_llm_provider", fake_get_llm_provider)

    authed = _authed_client(client)
    with authed.websocket_connect(f"/ws/chat/{conv['id']}") as ws:
        ws.receive_json()  # session_ready
        ws.send_json({"type": "compact", "model": "gpt-4o-mini"})
        # Drain events until agent_done or compaction resolves, to let the background
        # task finish before asserting on the persisted conversation doc.
        for _ in range(10):
            event = ws.receive_json()
            if event["type"] in ("compaction", "error"):
                break

    assert "gpt-4o-mini" in captured_models
    updated_conv = fake_fs.fs.get_conversation(conv["id"])
    assert updated_conv["selected_model"] == "gpt-4o-mini"
