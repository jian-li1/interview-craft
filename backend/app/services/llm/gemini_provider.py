"""Gemini LLM provider using the google-genai SDK.

Translates the provider-neutral ChatMessage/ToolSpec shapes into Gemini's `contents` +
`Tool(function_declarations=...)` format, and streams responses back as the same
ReasoningDelta/TextDelta/ToolCallDelta/Done events the OpenAI provider produces.
`chat_stream` requests thought summaries (`ThinkingConfig(include_thoughts=True)`) so
thinking-capable models (e.g. gemini-2.5-*) surface native reasoning as ReasoningDelta;
non-thinking models reject the config, so that request is retried once without it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import types as genai_types

from app.core.logging import get_logger
from app.services.llm.base import (
    ChatMessage,
    Done,
    LLMEvent,
    ReasoningDelta,
    TextDelta,
    ToolCallDelta,
    ToolSpec,
)

logger = get_logger(__name__)

_JSON_SCHEMA_TYPE_MAP = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}


def _translate_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively translate a JSON-schema dict into Gemini's Schema dict shape."""
    out: dict[str, Any] = {}
    json_type = schema.get("type", "object")
    out["type"] = _JSON_SCHEMA_TYPE_MAP.get(json_type, "STRING")
    if "description" in schema:
        out["description"] = schema["description"]
    if "enum" in schema:
        out["enum"] = schema["enum"]
    if json_type == "object":
        props = schema.get("properties", {})
        out["properties"] = {k: _translate_schema(v) for k, v in props.items()}
        if schema.get("required"):
            out["required"] = schema["required"]
    if json_type == "array" and "items" in schema:
        out["items"] = _translate_schema(schema["items"])
    return out


def _to_gemini_tools(tools: list[ToolSpec] | None) -> list[genai_types.Tool] | None:
    """Translate provider-neutral ToolSpec objects into Gemini's Tool/FunctionDeclaration shape.

    Args:
        tools (list[ToolSpec] | None): The provider-neutral tool definitions, or None.

    Returns:
        list[genai_types.Tool] | None: A single-element list containing one `Tool` whose
            `function_declarations` mirror `tools`, translating each JSON-schema
            parameters dict via `_translate_schema`; None if `tools` was empty/None.
    """
    if not tools:
        return None
    declarations = [
        genai_types.FunctionDeclaration(
            name=t.name,
            description=t.description,
            parameters=_translate_schema(t.parameters),
        )
        for t in tools
    ]
    return [genai_types.Tool(function_declarations=declarations)]


def _split_system_and_contents(
    messages: list[ChatMessage],
) -> tuple[str | None, list[genai_types.Content]]:
    """Gemini takes system instructions separately from the conversation `contents`.

    Splits the provider-neutral message list into a single concatenated system
    instruction string and a list of Gemini `Content` objects for the remaining
    turns, remapping roles along the way: "assistant" -> "model", "tool" -> "function"
    (wrapped as a function response part), and everything else -> "user".

    Args:
        messages (list[ChatMessage]): The provider-neutral conversation history,
            potentially interleaving system, user, assistant, and tool messages.

    Returns:
        tuple[str | None, list[genai_types.Content]]: A tuple of
            (concatenated system instruction, or None if there were no system messages;
            the ordered list of Gemini `Content` turns for the rest of the conversation).
    """
    system_parts: list[str] = []
    contents: list[genai_types.Content] = []

    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
            continue
        if m.role == "tool":
            contents.append(
                genai_types.Content(
                    role="function",
                    parts=[
                        genai_types.Part.from_function_response(
                            name=m.name or "tool",
                            response={"result": m.content},
                        )
                    ],
                )
            )
            continue

        gemini_role = "model" if m.role == "assistant" else "user"
        parts: list[genai_types.Part] = []
        if m.content:
            parts.append(genai_types.Part.from_text(text=m.content))
        if m.tool_calls:
            for tc in m.tool_calls:
                fn = tc.get("function", {})
                parts.append(
                    genai_types.Part.from_function_call(
                        name=fn.get("name", ""),
                        args=fn.get("arguments", {}),
                    )
                )
        if parts:
            contents.append(genai_types.Content(role=gemini_role, parts=parts))

    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, contents


class GeminiProvider:
    """Implements LLMProvider using google-genai's async client."""

    def __init__(
        self,
        api_key: str,
        model: str,
        small_model: str,
        max_output_tokens: int = 8192,
        request_timeout_seconds: float = 120.0,
    ) -> None:
        """Initialize the provider's async google-genai SDK client.

        Args:
            api_key (str): The Gemini API key; required (empty string is treated as
                "missing" and raises).
            model (str): The main model name/id to use for regular completions.
            small_model (str): The cheaper/faster model name/id to use when `small=True`
                (e.g. for summarization).
            max_output_tokens (int): The `max_output_tokens` cap applied to every
                generation request, to bound cost/latency.
            request_timeout_seconds (float): Request timeout in seconds, converted to
                milliseconds for the underlying `HttpOptions`.

        Raises:
            ValueError: If `api_key` is falsy.
        """
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required to use the gemini provider")
        http_options = genai_types.HttpOptions(timeout=int(request_timeout_seconds * 1000))
        self._client = genai.Client(api_key=api_key, http_options=http_options)
        self._model = model
        self._small_model = small_model
        self._max_output_tokens = max_output_tokens

    def _model_for(self, small: bool) -> str:
        """Select the main or small model name based on the `small` flag.

        Args:
            small (bool): Whether to use the small/cheap model instead of the main one.

        Returns:
            str: The resolved model name/id to pass to the google-genai SDK.
        """
        return self._small_model if small else self._model

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        small: bool = False,
    ) -> AsyncIterator[LLMEvent]:
        """Stream a chat completion from the Gemini API.

        Args:
            messages (list[ChatMessage]): The conversation history to send.
            tools (list[ToolSpec] | None): Tool definitions the model may call, or None.
            small (bool): If True, use the small/cheap model instead of the main one.

        Yields:
            LLMEvent: `ReasoningDelta` for each streamed thought-summary part (`part.thought
                == True`, only produced by thinking-capable models with
                `include_thoughts` set), `TextDelta` for each streamed answer text part,
                `ToolCallDelta` for each function call part (Gemini emits complete
                function calls per chunk, so no fragment accumulation is needed, unlike
                the OpenAI provider; each is assigned a synthetic sequential id since
                Gemini doesn't provide one), and finally one `Done` carrying the stream's
                finish reason.
        """
        model = self._model_for(small)
        system_instruction, contents = _split_system_and_contents(messages)
        gemini_tools = _to_gemini_tools(tools)

        # Request thought summaries so thinking-capable models stream native reasoning
        # as ReasoningDelta; non-thinking models reject this field (see the retry below).
        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=gemini_tools,
            max_output_tokens=self._max_output_tokens,
            thinking_config=genai_types.ThinkingConfig(include_thoughts=True),
        )

        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=model, contents=contents, config=config
            )
        except Exception:
            # Non-thinking models (e.g. gemini-2.0-*) reject thinking_config with an
            # INVALID_ARGUMENT error — retry once without it so those models still work.
            logger.warning(
                "model rejected thinking_config; retrying without thought summaries",
                extra={"extra_fields": {"model": model}},
            )
            fallback_config = genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=gemini_tools,
                max_output_tokens=self._max_output_tokens,
            )
            stream = await self._client.aio.models.generate_content_stream(
                model=model, contents=contents, config=fallback_config
            )

        finish_reason: str | None = None
        call_counter = 0
        async for chunk in stream:
            if not chunk.candidates:
                continue
            candidate = chunk.candidates[0]
            if candidate.finish_reason:
                finish_reason = str(candidate.finish_reason)
            if not candidate.content or not candidate.content.parts:
                continue
            for part in candidate.content.parts:
                # Thought-summary parts carry the model's native reasoning, not the
                # user-visible answer — route them separately from plain text parts.
                if part.thought and part.text:
                    yield ReasoningDelta(text=part.text)
                elif part.text:
                    yield TextDelta(text=part.text)
                if part.function_call:
                    call_counter += 1
                    yield ToolCallDelta(
                        id=f"gemini-call-{call_counter}",
                        name=part.function_call.name or "",
                        arguments=dict(part.function_call.args or {}),
                    )

        yield Done(finish_reason=finish_reason)

    async def complete(self, messages: list[ChatMessage], small: bool = False) -> str:
        """Perform a non-streaming chat completion.

        Args:
            messages (list[ChatMessage]): The conversation history to send.
            small (bool): If True, use the small/cheap model instead of the main one.

        Returns:
            str: The complete text of the model's response (empty string if the model
                returned no text).
        """
        model = self._model_for(small)
        system_instruction, contents = _split_system_and_contents(messages)
        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=self._max_output_tokens,
        )
        response = await self._client.aio.models.generate_content(
            model=model, contents=contents, config=config
        )
        return response.text or ""
