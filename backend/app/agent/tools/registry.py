"""ToolRegistry: holds all tool instances, filters by phase, executes and converts errors.

Per spec 02 §4: "A ToolRegistry exposes provider-formatted specs filtered by phase
(research tools hidden during writing-only refinements, etc — keep filtering simple: a
phase→allowed-tools map)."
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from app.agent.tools.base import AgentContext, Tool, ToolExecutionError
from app.agent.tools.control import CompletePhaseTool, RequestUserInputTool, UpdateScratchpadTool
from app.agent.tools.curriculum import (
    ListCurriculumStructureTool,
    ReadSectionTool,
    SetModuleStatusTool,
    UpdateSectionTool,
    WriteCurriculumOverviewTool,
    WriteSectionTool,
)
from app.agent.tools.planning import GetTaskPlanTool, ProposeTaskPlanTool
from app.agent.tools.research import (
    FetchUrlTool,
    ListResearchNotesTool,
    SaveResearchNoteTool,
    SearchResearchNotesTool,
    WebSearchTool,
)
from app.agent.tools.user_memory import GetUserProfileTool
from app.core.logging import get_logger
from app.services.llm.base import ToolSpec

logger = get_logger(__name__)


class ToolResult:
    """Result of executing a tool call, including timing and status for WS reporting."""

    __slots__ = ("output", "status", "elapsed_ms")

    def __init__(self, output: dict[str, Any], status: str, elapsed_ms: int) -> None:
        self.output = output
        self.status = status
        self.elapsed_ms = elapsed_ms


# Phase -> allowed tool names. Tools not listed for a phase are hidden from the LLM
# entirely (not offered as a function-calling option) for that phase.
_ALWAYS_AVAILABLE = [
    "get_user_profile",
    "update_scratchpad",
    "complete_phase",
    "request_user_input",
]

_PHASE_TOOLS: dict[str, list[str]] = {
    "intake": [*_ALWAYS_AVAILABLE],
    "deep_research": [
        *_ALWAYS_AVAILABLE,
        "web_search",
        "fetch_url",
        "save_research_note",
        "search_research_notes",
        "list_research_notes",
    ],
    "outline_planning": [
        *_ALWAYS_AVAILABLE,
        "search_research_notes",
        "list_research_notes",
        "propose_task_plan",
        "get_task_plan",
    ],
    "awaiting_approval": [*_ALWAYS_AVAILABLE, "get_task_plan"],
    "writing": [
        *_ALWAYS_AVAILABLE,
        "search_research_notes",
        "list_research_notes",
        "web_search",
        "fetch_url",
        "save_research_note",
        "get_task_plan",
        "list_curriculum_structure",
        "write_section",
        "write_curriculum_overview",
        "set_module_status",
    ],
    "review": [
        *_ALWAYS_AVAILABLE,
        "list_curriculum_structure",
        "read_section",
        "write_section",
        "write_curriculum_overview",
        "set_module_status",
        "search_research_notes",
    ],
    "ready": [
        *_ALWAYS_AVAILABLE,
        "list_curriculum_structure",
        "read_section",
        "update_section",
        "write_section",
        "search_research_notes",
        "list_research_notes",
        "web_search",
        "fetch_url",
        "save_research_note",
    ],
    "refinement": [
        *_ALWAYS_AVAILABLE,
        "list_curriculum_structure",
        "read_section",
        "update_section",
        "write_section",
        "search_research_notes",
        "list_research_notes",
        "web_search",
        "fetch_url",
        "save_research_note",
    ],
}

# Tool names that pause the ReAct loop for human-in-the-loop decisions.
HITL_GATE_TOOLS = {"propose_task_plan", "request_user_input"}


class ToolRegistry:
    """Holds all tool instances and provides phase-filtered, provider-formatted access."""

    def __init__(self) -> None:
        tool_instances: list[Tool] = [
            WebSearchTool(),
            FetchUrlTool(),
            SaveResearchNoteTool(),
            SearchResearchNotesTool(),
            ListResearchNotesTool(),
            GetUserProfileTool(),
            ProposeTaskPlanTool(),
            GetTaskPlanTool(),
            ListCurriculumStructureTool(),
            WriteSectionTool(),
            ReadSectionTool(),
            UpdateSectionTool(),
            WriteCurriculumOverviewTool(),
            SetModuleStatusTool(),
            RequestUserInputTool(),
            UpdateScratchpadTool(),
            CompletePhaseTool(),
        ]
        self._tools: dict[str, Tool] = {t.name: t for t in tool_instances}

    def specs_for_phase(self, phase: str) -> list[ToolSpec]:
        """Return provider-neutral ToolSpecs for the tools allowed in `phase`."""
        allowed = _PHASE_TOOLS.get(phase, _ALWAYS_AVAILABLE)
        specs = []
        for name in allowed:
            tool = self._tools.get(name)
            if not tool:
                continue
            specs.append(
                ToolSpec(name=tool.name, description=tool.description, parameters=tool.json_schema())
            )
        return specs

    def is_hitl_gate(self, tool_name: str) -> bool:
        return tool_name in HITL_GATE_TOOLS

    async def execute(self, tool_name: str, raw_input: dict[str, Any], ctx: AgentContext) -> ToolResult:
        """Execute a tool call by name, returning a ToolResult.

        Never raises: validation errors, execution errors, and unknown-tool lookups are
        all captured and converted into {"error": "..."} observations so the ReAct loop
        never crashes on a bad or failing tool call (spec 02 §3).
        """
        start = time.monotonic()
        tool = self._tools.get(tool_name)
        if tool is None:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return ToolResult({"error": f"unknown tool: {tool_name!r}"}, "error", elapsed_ms)

        try:
            parsed_input = tool.input_model.model_validate(raw_input)
        except ValidationError as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "tool input validation failed",
                extra={"extra_fields": {"tool": tool_name, "error": str(exc)}},
            )
            return ToolResult({"error": f"invalid input for {tool_name}: {exc}"}, "error", elapsed_ms)

        try:
            output = await tool.execute(parsed_input, ctx)
        except ToolExecutionError as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return ToolResult({"error": str(exc)}, "error", elapsed_ms)
        except Exception as exc:  # tools must never crash the orchestrator loop
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.exception(
                "tool execution raised an unhandled exception",
                extra={"extra_fields": {"tool": tool_name}},
            )
            return ToolResult({"error": f"tool {tool_name} failed: {exc}"}, "error", elapsed_ms)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        status = "error" if isinstance(output, dict) and "error" in output else "ok"
        return ToolResult(output, status, elapsed_ms)
