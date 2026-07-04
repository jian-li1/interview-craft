"""MemoryManager: assembles the layered context sent to the LLM on every ReAct iteration.

Layers (see docs/specs/02-agent-system-spec.md §5):
1. Static system prompt (base_system.md + phase file + citation + visual guidelines)
2. User memory (synthesized profile)
3. Working memory (agent state doc: phase, task queue, scratchpad, plan version)
4. Episodic memory (conversation summary + recent messages + tool exchanges verbatim)
5. Research memory — NOT injected; accessed on demand via tools.

Also owns auto-compaction: when the assembled context exceeds 0.8 * CONTEXT_TOKEN_LIMIT,
older messages are summarized via the small model and folded into a rolling summary
persisted on the conversation document.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent.memory.compaction import (
    run_compaction,
    select_messages_to_compact,
    truncate_old_tool_outputs,
)
from app.agent.memory.tokens import estimate_tokens
from app.core.config import Settings
from app.core.logging import get_logger
from app.services import firestore as fs
from app.services.llm.base import ChatMessage, LLMProvider

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
COMPACTION_TRIGGER_FRACTION = 0.8


class PromptLibrary:
    """Loads and caches the markdown prompt files from disk."""

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def get(self, filename: str) -> str:
        if filename not in self._cache:
            path = _PROMPTS_DIR / filename
            self._cache[filename] = path.read_text(encoding="utf-8")
        return self._cache[filename]


_prompt_library = PromptLibrary()


_PHASE_PROMPT_FILES: dict[str, str] = {
    "intake": "intake_phase.md",
    "deep_research": "research_phase.md",
    "outline_planning": "planning_phase.md",
    "awaiting_approval": "planning_phase.md",
    "writing": "writing_phase.md",
    "review": "writing_phase.md",
    "ready": "refinement_phase.md",
    "refinement": "refinement_phase.md",
}


def build_static_system_prompt(phase: str) -> str:
    """Compose base_system.md + phase file + citation + visual guidelines."""
    parts = [_prompt_library.get("base_system.md")]
    phase_file = _PHASE_PROMPT_FILES.get(phase, "refinement_phase.md")
    parts.append(f"# Current phase instructions ({phase})\n\n" + _prompt_library.get(phase_file))
    parts.append("# Citation guidelines\n\n" + _prompt_library.get("citation_guidelines.md"))
    parts.append("# Visual guidelines\n\n" + _prompt_library.get("visual_guidelines.md"))
    return "\n\n---\n\n".join(parts)


def build_user_memory_block(synthesized_profile: str | None, profile: dict[str, Any] | None) -> str:
    if not synthesized_profile and not profile:
        return "About the user: no profile information available yet."
    lines = ["About the user:"]
    if synthesized_profile:
        lines.append(synthesized_profile)
    if profile:
        structured = {
            "target_roles": profile.get("target_roles"),
            "experience_level": profile.get("experience_level"),
            "learning_style": profile.get("learning_style"),
            "timeline": profile.get("timeline"),
        }
        lines.append(f"Structured profile fields: {structured}")
    return "\n\n".join(lines)


def build_working_memory_block(state: dict[str, Any]) -> str:
    """Compact, always-fresh rendering of the agent state doc."""
    return (
        "Agent working memory (authoritative, always current):\n"
        f"- phase: {state.get('phase', 'intake')}\n"
        f"- task_queue: {state.get('task_queue', [])}\n"
        f"- current_task_id: {state.get('current_task_id')}\n"
        f"- iteration_count: {state.get('iteration_count', 0)}\n"
        f"- scratchpad:\n{state.get('scratchpad', '') or '(empty)'}"
    )


class MemoryManager:
    """Builds LLM context for a conversation/curriculum, with auto-compaction."""

    def __init__(self, settings: Settings, llm_provider_factory=None) -> None:
        self._settings = settings
        self._llm_provider_factory = llm_provider_factory

    async def build_context(
        self,
        conversation_id: str,
        phase: str,
        synthesized_profile: str | None,
        profile: dict[str, Any] | None,
        agent_state: dict[str, Any],
        small_llm: LLMProvider | None = None,
        on_compaction=None,
    ) -> list[ChatMessage]:
        """Assemble the full message list to send to the LLM this iteration.

        `on_compaction` is an optional async callback `(summary_preview, tokens_before,
        tokens_after) -> None` used to emit the WS `compaction` event.
        """
        conversation = fs.get_conversation(conversation_id) or {}
        existing_summary = conversation.get("summary")

        all_messages = fs.list_messages(conversation_id)
        compacted_through = conversation.get("compacted_through")
        if compacted_through:
            # Only include messages after the last compacted one.
            idx = next(
                (i for i, m in enumerate(all_messages) if m["id"] == compacted_through), None
            )
            recent_messages = all_messages[idx + 1 :] if idx is not None else all_messages
        else:
            recent_messages = all_messages

        static_prompt = build_static_system_prompt(phase)
        user_memory = build_user_memory_block(synthesized_profile, profile)
        working_memory = build_working_memory_block(agent_state)

        system_blocks = [static_prompt, user_memory, working_memory]
        if existing_summary:
            system_blocks.append(f"Summary of earlier conversation:\n\n{existing_summary}")

        candidate_messages = truncate_old_tool_outputs(recent_messages)

        def _assemble(msgs: list[dict]) -> list[ChatMessage]:
            chat_messages = [ChatMessage(role="system", content=b) for b in system_blocks]
            for m in msgs:
                chat_messages.extend(_message_to_chat_messages(m))
            return chat_messages

        assembled = _assemble(candidate_messages)
        total_text = "\n".join(m.content for m in assembled if m.content)
        tokens_before = estimate_tokens(total_text)
        limit = self._settings.context_token_limit

        if tokens_before > COMPACTION_TRIGGER_FRACTION * limit and small_llm is not None and len(candidate_messages) > 2:
            older, remaining = select_messages_to_compact(candidate_messages)
            if older:
                logger.info(
                    "triggering context compaction",
                    extra={"extra_fields": {"conversation_id": conversation_id, "tokens_before": tokens_before}},
                )
                new_summary = await run_compaction(small_llm, existing_summary, older)
                last_compacted_msg = older[-1]
                fs.update_conversation(
                    conversation_id,
                    {
                        "summary": new_summary,
                        "compacted_through": last_compacted_msg["id"],
                        "token_estimate": tokens_before,
                    },
                )
                system_blocks = system_blocks[:-1] if existing_summary else system_blocks
                system_blocks.append(f"Summary of earlier conversation:\n\n{new_summary}")
                assembled = _assemble(remaining)
                tokens_after = estimate_tokens("\n".join(m.content for m in assembled if m.content))
                if on_compaction:
                    preview = new_summary[:300]
                    await on_compaction(preview, tokens_before, tokens_after)
                return assembled

        fs.update_conversation(conversation_id, {"token_estimate": tokens_before})
        return assembled


def _message_to_chat_messages(msg: dict[str, Any]) -> list[ChatMessage]:
    """Convert a stored Firestore message doc into one or more ChatMessage entries.

    Assistant messages with tool_calls become an assistant message (with tool_calls) plus
    one tool-role message per call result, matching the OpenAI-style conversation shape
    that both provider adapters expect.
    """
    role = msg.get("role", "user")
    content = msg.get("content", "") or ""
    tool_calls = msg.get("tool_calls") or []

    if role == "assistant" and tool_calls:
        assistant_tool_calls = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": _safe_json(tc.get("input", {}))},
            }
            for tc in tool_calls
        ]
        out = [
            ChatMessage(role="assistant", content=content, tool_calls=assistant_tool_calls)
        ]
        for tc in tool_calls:
            out.append(
                ChatMessage(
                    role="tool",
                    content=str(tc.get("output_preview", "")),
                    name=tc["name"],
                    tool_call_id=tc["id"],
                )
            )
        return out

    return [ChatMessage(role=role, content=content)]


def _safe_json(obj: Any) -> str:
    import json

    try:
        return json.dumps(obj)
    except Exception:
        return "{}"
