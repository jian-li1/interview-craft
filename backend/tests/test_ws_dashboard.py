"""Dashboard WS endpoint (/ws/dashboard) + the firestore curriculum-change signal.

Covers: unauthenticated connect closes 4401, authenticated ping/pong, and
`notify_curriculum_changed` delivering `curriculum_updated`/`curriculum_deleted` events
to the right owner's sockets only. No real network/credentials — Firestore is faked via
`fake_fs` and the WS is driven through Starlette's `TestClient.websocket_connect`.

Since `fake_fs` monkeypatches `create_curriculum`/`update_curriculum`/`delete_curriculum`
with plain in-memory fakes that never call the real listener-firing code in
`app/services/firestore.py`, the notify path itself is exercised by calling
`notify_curriculum_changed` directly (its internal `fs.get_curriculum` call still hits
the fake store, so a curriculum seeded via `fake_fs.fs.create_curriculum` is visible to
it) rather than relying on the fakes to fire it automatically.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


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


def _authed_client(client, uid: str = "uid1") -> TestClient:
    """Mint a session JWT for `uid` and attach it to the client as a cookie.

    Args:
        client (TestClient): The test client to authenticate in place.
        uid (str): The uid to mint a session for.

    Returns:
        TestClient: The same client instance, now carrying a valid `ic_session` cookie.
    """
    from app.core.config import get_settings
    from app.core.security import create_session_jwt

    settings = get_settings()
    token = create_session_jwt(uid, settings)
    client.cookies.set("ic_session", token)
    return client


def test_dashboard_ws_requires_auth(client):
    """An unauthenticated connect attempt must be rejected with close code 4401."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/dashboard"):
            pass
    assert exc_info.value.code == 4401


def test_dashboard_ws_ping_pong(client):
    """An authenticated connection replies to a `ping` frame with `pong`."""
    authed = _authed_client(client)
    with authed.websocket_connect("/ws/dashboard") as ws:
        ws.send_json({"type": "ping"})
        event = ws.receive_json()
    assert event == {"type": "pong"}


def test_notify_curriculum_changed_delivers_to_owner(client, fake_fs):
    """A curriculum update for the connected user's own curriculum delivers
    `curriculum_updated` with the summary fields to that user's socket.

    Uses `ws.portal.call(...)` to invoke the sync `notify_curriculum_changed` on the
    SAME event loop/thread the WS connection is running on (Starlette's TestClient
    drives the ASGI app via an anyio blocking portal in a background thread) — calling
    it from the test's own thread would find no running loop and silently no-op.
    """
    curriculum = fake_fs.fs.create_curriculum("uid1", "My Curriculum", "prep me", conversation_id="conv1")
    authed = _authed_client(client, uid="uid1")

    from app.ws.dashboard import notify_curriculum_changed

    with authed.websocket_connect("/ws/dashboard") as ws:
        ws.portal.call(notify_curriculum_changed, curriculum["id"], "uid1")
        event = ws.receive_json()

    assert event["type"] == "curriculum_updated"
    assert event["curriculum"]["id"] == curriculum["id"]
    assert event["curriculum"]["title"] == "My Curriculum"
    assert event["curriculum"]["owner_uid"] == "uid1"


def test_notify_curriculum_changed_ignores_other_owner(client, fake_fs):
    """A curriculum update for a DIFFERENT user's curriculum must not reach this
    socket — asserted by sending a ping afterward and seeing only `pong` come back."""
    curriculum = fake_fs.fs.create_curriculum("uid2", "Someone Else's", "prep me", conversation_id="conv2")
    authed = _authed_client(client, uid="uid1")

    from app.ws.dashboard import notify_curriculum_changed

    with authed.websocket_connect("/ws/dashboard") as ws:
        ws.portal.call(notify_curriculum_changed, curriculum["id"], "uid2")
        ws.send_json({"type": "ping"})
        event = ws.receive_json()

    # If the other owner's event had leaked through, it would have arrived before pong.
    assert event == {"type": "pong"}


def test_notify_curriculum_changed_for_deleted_doc_delivers_curriculum_deleted(client, fake_fs):
    """When the curriculum doc no longer exists and an owner_uid hint is given, the
    owner's socket receives `curriculum_deleted` rather than `curriculum_updated`."""
    authed = _authed_client(client, uid="uid1")

    from app.ws.dashboard import notify_curriculum_changed

    with authed.websocket_connect("/ws/dashboard") as ws:
        # "gone-id" was never created in fake_fs's store, so fs.get_curriculum returns None.
        ws.portal.call(notify_curriculum_changed, "gone-id", "uid1")
        event = ws.receive_json()

    assert event == {"type": "curriculum_deleted", "curriculum_id": "gone-id"}


def test_notify_curriculum_changed_noop_without_owner_hint_when_doc_gone(client, fake_fs):
    """When the doc is gone AND no owner_uid hint was given, nothing is emitted at all
    (there's no one to target) — asserted the same way as the other-owner test."""
    authed = _authed_client(client, uid="uid1")

    from app.ws.dashboard import notify_curriculum_changed

    with authed.websocket_connect("/ws/dashboard") as ws:
        ws.portal.call(notify_curriculum_changed, "gone-id", None)
        ws.send_json({"type": "ping"})
        event = ws.receive_json()

    assert event == {"type": "pong"}


def test_register_curriculum_listener_fires_and_isolates_errors():
    """Unit-tests the listener registry in `app.services.firestore` directly (not via
    `fake_fs`, which replaces `update_curriculum` wholesale and never calls the real
    listener-firing code): a registered listener is invoked with the right args, and a
    listener that raises never propagates past `_notify_curriculum_listeners`.
    """
    import app.services.firestore as fs

    calls: list[tuple[str, str | None]] = []

    def good_listener(curriculum_id: str, owner_uid: str | None) -> None:
        calls.append((curriculum_id, owner_uid))

    def bad_listener(curriculum_id: str, owner_uid: str | None) -> None:
        raise RuntimeError("boom")

    original = list(fs._curriculum_listeners)
    try:
        fs._curriculum_listeners.clear()
        fs.register_curriculum_listener(bad_listener)
        fs.register_curriculum_listener(good_listener)
        # Must not raise despite bad_listener blowing up; good_listener still fires.
        fs._notify_curriculum_listeners("cid1", "uid1")
        assert calls == [("cid1", "uid1")]
    finally:
        # Restore the module-level registry so other tests (e.g. app/ws/dashboard.py's
        # own registration at import time) aren't affected by this test's teardown.
        fs._curriculum_listeners[:] = original
