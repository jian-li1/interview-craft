"""WebSocket dashboard endpoint: /ws/dashboard.

Push-based replacement for the dashboard's old 8s `curriculaApi.list()` polling (see
docs/specs/01-architecture-and-contracts.md §7b). A connected socket receives
`curriculum_updated`/`curriculum_deleted` events whenever any of the user's curricula
change, sourced from a listener registered on `app.services.firestore` at import time. It
also receives `suggestions_updated` events, emitted directly (not via the listener
registry) by `app.services.prompt_suggestions.generate_prompt_suggestions` once async
dashboard PromptBox suggestion generation finishes after onboarding completes.

Known limitation: this broker is in-process only. On a multi-instance Cloud Run
deployment, a dashboard socket only receives events for curriculum writes that happen to
be handled by agent runs on the *same* instance — writes on other instances are silently
missed. This is acceptable for the current single-instance deploy; the client already
refetches the full list once on reconnect to catch anything missed while disconnected.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.curricula import _to_summary
from app.services import firestore as fs
from app.ws.chat import WS_CODE_UNAUTHORIZED, _authenticate_ws

logger = logging.getLogger(__name__)
router = APIRouter()


@dataclass(eq=False)
class _DashboardConnection:
    """One connected dashboard socket, plus its send-serialization lock.

    `eq=False` keeps the dataclass's default identity-based `__hash__` (auto-generated
    `__eq__`/field-based hashing would otherwise make two connections wrapping the same
    live-but-unequal `WebSocket` collide, and — worse — plain dataclasses become
    unhashable once `__eq__` is defined) so instances can live directly in the `set`
    values of `_connections` below.

    Attributes:
        ws (WebSocket): The accepted WebSocket connection.
        send_lock (asyncio.Lock): Serializes writes to `ws` so a background notification
            task and the connection's own receive loop never interleave partial frames.
    """

    ws: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Registry of every live dashboard socket, keyed by owner uid. Unlike the chat WS's
# "latest wins" registry, a user may have several dashboard tabs open simultaneously, so
# each uid maps to a SET of connections — all of them receive every event.
_connections: dict[str, set[_DashboardConnection]] = {}


@router.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket) -> None:
    """Dashboard WebSocket: pushes curriculum change events to the signed-in user.

    Authenticated the same way as `/ws/chat/{conversation_id}` (session cookie or
    `?token=` fallback). After a successful handshake, loops reading client frames —
    only `{"type": "ping"}` gets a reply (`{"type": "pong"}`); every other frame shape is
    silently ignored. The connection is removed from the registry in a `finally` block on
    disconnect.

    Args:
        ws (WebSocket): The incoming WebSocket connection, not yet accepted at entry.

    Returns:
        None: The connection is closed (4401 on auth failure, or implicitly on client
            disconnect) rather than any value returned.
    """
    uid = await _authenticate_ws(ws)
    if uid is None:
        await ws.close(code=WS_CODE_UNAUTHORIZED)
        return

    await ws.accept()
    conn = _DashboardConnection(ws=ws)
    _connections.setdefault(uid, set()).add(conn)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if frame.get("type") == "ping":
                async with conn.send_lock:
                    await ws.send_text(json.dumps({"type": "pong"}))
            # Any other frame type is silently ignored — this socket is read-only from
            # the client's perspective beyond keepalive pings.
    except WebSocketDisconnect:
        logger.info("dashboard ws client disconnected", extra={"extra_fields": {"uid": uid}})
    finally:
        # Drop this connection from the registry; clean up the uid's set entirely once empty.
        peers = _connections.get(uid)
        if peers is not None:
            peers.discard(conn)
            if not peers:
                del _connections[uid]


def notify_curriculum_changed(curriculum_id: str, owner_uid: str | None) -> None:
    """Sync entry point invoked by `firestore.py` right after any curriculum write.

    Registered onto `app.services.firestore`'s listener registry at import time (see the
    bottom of this module), so importing this module (which happens once, via
    `main.py`'s router registration) is what wires the notification path up. Cheap
    fast-path: if nobody has a dashboard socket open, return immediately without ever
    touching Firestore. Otherwise schedules the actual (async) notification work as a
    background task on the running event loop.

    Args:
        curriculum_id (str): The curriculum document id that was just written.
        owner_uid (str | None): The owner uid if cheaply known at the write site (create/
            delete); None for a plain `update_curriculum` call, in which case the
            background task re-fetches the doc to learn it.

    Returns:
        None:
    """
    if not _connections:
        # Nobody is watching — skip the Firestore read entirely.
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (e.g. a sync test context) — nothing to schedule onto.
        return
    loop.create_task(_notify_curriculum_changed_async(curriculum_id, owner_uid))


async def _notify_curriculum_changed_async(curriculum_id: str, owner_uid: str | None) -> None:
    """Background task: fetch the curriculum and push the appropriate event.

    Args:
        curriculum_id (str): The curriculum document id that was just written.
        owner_uid (str | None): The owner uid hint from the write site (used only for the
            delete-and-gone case, where the doc itself can no longer supply it).

    Returns:
        None:
    """
    doc = fs.get_curriculum(curriculum_id)
    if doc is not None:
        # Doc still exists (create/update): build the same summary shape the REST list
        # endpoint returns, and notify its actual owner's sockets.
        summary = _to_summary(doc)
        await _emit_to_owner(
            doc["owner_uid"], {"type": "curriculum_updated", "curriculum": summary.model_dump(mode="json")}
        )
    elif owner_uid is not None:
        # Doc is gone (delete) and we know who owned it — notify that owner directly.
        await _emit_to_owner(owner_uid, {"type": "curriculum_deleted", "curriculum_id": curriculum_id})


async def emit_suggestions_updated(uid: str, suggestions: list[str], placeholder: str) -> None:
    """Push a `suggestions_updated` event to every live dashboard socket for one user.

    Called directly (awaited, not fire-and-forget) by
    `app.services.prompt_suggestions.generate_prompt_suggestions` right after it persists
    the newly-generated PromptBox suggestions/placeholder — lets the PromptBox swap out of
    "pending" mode without a page refresh. Import direction is
    `services.prompt_suggestions -> ws.dashboard -> api.curricula`, which stays acyclic
    since neither of those modules imports back into `services.prompt_suggestions`.

    Args:
        uid (str): The owner uid whose dashboard sockets should receive the event.
        suggestions (list[str]): The generated PromptBox example-chip strings (up to 5).
        placeholder (str): The generated PromptBox textarea placeholder sentence.

    Returns:
        None:
    """
    await _emit_to_owner(
        uid,
        {"type": "suggestions_updated", "prompt_suggestions": suggestions, "prompt_placeholder": placeholder},
    )


async def _emit_to_owner(owner_uid: str, event: dict[str, Any]) -> None:
    """Send a JSON event to every currently-connected dashboard socket for one user.

    Args:
        owner_uid (str): The uid whose dashboard sockets should receive `event`.
        event (dict[str, Any]): The JSON-serializable event payload to send.

    Returns:
        None:
    """
    peers = list(_connections.get(owner_uid, ()))
    payload = json.dumps(event, default=str)
    for conn in peers:
        async with conn.send_lock:
            try:
                await conn.ws.send_text(payload)
            except Exception:
                # Dead socket: drop it so future notifications don't keep retrying it.
                logger.warning("failed to send dashboard WS event; dropping connection")
                live = _connections.get(owner_uid)
                if live is not None:
                    live.discard(conn)
                    if not live:
                        del _connections[owner_uid]


# Registered at import time (this module is imported once, via main.py's router
# registration) so every curriculum write anywhere in the app triggers this notification
# path without firestore.py needing to import anything from app.ws.
fs.register_curriculum_listener(notify_curriculum_changed)
