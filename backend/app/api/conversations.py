"""Conversations routes: list, create (starts a new curriculum), message history."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import (
    CurrentUser,
    enforce_rate_limit,
    get_current_user,
    get_owned_conversation,
    require_csrf_header,
)
from app.models.conversation import (
    ConversationSummary,
    MessageOut,
    NewConversationRequest,
    NewConversationResponse,
)
from app.services import firestore as fs

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(user: CurrentUser = Depends(get_current_user)) -> list[ConversationSummary]:
    """List all conversations owned by the current user."""
    items = fs.list_conversations(user.uid)
    return [
        ConversationSummary(
            id=i["id"],
            curriculum_id=i.get("curriculum_id"),
            title=i.get("title", ""),
            created_at=i["created_at"],
            updated_at=i["updated_at"],
        )
        for i in items
    ]


@router.post("", response_model=NewConversationResponse, dependencies=[Depends(require_csrf_header)])
async def create_conversation(
    body: NewConversationRequest, user: CurrentUser = Depends(get_current_user)
) -> NewConversationResponse:
    """Start a new conversation. If a curriculum_prompt is given, also creates a new
    curriculum doc (status=researching) linked to this conversation, ready for the agent
    to pick up on the first user_message WS frame.
    """
    enforce_rate_limit(user)

    title = (body.curriculum_prompt or "New conversation")[:80]
    conversation = fs.create_conversation(user.uid, title=title, curriculum_id=None)

    if body.curriculum_prompt:
        curriculum = fs.create_curriculum(
            owner_uid=user.uid,
            title=title,
            user_prompt=body.curriculum_prompt,
            conversation_id=conversation["id"],
        )
        fs.update_conversation(conversation["id"], {"curriculum_id": curriculum["id"]})
        fs.set_agent_state(
            curriculum["id"],
            {"phase": "intake", "task_queue": [], "current_task_id": None, "scratchpad": "", "iteration_count": 0},
        )

    return NewConversationResponse(conversation_id=conversation["id"])


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(
    conversation_id: str, user: CurrentUser = Depends(get_current_user)
) -> list[MessageOut]:
    """Fetch the full message history for a conversation, for rendering on load."""
    get_owned_conversation(conversation_id, user)
    messages = fs.list_messages(conversation_id)
    return [MessageOut(**m) for m in messages]
