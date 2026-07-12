"""Conversations routes: list, create (starts a new curriculum), message history."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
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
from app.services.llm.factory import resolve_model
from app.services.search.factory import resolve_search_provider

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(user: CurrentUser = Depends(get_current_user)) -> list[ConversationSummary]:
    """List all conversations owned by the current user.

    Args:
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.

    Returns:
        list[ConversationSummary]: Summary representations of every conversation owned
            by the user.
    """
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
    body: NewConversationRequest,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> NewConversationResponse:
    """Start a new conversation. If a curriculum_prompt is given, also creates a new
    curriculum doc (status=researching) linked to this conversation, ready for the agent
    to pick up on the first user_message WS frame.

    Requires the `X-Requested-With` CSRF header (enforced by the router-level
    dependency) and is subject to the shared agent rate limit since it can kick off an
    agent run. When a curriculum is created, its initial agent state is seeded here
    (phase="intake", empty task queue) so the orchestrator has a well-formed starting
    point on the first WS turn.

    Args:
        body (NewConversationRequest): Optionally includes `curriculum_prompt`, the
            user's initial prompt describing what curriculum to build, plus optional
            `selected_model`/`search_provider` chip selections from the dashboard
            prompt box.
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.
        settings (Settings): Application settings, used to resolve any requested
            model/search-provider selection.

    Returns:
        NewConversationResponse: The id of the newly created conversation.

    Raises:
        HTTPException: 429 if the caller has exceeded the agent rate limit (raised by
            `enforce_rate_limit`).
    """
    enforce_rate_limit(user)

    title = (body.curriculum_prompt or "New conversation")[:80]

    # Only resolve/persist a selection when the client actually sent one — a null body
    # value must stay null on the doc (falls back to server defaults), not get resolved
    # to the default and persisted as an explicit choice.
    resolved_model = resolve_model(body.selected_model, settings)[1] if body.selected_model is not None else None
    resolved_search = (
        resolve_search_provider(body.search_provider, settings) if body.search_provider is not None else None
    )

    conversation = fs.create_conversation(
        user.uid,
        title=title,
        curriculum_id=None,
        selected_model=resolved_model,
        search_provider=resolved_search,
    )

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
    """Fetch the full message history for a conversation, for rendering on load.

    Args:
        conversation_id (str): The Firestore document id of the conversation whose
            messages are being fetched.
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`.

    Returns:
        list[MessageOut]: The full ordered message history for the conversation.

    Raises:
        HTTPException: 404 if the conversation does not exist or is not owned by `user`
            (raised by `get_owned_conversation`).
    """
    get_owned_conversation(conversation_id, user)
    messages = fs.list_messages(conversation_id)
    return [MessageOut(**m) for m in messages]
