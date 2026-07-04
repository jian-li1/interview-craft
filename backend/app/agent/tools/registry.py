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
    SetCurriculumTitleTool,
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
        """Store the tool's output dict alongside execution metadata.

        Args:
            output (dict[str, Any]): The tool's JSON-serializable observation, possibly
                still containing internal `_hitl_gate`/`_ws_event`/`_ws_events` keys that
                the orchestrator pops before building the client-visible preview.
            status (str): `"ok"` or `"error"`, derived from whether `output` contains an
                `"error"` key.
            elapsed_ms (int): Wall-clock milliseconds the execution took, for WS
                reporting/telemetry.
        """
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
    "set_curriculum_title",
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
        """Instantiate every known tool once and index them by name.

        The `tool_instances` list here is the single place new tools must be registered
        (per the "Adding a new tool" steps in `app/agent/CLAUDE.md`) — a tool class that
        exists but isn't listed here is never available to the agent.
        """
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
            SetCurriculumTitleTool(),
            SetModuleStatusTool(),
            RequestUserInputTool(),
            UpdateScratchpadTool(),
            CompletePhaseTool(),
        ]
        self._tools: dict[str, Tool] = {t.name: t for t in tool_instances}

    def specs_for_phase(self, phase: str) -> list[ToolSpec]:
        """Return provider-neutral ToolSpecs for the tools allowed in `phase`.

        Tools not listed for a phase are omitted entirely from the returned specs — the
        LLM never even sees them as function-calling options for that phase (see
        `_PHASE_TOOLS`). Falls back to `_ALWAYS_AVAILABLE` for any phase without an
        explicit entry.

        Args:
            phase (str): The current agent phase (e.g. "writing", "deep_research").

        Returns:
            list[ToolSpec]: One spec per allowed tool that's actually registered
                (silently skips names in `_PHASE_TOOLS` that have no matching instance).
        """
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
        """Check whether `tool_name` is a registry-level HITL gate tool (backstop check).

        This is a backstop alongside each gate tool's own `_hitl_gate: True` output flag
        — the orchestrator treats a step as gated if *either* signal fires, so a gate
        tool that forgets to set the flag on a given call still pauses the loop.

        Args:
            tool_name (str): The tool name to check.

        Returns:
            bool: True if `tool_name` is in `HITL_GATE_TOOLS`.
        """
        return tool_name in HITL_GATE_TOOLS

    async def execute(self, tool_name: str, raw_input: dict[str, Any], ctx: AgentContext) -> ToolResult:
        """Execute a tool call by name, returning a ToolResult.

        Never raises: validation errors, execution errors, and unknown-tool lookups are
        all captured and converted into {"error": "..."} observations so the ReAct loop
        never crashes on a bad or failing tool call (spec 02 §3). Handles three
        failure points explicitly (unknown tool name, pydantic input validation, and
        execution) plus a catch-all for any other unexpected exception, each logged
        appropriately and each producing a `ToolResult` with `status="error"`.

        Args:
            tool_name (str): The name of the tool to execute, as requested by the LLM.
            raw_input (dict[str, Any]): The raw (unvalidated) arguments dict from the
                LLM's tool call, to be parsed against the tool's `input_model`.
            ctx (AgentContext): The current agent run's context, passed through to the
                tool's `execute` method.

        Returns:
            ToolResult: The execution result — `status="ok"` with the tool's output
                dict, or `status="error"` with an `{"error": "..."}` dict describing
                what went wrong (unknown tool, invalid input, `ToolExecutionError`, or
                an unexpected exception).
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
