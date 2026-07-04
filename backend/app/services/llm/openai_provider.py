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
    ) -> None:
        resolved_key = api_key or ("not-needed" if base_url else None)
        if not resolved_key:
            raise ValueError("OPENAI_API_KEY is required unless OPENAI_BASE_URL is set")
        self._client = AsyncOpenAI(api_key=resolved_key, base_url=base_url)
        self._model = model
        self._small_model = small_model

    def _model_for(self, small: bool) -> str:
        return self._small_model if small else self._model

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        small: bool = False,
    ) -> AsyncIterator[LLMEvent]:
        model = self._model_for(small)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": _to_openai_messages(messages),
            "stream": True,
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
        model = self._model_for(small)
        response = await self._client.chat.completions.create(
            model=model,
            messages=_to_openai_messages(messages),
            stream=False,
        )
        choice = response.choices[0]
        return choice.message.content or ""
