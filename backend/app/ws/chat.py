"""WebSocket chat endpoint: /ws/chat/{conversation_id}.

Implements the exact event protocol in docs/specs/01-architecture-and-contracts.md §7.
Authenticated via the `ic_session` cookie (browser same-site WS upgrade) with a `?token=`
query-param fallback carrying the same JWT, for environments where the cookie isn't sent
on the WS upgrade request.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agent.orchestrator import Orchestrator, PlanDecision, request_stop
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import SESSION_COOKIE_NAME, InvalidSessionTokenError, decode_session_jwt
from app.services import firestore as fs

logger = get_logger(__name__)
router = APIRouter()

# Codes chosen in the 4000-4999 (application-defined) range per RFC 6455.
WS_CODE_UNAUTHORIZED = 4401
WS_CODE_FORBIDDEN = 4403


async def _authenticate_ws(ws: WebSocket) -> str | None:
    """Resolve the uid for a WS connection from the cookie or `?token=` fallback.

    The cookie is preferred (matches REST auth) but some browser/proxy setups don't send
    same-site cookies on the WS upgrade request, so the same JWT is also accepted as a
    `?token=` query parameter as a fallback.

    Args:
        ws (WebSocket): The incoming WebSocket connection, not yet accepted.

    Returns:
        str | None: The authenticated user's uid, or None if no token was present or it
            failed validation.
    """
    settings = get_settings()
    token = ws.cookies.get(SESSION_COOKIE_NAME) or ws.query_params.get("token")
    if not token:
        return None
    try:
        return decode_session_jwt(token, settings)
    except InvalidSessionTokenError:
        return None


@router.websocket("/ws/chat/{conversation_id}")
async def ws_chat(ws: WebSocket, conversation_id: str) -> None:
    """Main chat WebSocket: streams agent turns and accepts client control frames.

    Implements the full event protocol from docs/specs/01-architecture-and-contracts.md
    §7: after a successful handshake it emits `session_ready`, then loops reading client
    frames (`ping`, `stop`, `user_message`, `plan_decision`) until the socket disconnects.
    Each `user_message`/`plan_decision` frame spawns the orchestrator's `run_turn` as a
    background asyncio task (rather than awaiting it inline) so the receive loop stays
    free to immediately accept a subsequent `stop` frame or `ping` while a long-running
    agent turn is in flight.

    Args:
        ws (WebSocket): The WebSocket connection, not yet accepted at entry.
        conversation_id (str): The conversation to attach this socket to, taken from the
            URL path.

    Returns:
        None: The connection is closed (with an application-defined code on auth
            failure, or implicitly on client disconnect) rather than any value returned.
    """
    # Auth happens before accept(): closing with a specific code pre-handshake tells the
    # client precisely why (unauthorized vs. forbidden) instead of a generic drop.
    uid = await _authenticate_ws(ws)
    if uid is None:
        await ws.close(code=WS_CODE_UNAUTHORIZED)
        return

    conversation = fs.get_conversation(conversation_id)
    if conversation is None:
        # No such conversation: treated as unauthorized (not 404) to avoid leaking
        # whether a conversation id exists to an unauthenticated/mismatched caller.
        await ws.close(code=WS_CODE_UNAUTHORIZED)
        return
    if conversation["owner_uid"] != uid:
        # Ownership check, mirroring get_owned_conversation's REST-side pattern.
        await ws.close(code=WS_CODE_FORBIDDEN)
        return

    await ws.accept()

    settings = get_settings()
    # One Orchestrator instance per connection; note its module-level lock/cancel state
    # (in app/agent/orchestrator.py) is keyed by conversation_id, not by this instance —
    # see backend/CLAUDE.md gotchas.
    orchestrator = Orchestrator(settings)
    curriculum_id = conversation.get("curriculum_id")

    # Multiple background tasks (agent turns) and the main loop can all call emit()
    # concurrently; the lock serializes writes so JSON frames are never interleaved on
    # the wire.
    send_lock = asyncio.Lock()

    async def emit(event: dict[str, Any]) -> None:
        """Serialize and send a single WS event frame, swallowing send failures.

        Args:
            event (dict[str, Any]): The event payload to send; must be JSON-serializable
                (falling back to `str()` for any non-standard values via `default=str`).

        Returns:
            None:
        """
        async with send_lock:
            try:
                await ws.send_text(json.dumps(event, default=str))
            except Exception:
                # The client may have already disconnected; don't let a send failure
                # crash the background task or the receive loop.
                logger.warning("failed to send WS event; connection likely closed")

    await emit(
        {
            "type": "session_ready",
            "conversation_id": conversation_id,
            "curriculum_id": curriculum_id,
        }
    )

    try:
        while True:
            raw = await ws.receive_text()
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                # Malformed frame: report as recoverable so the client can keep the
                # connection open and simply resend correctly.
                await emit({"type": "error", "message": "invalid JSON frame", "recoverable": True})
                continue

            frame_type = frame.get("type")

            if frame_type == "ping":
                await emit({"type": "pong"})
                continue

            if frame_type == "stop":
                # Signals the orchestrator's module-level cancel event for this
                # conversation; does not itself await/confirm the running turn has
                # stopped (that happens asynchronously inside run_turn).
                request_stop(conversation_id)
                continue

            if frame_type == "user_message":
                content = frame.get("content", "")
                if not content or not curriculum_id:
                    await emit(
                        {
                            "type": "error",
                            "message": "missing content or no curriculum associated with this conversation",
                            "recoverable": True,
                        }
                    )
                    continue
                # Fire-and-forget: run_turn streams its own events via emit() as it
                # progresses, so the caller doesn't need (and shouldn't await) its result
                # here — the receive loop must stay responsive to stop/ping frames.
                asyncio.create_task(
                    _run_turn_safely(
                        orchestrator,
                        conversation_id=conversation_id,
                        curriculum_id=curriculum_id,
                        owner_uid=uid,
                        user_input=content,
                        emit=emit,
                    )
                )
                continue

            if frame_type == "plan_decision":
                if not curriculum_id:
                    await emit({"type": "error", "message": "no curriculum for this conversation", "recoverable": True})
                    continue
                # Client's approve/modify response to a paused propose_task_plan HITL
                # checkpoint; passed to run_turn as the "user_input" for this turn so the
                # orchestrator can resume the paused ReAct loop.
                decision = PlanDecision(decision=frame.get("decision", "approve"), feedback=frame.get("feedback"))
                asyncio.create_task(
                    _run_turn_safely(
                        orchestrator,
                        conversation_id=conversation_id,
                        curriculum_id=curriculum_id,
                        owner_uid=uid,
                        user_input=decision,
                        emit=emit,
                    )
                )
                continue

            await emit({"type": "error", "message": f"unknown frame type: {frame_type}", "recoverable": True})

    except WebSocketDisconnect:
        logger.info("ws client disconnected", extra={"extra_fields": {"conversation_id": conversation_id}})


async def _run_turn_safely(orchestrator: Orchestrator, **kwargs: Any) -> None:
    """Wrap orchestrator.run_turn so a failure in the background task doesn't go silent.

    Since `run_turn` is launched via `asyncio.create_task` rather than awaited directly,
    an unhandled exception inside it would otherwise only surface as an "exception never
    retrieved" warning when the task is garbage collected. This wrapper ensures such
    failures are logged immediately with the conversation id for debugging.

    Args:
        orchestrator (Orchestrator): The orchestrator instance to run the turn on.
        **kwargs (Any): Forwarded directly to `orchestrator.run_turn` (conversation_id,
            curriculum_id, owner_uid, user_input, emit).

    Returns:
        None:
    """
    try:
        await orchestrator.run_turn(**kwargs)
    except Exception:
        logger.exception(
            "background agent turn failed",
            extra={"extra_fields": {"conversation_id": kwargs.get("conversation_id")}},
        )
