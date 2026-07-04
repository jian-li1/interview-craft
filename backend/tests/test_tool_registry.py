"""Tool registry: provider-format schema shape, phase filtering, and safe execution."""

from __future__ import annotations

import pytest

from app.agent.tools.base import AgentContext
from app.agent.tools.registry import HITL_GATE_TOOLS, ToolRegistry
from app.services.llm.base import ToolSpec

ALL_TOOL_NAMES = {
    "web_search",
    "fetch_url",
    "save_research_note",
    "search_research_notes",
    "list_research_notes",
    "get_user_profile",
    "propose_task_plan",
    "get_task_plan",
    "list_curriculum_structure",
    "write_section",
    "read_section",
    "update_section",
    "write_curriculum_overview",
    "set_module_status",
    "request_user_input",
    "update_scratchpad",
    "complete_phase",
}


@pytest.fixture()
def registry() -> ToolRegistry:
    return ToolRegistry()


def test_registry_has_all_spec_tools(registry):
    assert set(registry._tools.keys()) == ALL_TOOL_NAMES


@pytest.mark.parametrize(
    "phase",
    [
        "intake",
        "deep_research",
        "outline_planning",
        "awaiting_approval",
        "writing",
        "review",
        "ready",
        "refinement",
    ],
)
def test_specs_for_phase_returns_valid_provider_schemas(registry, phase):
    specs = registry.specs_for_phase(phase)
    assert len(specs) > 0
    for spec in specs:
        assert isinstance(spec, ToolSpec)
        assert spec.name
        assert spec.description
        assert isinstance(spec.parameters, dict)
        # A valid JSON schema object for function-calling providers.
        assert spec.parameters.get("type") == "object"
        assert "title" not in spec.parameters


def test_always_available_tools_present_in_every_phase(registry):
    always = {"get_user_profile", "update_scratchpad", "complete_phase", "request_user_input"}
    for phase in ["intake", "deep_research", "outline_planning", "writing", "refinement"]:
        names = {s.name for s in registry.specs_for_phase(phase)}
        assert always.issubset(names)


def test_research_tools_hidden_during_awaiting_approval(registry):
    names = {s.name for s in registry.specs_for_phase("awaiting_approval")}
    assert "web_search" not in names
    assert "fetch_url" not in names
    assert "save_research_note" not in names


def test_research_tools_available_during_deep_research(registry):
    names = {s.name for s in registry.specs_for_phase("deep_research")}
    assert {"web_search", "fetch_url", "save_research_note", "search_research_notes", "list_research_notes"}.issubset(
        names
    )


def test_writing_tools_hidden_during_intake(registry):
    names = {s.name for s in registry.specs_for_phase("intake")}
    assert "write_section" not in names
    assert "propose_task_plan" not in names


def test_unknown_phase_falls_back_to_always_available(registry):
    specs = registry.specs_for_phase("not-a-real-phase")
    names = {s.name for s in specs}
    assert names == {"get_user_profile", "update_scratchpad", "complete_phase", "request_user_input"}


def test_hitl_gate_tools_match_spec():
    assert HITL_GATE_TOOLS == {"propose_task_plan", "request_user_input"}


def _make_ctx(phase: str = "intake") -> AgentContext:
    from app.core.config import get_settings

    return AgentContext(
        curriculum_id="cur1",
        conversation_id="conv1",
        owner_uid="uid1",
        settings=get_settings(),
        llm=object(),
        small_llm=object(),
        search=object(),
        phase=phase,
    )


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_error_result(registry):
    ctx = _make_ctx()
    result = await registry.execute("not_a_real_tool", {}, ctx)
    assert result.status == "error"
    assert "error" in result.output


@pytest.mark.asyncio
async def test_execute_invalid_input_returns_error_result_not_raise(registry):
    ctx = _make_ctx()
    # update_scratchpad requires `content: str`; omit it entirely.
    result = await registry.execute("update_scratchpad", {}, ctx)
    assert result.status == "error"
    assert "error" in result.output


@pytest.mark.asyncio
async def test_execute_tool_raising_unexpected_exception_is_caught(registry, monkeypatch):
    """A tool whose execute() raises a bare exception must not propagate out of the
    registry — the ReAct loop must never crash on a bad tool (spec 02 §3).
    """
    tool = registry._tools["update_scratchpad"]

    async def boom(self, input, ctx):
        raise RuntimeError("boom")

    monkeypatch.setattr(type(tool), "execute", boom)
    ctx = _make_ctx()
    result = await registry.execute("update_scratchpad", {"content": "x"}, ctx)
    assert result.status == "error"
    assert "boom" in result.output["error"]
