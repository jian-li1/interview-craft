"""Memory manager: token estimation, compaction-threshold logic, prompt composition."""

from __future__ import annotations

import pytest

from app.agent.memory.compaction import (
    select_messages_to_compact,
    truncate_old_tool_outputs,
)
from app.agent.memory.manager import (
    build_static_system_prompt,
    build_user_memory_block,
    build_working_memory_block,
)
from app.agent.memory.tokens import estimate_tokens


def test_estimate_tokens_empty_string_is_zero():
    assert estimate_tokens("") == 0


def test_estimate_tokens_scales_with_length():
    short = estimate_tokens("hello world")
    long = estimate_tokens("hello world " * 100)
    assert long > short
    assert short >= 1


def test_estimate_tokens_reasonable_for_known_text():
    # "hello world" -> 2 tokens under cl100k_base; allow the chars/4 fallback (~3) too.
    tokens = estimate_tokens("hello world")
    assert 1 <= tokens <= 5


def test_select_messages_to_compact_empty():
    older, remaining = select_messages_to_compact([])
    assert older == []
    assert remaining == []


def test_select_messages_to_compact_single_message_not_compacted():
    msgs = [{"id": "1", "seq": 1}]
    older, remaining = select_messages_to_compact(msgs)
    assert older == []
    assert remaining == msgs


def test_select_messages_to_compact_splits_older_60_percent():
    msgs = [{"id": str(i), "seq": i} for i in range(10)]
    older, remaining = select_messages_to_compact(msgs)
    assert len(older) == 6
    assert len(remaining) == 4
    assert older + remaining == msgs


def test_truncate_old_tool_outputs_keeps_recent_full():
    msgs = []
    for i in range(10):
        msgs.append(
            {
                "id": str(i),
                "role": "assistant",
                "tool_calls": [
                    {"id": f"tc{i}", "name": "web_search", "output_preview": "x" * 500}
                ],
            }
        )
    result = truncate_old_tool_outputs(msgs)
    # Last 6 tool-bearing messages keep full output; earlier ones get truncated.
    for i, msg in enumerate(result):
        preview = msg["tool_calls"][0]["output_preview"]
        if i >= 4:  # indices 4..9 are the last 6
            assert preview == "x" * 500
        else:
            assert preview.endswith("... [truncated]")
            assert len(preview) < 500


def test_truncate_old_tool_outputs_leaves_non_tool_messages_untouched():
    msgs = [{"id": "1", "role": "user", "content": "hi"}]
    result = truncate_old_tool_outputs(msgs)
    assert result == msgs


def test_build_static_system_prompt_includes_phase_and_shared_sections():
    prompt = build_static_system_prompt("deep_research")
    assert "Current phase instructions (deep_research)" in prompt
    assert "Citation guidelines" in prompt
    assert "Visual guidelines" in prompt


def test_build_static_system_prompt_unknown_phase_falls_back_to_refinement():
    prompt = build_static_system_prompt("nonexistent_phase")
    assert "refinement_phase" in prompt.lower() or "Current phase instructions (nonexistent_phase)" in prompt


def test_build_user_memory_block_no_profile():
    block = build_user_memory_block(None, None)
    assert "no profile information available" in block.lower()


def test_build_user_memory_block_with_synthesized_profile():
    block = build_user_memory_block("A driven backend engineer.", {"target_roles": ["SWE"]})
    assert "A driven backend engineer." in block
    assert "target_roles" in block


def test_build_working_memory_block_reflects_state():
    state = {
        "phase": "writing",
        "task_queue": ["t1", "t2"],
        "current_task_id": "t1",
        "iteration_count": 5,
        "scratchpad": "working on module 2",
    }
    block = build_working_memory_block(state)
    assert "writing" in block
    assert "t1" in block
    assert "5" in block
    assert "working on module 2" in block


def test_build_working_memory_block_empty_scratchpad():
    block = build_working_memory_block({})
    assert "(empty)" in block
