"""Provider-agnostic LLM abstraction.

All providers (OpenAI — including any OpenAI-compatible endpoint via `OPENAI_BASE_URL` —
and Gemini) implement the same `LLMProvider` protocol and emit the same stream of
`LLMEvent`s, so the orchestrator never has to branch on which provider is active.
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
    """A chunk of user-visible answer text as it streams from the model.

    Reasoning arrives separately as `ReasoningDelta` — this is answer text only.
    """

    text: str


@dataclass(slots=True)
class ReasoningDelta:
    """A chunk of the model's native reasoning/thinking text as it streams.

    Surfaced by the provider (OpenAI-compatible `reasoning_content`/`reasoning` delta
    fields, or Gemini thought-summary parts) and emitted to the client as `reasoning_delta`.
    """

    text: str


@dataclass(slots=True)
class Done:
    """Terminal event for a stream, carrying usage info if the provider reports it."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None


LLMEvent = TextDelta | ReasoningDelta | ToolCallDelta | Done


@dataclass(slots=True)
class CompletionResult:
    """The fully-assembled result of a non-streaming completion (text plus any tool calls).

    Attributes:
        text (str): The complete text of the model's response.
        tool_calls (list[ToolCallDelta]): Any tool calls the model requested, fully
            assembled (empty if the model returned plain text only).
    """

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
        """Stream a chat completion. Yields TextDelta/ToolCallDelta events, ends with Done.

        Args:
            messages (list[ChatMessage]): The conversation history to send to the model,
                in provider-neutral form.
            tools (list[ToolSpec] | None): Tool definitions the model may call, or None
                to disable tool use for this request.
            small (bool): If True, route the request to the provider's cheaper/faster
                "small" model (used for summarization and other lightweight generations)
                instead of the main model.

        Yields:
            LLMEvent: A sequence of `ReasoningDelta` (native reasoning/thinking text,
                when the provider surfaces it), `TextDelta` (streamed answer text
                chunks), and/or `ToolCallDelta` (fully-assembled tool calls) events,
                terminated by exactly one `Done` event carrying usage/finish-reason info.
        """
        ...

    async def complete(self, messages: list[ChatMessage], small: bool = False) -> str:
        """Non-streaming helper used for small, one-shot generations (e.g. summarization).

        Args:
            messages (list[ChatMessage]): The conversation history to send to the model,
                in provider-neutral form.
            small (bool): If True, route the request to the provider's cheaper/faster
                "small" model instead of the main model.

        Returns:
            str: The complete text of the model's response.
        """
        ...
