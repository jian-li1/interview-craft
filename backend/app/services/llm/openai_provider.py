"""OpenAI-compatible LLM provider.

Also serves llama.cpp servers (or any other OpenAI-compatible endpoint) when
`OPENAI_BASE_URL` is set: the OpenAI SDK is pointed at that base URL, and if no API key
is configured a harmless placeholder ("not-needed") is used since local servers usually
don't check it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.core.logging import get_logger
from app.services.llm.base import (
    ChatMessage,
    Done,
    LLMEvent,
    TextDelta,
    ToolCallDelta,
    ToolSpec,
)

logger = get_logger(__name__)


def _to_openai_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Translate provider-neutral ChatMessage objects into the OpenAI chat message shape.

    Args:
        messages (list[ChatMessage]): The provider-neutral conversation history.

    Returns:
        list[dict[str, Any]]: Messages in the dict shape expected by
            `openai.chat.completions.create(messages=...)`.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        entry: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.name:
            entry["name"] = m.name
        if m.tool_call_id:
            entry["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            entry["tool_calls"] = m.tool_calls
            # OpenAI requires content to be None (not "") when tool_calls is set on assistant msgs
            if not entry["content"]:
                entry["content"] = None
        out.append(entry)
    return out


def _to_openai_tools(tools: list[ToolSpec] | None) -> list[dict[str, Any]] | None:
    """Translate provider-neutral ToolSpec objects into OpenAI's function-tool shape.

    Args:
        tools (list[ToolSpec] | None): The provider-neutral tool definitions, or None.

    Returns:
        list[dict[str, Any]] | None: Tools in the `{"type": "function", "function": ...}`
            shape expected by the OpenAI SDK, or None if `tools` was empty/None.
    """
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


class OpenAIProvider:
    """Implements LLMProvider using the openai Python SDK's async client."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        small_model: str,
        base_url: str | None = None,
        max_output_tokens: int = 8192,
        request_timeout_seconds: float = 120.0,
    ) -> None:
        """Initialize the provider's async OpenAI SDK client.

        Args:
            api_key (str | None): The OpenAI API key, or None when targeting a local
                OpenAI-compatible server (e.g. llama.cpp) that doesn't check the key.
            model (str): The main model name/id to use for regular completions.
            small_model (str): The cheaper/faster model name/id to use when `small=True`
                (e.g. for summarization).
            base_url (str | None): An alternate OpenAI-compatible base URL (set for the
                "llamacpp" provider); None uses OpenAI's default endpoint.
            max_output_tokens (int): The `max_tokens` cap applied to every completion
                request, to bound cost/latency.
            request_timeout_seconds (float): Read timeout (seconds) for the HTTP client;
                connect/write/pool timeouts are set to shorter fixed values.

        Raises:
            ValueError: If no API key is available and `base_url` is not set (i.e. this
                isn't a local server that tolerates a placeholder key).
        """
        resolved_key = api_key or ("not-needed" if base_url else None)
        if not resolved_key:
            raise ValueError("OPENAI_API_KEY is required unless OPENAI_BASE_URL is set")
        timeout = httpx.Timeout(
            connect=10.0, read=request_timeout_seconds, write=30.0, pool=10.0
        )
        self._client = AsyncOpenAI(api_key=resolved_key, base_url=base_url, timeout=timeout)
        self._model = model
        self._small_model = small_model
        self._max_output_tokens = max_output_tokens

    def _model_for(self, small: bool) -> str:
        """Select the main or small model name based on the `small` flag.

        Args:
            small (bool): Whether to use the small/cheap model instead of the main one.

        Returns:
            str: The resolved model name/id to pass to the OpenAI SDK.
        """
        return self._small_model if small else self._model

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        small: bool = False,
    ) -> AsyncIterator[LLMEvent]:
        """Stream a chat completion from the OpenAI-compatible API.

        Args:
            messages (list[ChatMessage]): The conversation history to send.
            tools (list[ToolSpec] | None): Tool definitions the model may call, or None.
            small (bool): If True, use the small/cheap model instead of the main one.

        Yields:
            LLMEvent: `TextDelta` for each streamed text chunk, `ToolCallDelta` for each
                fully-assembled tool call (tool call argument fragments are accumulated
                across chunks and only emitted once complete), and finally one `Done`
                carrying the stream's finish reason.
        """
        model = self._model_for(small)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": _to_openai_messages(messages),
            "stream": True,
            "max_tokens": self._max_output_tokens,
        }
        openai_tools = _to_openai_tools(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        stream = await self._client.chat.completions.create(**kwargs)

        # Accumulate tool call fragments keyed by index until each is complete.
        pending_calls: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None

        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if choice.finish_reason:
                finish_reason = choice.finish_reason

            if delta and delta.content:
                yield TextDelta(text=delta.content)

            if delta and delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    entry = pending_calls.setdefault(idx, {"id": None, "name": None, "arguments": ""})
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            entry["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            entry["arguments"] += tc_delta.function.arguments

        for entry in pending_calls.values():
            try:
                args = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except json.JSONDecodeError:
                logger.warning("failed to parse tool call arguments as JSON; using empty dict")
                args = {}
            yield ToolCallDelta(id=entry["id"] or "", name=entry["name"] or "", arguments=args)

        yield Done(finish_reason=finish_reason)

    async def complete(self, messages: list[ChatMessage], small: bool = False) -> str:
        """Perform a non-streaming chat completion.

        Args:
            messages (list[ChatMessage]): The conversation history to send.
            small (bool): If True, use the small/cheap model instead of the main one.

        Returns:
            str: The complete text of the model's response (empty string if the model
                returned no content).
        """
        model = self._model_for(small)
        response = await self._client.chat.completions.create(
            model=model,
            messages=_to_openai_messages(messages),
            stream=False,
            max_tokens=self._max_output_tokens,
        )
        choice = response.choices[0]
        return choice.message.content or ""
