"""Gemini LLM provider using the google-genai SDK.

Translates the provider-neutral ChatMessage/ToolSpec shapes into Gemini's `contents` +
`Tool(function_declarations=...)` format, and streams responses back as the same
TextDelta/ToolCallDelta/Done events the OpenAI provider produces.
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
    """Gemini takes system instructions separately from the conversation `contents`."""
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
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required to use the gemini provider")
        http_options = genai_types.HttpOptions(timeout=int(request_timeout_seconds * 1000))
        self._client = genai.Client(api_key=api_key, http_options=http_options)
        self._model = model
        self._small_model = small_model
        self._max_output_tokens = max_output_tokens

    def _model_for(self, small: bool) -> str:
        return self._small_model if small else self._model

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        small: bool = False,
    ) -> AsyncIterator[LLMEvent]:
        model = self._model_for(small)
        system_instruction, contents = _split_system_and_contents(messages)
        gemini_tools = _to_gemini_tools(tools)

        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=gemini_tools,
            max_output_tokens=self._max_output_tokens,
        )

        stream = await self._client.aio.models.generate_content_stream(
            model=model, contents=contents, config=config
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
                if part.text:
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
