"""Conversation + message models (mirrors `conversations/{convId}` collection)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import Field

from app.models.common import ApiModel

Role = Literal["user", "assistant", "system"]
ToolCallStatus = Literal["ok", "error"]


class ToolCallRecord(ApiModel):
    """Record of a single agent tool invocation, embedded in a `Message`.

    Attributes:
        id (str): Unique id of this tool call within the conversation.
        name (str): Name of the tool that was invoked.
        input (dict[str, Any]): Arguments passed to the tool.
        output_preview (str): Truncated/summarized tool output for display purposes.
        status (ToolCallStatus): Whether the tool call succeeded ("ok") or failed
            ("error"); per `ToolRegistry.execute`, tool errors never raise and are
            instead surfaced via this status field.
    """

    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output_preview: str = ""
    status: ToolCallStatus = "ok"


class Message(ApiModel):
    """A single chat message, mirroring a doc in `conversations/{convId}/messages`.

    Attributes:
        id (str): Unique message id.
        role (Role): Author of the message ("user", "assistant", or "system").
        content (str): User-facing text content (reasoning is stored separately).
        reasoning (str | None): Extracted `<thinking>...</thinking>` reasoning text for
            assistant messages, split out from `content` by the streaming layer.
        tool_calls (list[ToolCallRecord]): Tool invocations made while producing this
            message, if any.
        created_at (dt.datetime): Timestamp the message was created.
        seq (int): Monotonically increasing sequence number within the conversation,
            used for ordering.
    """

    id: str
    role: Role
    content: str
    reasoning: str | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    created_at: dt.datetime
    seq: int


class MessageOut(Message):
    """Public-facing message shape returned by conversation endpoints.

    Currently identical to `Message`; kept as a distinct type so the response contract
    can diverge from the internal storage shape without touching call sites.
    """

    pass


class Conversation(ApiModel):
    """Full internal representation of a `conversations/{convId}` Firestore document.

    Attributes:
        id (str): Conversation id (Firestore doc id).
        owner_uid (str): uid of the user who owns this conversation.
        curriculum_id (str | None): Id of the curriculum this conversation is building,
            once one has been created.
        title (str): Display title for the conversation.
        summary (str | None): Rolling compaction summary produced by the small model
            once the conversation exceeds the compaction token threshold.
        compacted_through (str | None): Id/marker of the last message folded into
            `summary`, so compaction can resume incrementally.
        token_estimate (int): Running estimate of the conversation's token usage, used
            to decide when to trigger compaction.
        created_at (dt.datetime): Timestamp the conversation was created.
        updated_at (dt.datetime): Timestamp of the most recent update.
    """

    id: str
    owner_uid: str
    curriculum_id: str | None = None
    title: str
    summary: str | None = None
    compacted_through: str | None = None
    token_estimate: int = 0
    created_at: dt.datetime
    updated_at: dt.datetime


class ConversationSummary(ApiModel):
    """Lightweight conversation shape used for list views (e.g. sidebar history).

    Attributes:
        id (str): Conversation id.
        curriculum_id (str | None): Id of the associated curriculum, if any.
        title (str): Display title for the conversation.
        created_at (dt.datetime): Timestamp the conversation was created.
        updated_at (dt.datetime): Timestamp of the most recent update.
    """

    id: str
    curriculum_id: str | None = None
    title: str
    created_at: dt.datetime
    updated_at: dt.datetime


class NewConversationRequest(ApiModel):
    """Request body for creating a new conversation.

    Attributes:
        curriculum_prompt (str | None): Optional initial user prompt describing the
            curriculum to generate; if omitted the conversation starts empty.
    """

    curriculum_prompt: str | None = None


class NewConversationResponse(ApiModel):
    """Response body after creating a new conversation.

    Attributes:
        conversation_id (str): Id of the newly created conversation.
    """

    conversation_id: str
