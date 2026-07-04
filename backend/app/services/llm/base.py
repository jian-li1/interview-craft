"""Provider-agnostic LLM abstraction.

All providers (OpenAI, Gemini, llama.cpp via OpenAI-compatible endpoint) implement the
same `LLMProvider` protocol and emit the same stream of `LLMEvent`s, so the orchestrator
never has to branch on which provider is active.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class ChatMessage:
    """A single message in the conversation sent to the LLM.

    `tool_call_id` / `name` are used for role="tool" messages (tool results fed back).
    `tool_calls` is used for role="assistant" messages that requested tool calls.
    """

    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass(slots=True)
class ToolSpec:
    """A tool definition in a provider-neutral shape (JSON schema based)."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(slots=True)
class ToolCallDelta:
    """A complete tool call assembled by the provider implementation.

    Providers stream partial tool-call fragments internally but only emit this event once
    a tool call is fully assembled (name + complete JSON arguments), to keep the
    orchestrator simple.
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class TextDelta:
    """A chunk of raw text as it streams from the model (before thinking/text split)."""

    text: str


@dataclass(slots=True)
class Done:
    """Terminal event for a stream, carrying usage info if the provider reports it."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None


LLMEvent = TextDelta | ToolCallDelta | Done


@dataclass(slots=True)
class CompletionResult:
    text: str
    tool_calls: list[ToolCallDelta] = field(default_factory=list)


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol every LLM provider implementation must satisfy."""

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        small: bool = False,
    ) -> AsyncIterator[LLMEvent]:
        """Stream a chat completion. Yields TextDelta/ToolCallDelta events, ends with Done."""
        ...

    async def complete(self, messages: list[ChatMessage], small: bool = False) -> str:
        """Non-streaming helper used for small, one-shot generations (e.g. summarization)."""
        ...
