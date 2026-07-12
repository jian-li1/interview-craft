"""Tool base class, execution context, and shared error type.

Every concrete tool subclasses `Tool`, defines a pydantic input model, and implements
`execute`. Tool errors are caught by the registry and returned as `{"error": "..."}`
observations — they must never raise out of `ToolRegistry.execute` and crash the
orchestrator loop (see spec 02 §3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    # The single LLM provider for this run's selected model — no more "small model"
    # concept (compaction/profile synthesis now run on the same selected model too).
    llm: LLMProvider
    search: SearchProvider
    phase: str = "intake"

    # Populated by the orchestrator when a WS emitter is available; tools that need to
    # emit events directly (rare — most emission happens in the orchestrator loop after
    # a tool call completes) can use this. Optional so tools are unit-testable headless.
    emit: Any = None

    # In-run cache of fetched pages (url -> {title, content_markdown, content_truncated}),
    # shared across every iteration's AgentContext for one orchestrator run — lets
    # save_sources skip re-fetching a page fetch_url already pulled this run.
    page_cache: dict[str, dict[str, Any]] = field(default_factory=dict)


class ToolExecutionError(Exception):
    """Raised by a tool's execute() to signal a handled, user-facing error condition.

    The registry converts this (and any other exception) into a structured
    {"error": "..."} observation rather than letting it propagate.
    """


class ToolProtocol(Protocol):
    """Structural type describing the shape every concrete `Tool` subclass must satisfy.

    Not used for runtime isinstance checks (Tool subclasses satisfy it structurally) —
    documents the contract for static typing and for anyone implementing a new tool
    without subclassing `Tool` directly.

    Attributes:
        name (str): The tool's unique registration name (also the LLM-facing function
            name).
        description (str): The LLM-facing description of what the tool does and when to
            use it — part of the prompt, not documentation.
        input_model (type[BaseModel]): The pydantic model validating this tool's input.
    """

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
        """Execute the tool's action given validated input and the current agent context.

        Subclasses must override this. The base implementation always raises, so a
        `Tool` subclass that forgets to implement `execute` fails loudly rather than
        silently doing nothing.

        Args:
            input (BaseModel): The validated input, an instance of `self.input_model`.
            ctx (AgentContext): The current agent run's context (ids, providers, phase).

        Returns:
            dict[str, Any]: A JSON-serializable observation dict. Should contain
                `{"error": ...}` on failure rather than raising, per the tool-error
                contract (raising `ToolExecutionError` is also acceptable and is caught
                by the registry).

        Raises:
            NotImplementedError: Always, unless overridden by a subclass.
        """
        raise NotImplementedError

    def json_schema(self) -> dict[str, Any]:
        """Return the JSON schema for this tool's input, suitable for LLM function-calling specs.

        Returns:
            dict[str, Any]: The pydantic-generated JSON schema for `input_model`, with
                the `title` key stripped (providers don't need it and it adds noise to
                the function-calling spec).
        """
        schema = self.input_model.model_json_schema()
        # Providers expect a flat JSON schema without pydantic's $defs indirection ideally,
        # but both our OpenAI and Gemini adapters handle nested schemas fine, so we pass
        # through as-is with defs inlined where pydantic already does so for simple models.
        schema.pop("title", None)
        return schema
