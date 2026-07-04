"""Tool base class, execution context, and shared error type.

Every concrete tool subclasses `Tool`, defines a pydantic input model, and implements
`execute`. Tool errors are caught by the registry and returned as `{"error": "..."}`
observations — they must never raise out of `ToolRegistry.execute` and crash the
orchestrator loop (see spec 02 §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from app.core.config import Settings
from app.services.llm.base import LLMProvider
from app.services.search.base import SearchProvider


@dataclass(slots=True)
class AgentContext:
    """Everything a tool needs to act on behalf of the current agent run."""

    curriculum_id: str
    conversation_id: str
    owner_uid: str
    settings: Settings
    llm: LLMProvider
    small_llm: LLMProvider
    search: SearchProvider
    phase: str = "intake"

    # Populated by the orchestrator when a WS emitter is available; tools that need to
    # emit events directly (rare — most emission happens in the orchestrator loop after
    # a tool call completes) can use this. Optional so tools are unit-testable headless.
    emit: Any = None


class ToolExecutionError(Exception):
    """Raised by a tool's execute() to signal a handled, user-facing error condition.

    The registry converts this (and any other exception) into a structured
    {"error": "..."} observation rather than letting it propagate.
    """


class ToolProtocol(Protocol):
    name: str
    description: str
    input_model: type[BaseModel]

    async def execute(self, input: BaseModel, ctx: AgentContext) -> dict[str, Any]: ...


class Tool:
    """Base class for all agent tools."""

    name: str = ""
    description: str = ""
    input_model: type[BaseModel] = BaseModel

    async def execute(self, input: BaseModel, ctx: AgentContext) -> dict[str, Any]:
        raise NotImplementedError

    def json_schema(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        # Providers expect a flat JSON schema without pydantic's $defs indirection ideally,
        # but both our OpenAI and Gemini adapters handle nested schemas fine, so we pass
        # through as-is with defs inlined where pydantic already does so for simple models.
        schema.pop("title", None)
        return schema
