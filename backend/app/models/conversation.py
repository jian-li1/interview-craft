"""Conversation + message models (mirrors `conversations/{convId}` collection)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import Field

from app.models.common import ApiModel

Role = Literal["user", "assistant"]
ToolCallStatus = Literal["ok", "error"]


class ToolCallRecord(ApiModel):
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output_preview: str = ""
    status: ToolCallStatus = "ok"


class Message(ApiModel):
    id: str
    role: Role
    content: str
    reasoning: str | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    created_at: dt.datetime
    seq: int


class MessageOut(Message):
    pass


class Conversation(ApiModel):
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
    id: str
    curriculum_id: str | None = None
    title: str
    created_at: dt.datetime
    updated_at: dt.datetime


class NewConversationRequest(ApiModel):
    curriculum_prompt: str | None = None


class NewConversationResponse(ApiModel):
    conversation_id: str
