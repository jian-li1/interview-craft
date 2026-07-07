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
    """Loads and caches the markdown prompt files from disk.

    Each file is read from disk at most once per process (per `_prompt_library`
    singleton below) — subsequent `get` calls for the same filename hit the in-memory
    cache. This means prompt file edits require a process restart to take effect.
    """

    def __init__(self) -> None:
        """Initialize an empty file-contents cache."""
        self._cache: dict[str, str] = {}

    def get(self, filename: str) -> str:
        """Return the contents of `filename` from `_PROMPTS_DIR`, loading and caching it first if needed.

        Args:
            filename (str): The prompt file's name, relative to `_PROMPTS_DIR` (e.g.
                `"base_system.md"`).

        Returns:
            str: The full UTF-8 text contents of the file.
        """
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
    "review": "review_phase.md",  # dedicated quality pass + publish, not a second writing phase
    "ready": "refinement_phase.md",
    "refinement": "refinement_phase.md",
}


def build_static_system_prompt(phase: str) -> str:
    """Compose base_system.md + phase file + citation + visual guidelines.

    This is layer 1 of the context (see module docstring): the fixed instructional
    prompt for the given phase, unaffected by conversation history or user data. The
    phase file is looked up via `_PHASE_PROMPT_FILES`, falling back to
    `refinement_phase.md` for any phase not explicitly mapped. `base_system.md`,
    `citation_guidelines.md`, and `visual_guidelines.md` are appended for every phase.

    Args:
        phase (str): The current agent phase (e.g. "intake", "deep_research",
            "writing"), used to select the phase-specific instruction file.

    Returns:
        str: The concatenated prompt text, with each section separated by a
            `"\\n\\n---\\n\\n"` divider.
    """
    parts = [_prompt_library.get("base_system.md")]
    phase_file = _PHASE_PROMPT_FILES.get(phase, "refinement_phase.md")
    parts.append(f"# Current phase instructions ({phase})\n\n" + _prompt_library.get(phase_file))
    parts.append("# Citation guidelines\n\n" + _prompt_library.get("citation_guidelines.md"))
    parts.append("# Visual guidelines\n\n" + _prompt_library.get("visual_guidelines.md"))
    return "\n\n---\n\n".join(parts)


def build_user_memory_block(synthesized_profile: str | None, profile: dict[str, Any] | None) -> str:
    """Render layer 2 of the context: the user's synthesized profile and key structured fields.

    Args:
        synthesized_profile (str | None): The free-text profile summary produced by the
            profile-synthesis one-shot task, or None if not yet generated.
        profile (dict[str, Any] | None): The raw onboarding profile document, or None if
            the user has no profile yet.

    Returns:
        str: A human-readable block describing the user, or a placeholder string noting
            no profile information is available yet if both inputs are falsy.
    """
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
    """Compact, always-fresh rendering of the agent state doc.

    This is layer 3 of the context: the working-memory block is rebuilt fresh from the
    Firestore state doc on every call — it is never cached — so the model always sees
    the authoritative current phase/queue/scratchpad, even if a tool call earlier in the
    same iteration mutated the state doc.

    Args:
        state (dict[str, Any]): The agent state document (phase, task_queue,
            current_task_id, iteration_count, scratchpad).

    Returns:
        str: A compact multi-line summary of the state doc, with sensible defaults for
            any missing fields (phase defaults to "intake", scratchpad shows "(empty)").
    """
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
        """Store settings needed to build context (notably `context_token_limit`).

        Args:
            settings (Settings): Application settings, used here for
                `context_token_limit` (the compaction trigger threshold).
            llm_provider_factory: Currently unused placeholder for a future
                provider-factory injection point; defaults to None.
        """
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

        Called on every ReAct iteration (must stay cheap — see module docstring). Builds
        the layered context in fixed order: static system prompt, user memory, working
        memory, optional rolling summary, then recent conversation messages (with old
        tool outputs truncated via `truncate_old_tool_outputs`). If the assembled context
        exceeds `COMPACTION_TRIGGER_FRACTION` (0.8) of `context_token_limit`, the older
        ~60% of candidate messages (`select_messages_to_compact`) are summarized via the
        small model and folded into a new rolling summary, replacing the raw messages in
        the returned list; the conversation doc's `summary`/`compacted_through`/
        `token_estimate` fields are updated to persist the new checkpoint. If compaction
        does not trigger, only `token_estimate` is updated.

        `on_compaction` is an optional async callback `(summary_preview, tokens_before,
        tokens_after) -> None` used to emit the WS `compaction` event.

        Args:
            conversation_id (str): The conversation whose messages/summary to load.
            phase (str): The current agent phase, used to select the phase prompt file.
            synthesized_profile (str | None): The user's synthesized profile text, or
                None if not yet generated.
            profile (dict[str, Any] | None): The raw onboarding profile document, or
                None.
            agent_state (dict[str, Any]): The current agent state doc (phase, task
                queue, scratchpad, etc.) used to render the working-memory block.
            small_llm (LLMProvider | None): The provider to use for compaction
                summarization (routed via `small=True`); if None, compaction is skipped
                even if the token threshold is exceeded.
            on_compaction: Optional async callback invoked with `(summary_preview,
                tokens_before, tokens_after)` when compaction actually runs this call.

        Returns:
            list[ChatMessage]: The full ordered message list to send to the LLM this
                iteration, starting with the system-role context blocks followed by the
                (possibly compacted) conversation history.
        """
        conversation = fs.get_conversation(conversation_id) or {}
        existing_summary = conversation.get("summary")

        all_messages = fs.list_messages(conversation_id)
        compacted_through = conversation.get("compacted_through")
        if compacted_through:
            # Only include messages after the last compacted one — earlier messages are
            # already folded into `existing_summary` and must not be re-sent verbatim.
            idx = next(
                (i for i, m in enumerate(all_messages) if m["id"] == compacted_through), None
            )
            recent_messages = all_messages[idx + 1 :] if idx is not None else all_messages
        else:
            recent_messages = all_messages

        static_prompt = build_static_system_prompt(phase)
        user_memory = build_user_memory_block(synthesized_profile, profile)
        working_memory = build_working_memory_block(agent_state)

        # Fixed layer order per the module docstring / CLAUDE.md invariant: static
        # prompt -> user memory -> working memory -> (optional) summary -> messages.
        system_blocks = [static_prompt, user_memory, working_memory]
        if existing_summary:
            system_blocks.append(f"Summary of earlier conversation:\n\n{existing_summary}")

        # Independent of compaction: always trims old tool-call outputs to previews.
        candidate_messages = truncate_old_tool_outputs(recent_messages)

        def _assemble(msgs: list[dict]) -> list[ChatMessage]:
            """Combine the current `system_blocks` with converted conversation messages.

            Args:
                msgs (list[dict]): Raw Firestore message dicts to append after the
                    system blocks.

            Returns:
                list[ChatMessage]: System-role blocks followed by the converted
                    conversation messages, in order.
            """
            chat_messages = [ChatMessage(role="system", content=b) for b in system_blocks]
            for m in msgs:
                chat_messages.extend(_message_to_chat_messages(m))
            return chat_messages

        assembled = _assemble(candidate_messages)
        total_text = "\n".join(m.content for m in assembled if m.content)
        tokens_before = estimate_tokens(total_text)
        limit = self._settings.context_token_limit

        # Compaction trigger: only fires when (a) we're over 0.8x the context limit,
        # (b) a small model is available to do the summarization, and (c) there are
        # enough candidate messages that compacting is meaningful (>2, so we never try
        # to compact e.g. a single lingering message down to nothing).
        if tokens_before > COMPACTION_TRIGGER_FRACTION * limit and small_llm is not None and len(candidate_messages) > 2:
            older, remaining = select_messages_to_compact(candidate_messages)
            if older:
                logger.info(
                    "triggering context compaction",
                    extra={"extra_fields": {"conversation_id": conversation_id, "tokens_before": tokens_before}},
                )
                new_summary = await run_compaction(small_llm, existing_summary, older)
                last_compacted_msg = older[-1]
                # Persist the new checkpoint: future build_context calls will only load
                # messages after `last_compacted_msg["id"]` (see `compacted_through` read
                # above) and will use the merged `new_summary` in place of the old one.
                fs.update_conversation(
                    conversation_id,
                    {
                        "summary": new_summary,
                        "compacted_through": last_compacted_msg["id"],
                        "token_estimate": tokens_before,
                    },
                )
                # Swap the summary block in system_blocks for the freshly merged one,
                # then rebuild the message list using only the still-recent `remaining`
                # messages (the `older` ones are now represented solely by the summary).
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

    Args:
        msg (dict[str, Any]): A raw message document (role, content, optional
            tool_calls list with id/name/input/output_full/output_preview per call).

    Returns:
        list[ChatMessage]: A single ChatMessage for plain messages, or an
            assistant-message-plus-per-call tool-messages sequence when `tool_calls`
            is present on an assistant message.
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
                    # Replay the full tool output; fall back to the short preview for
                    # legacy records written before `output_full` existed.
                    content=str(tc.get("output_full") or tc.get("output_preview", "")),
                    name=tc["name"],
                    tool_call_id=tc["id"],
                )
            )
        return out

    return [ChatMessage(role=role, content=content)]


def _safe_json(obj: Any) -> str:
    """Best-effort JSON-serialize `obj`, never raising.

    Args:
        obj (Any): The object to serialize (typically a tool call's input dict).

    Returns:
        str: The JSON string, or `"{}"` if `obj` is not JSON-serializable.
    """
    import json

    try:
        return json.dumps(obj)
    except Exception:
        return "{}"
