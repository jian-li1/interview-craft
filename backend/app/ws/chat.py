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
    """Resolve the uid for a WS connection from the cookie or `?token=` fallback."""
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
    """Main chat WebSocket: streams agent turns and accepts client control frames."""
    uid = await _authenticate_ws(ws)
    if uid is None:
        await ws.close(code=WS_CODE_UNAUTHORIZED)
        return

    conversation = fs.get_conversation(conversation_id)
    if conversation is None:
        await ws.close(code=WS_CODE_UNAUTHORIZED)
        return
    if conversation["owner_uid"] != uid:
        await ws.close(code=WS_CODE_FORBIDDEN)
        return

    await ws.accept()

    settings = get_settings()
    orchestrator = Orchestrator(settings)
    curriculum_id = conversation.get("curriculum_id")

    send_lock = asyncio.Lock()

    async def emit(event: dict[str, Any]) -> None:
        async with send_lock:
            try:
                await ws.send_text(json.dumps(event, default=str))
            except Exception:
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
                await emit({"type": "error", "message": "invalid JSON frame", "recoverable": True})
                continue

            frame_type = frame.get("type")

            if frame_type == "ping":
                await emit({"type": "pong"})
                continue

            if frame_type == "stop":
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
    """Wrap orchestrator.run_turn so a failure in the background task doesn't go silent."""
    try:
        await orchestrator.run_turn(**kwargs)
    except Exception:
        logger.exception(
            "background agent turn failed",
            extra={"extra_fields": {"conversation_id": kwargs.get("conversation_id")}},
        )
