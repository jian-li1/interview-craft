"""Auto-compaction: summarizes older messages using the small model when context grows large.

See docs/specs/02-agent-system-spec.md §5 and agent/prompts/compaction.md for the
contract this implements.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.llm.base import ChatMessage, LLMProvider

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Tool outputs older than this many recent exchanges get truncated to a short preview
# in the rebuilt context (full data still lives in Firestore research notes / sections).
RECENT_TOOL_EXCHANGES_KEPT_FULL = 6
TOOL_OUTPUT_PREVIEW_CHARS = 300

# Fraction of older messages folded into the summary when compaction triggers.
OLDER_FRACTION_TO_COMPACT = 0.6


@dataclass(slots=True)
class CompactionResult:
    summary: str
    compacted_through_seq: int
    tokens_before: int
    tokens_after: int


def load_compaction_prompt() -> str:
    return (_PROMPTS_DIR / "compaction.md").read_text(encoding="utf-8")


def _render_message_for_summary(msg: dict) -> str:
    role = msg.get("role", "user")
    content = msg.get("content", "") or ""
    reasoning = msg.get("reasoning")
    tool_calls = msg.get("tool_calls") or []
    parts = [f"[{role} | seq={msg.get('seq')}]"]
    if reasoning:
        parts.append(f"(reasoning: {reasoning[:200]})")
    if content:
        parts.append(content)
    for tc in tool_calls:
        parts.append(
            f"[tool_call {tc.get('name')} -> {tc.get('status')}: "
            f"{str(tc.get('output_preview', ''))[:200]}]"
        )
    return "\n".join(parts)


async def run_compaction(
    llm: LLMProvider,
    existing_summary: str | None,
    messages_to_compact: list[dict],
) -> str:
    """Summarize `messages_to_compact` (older ~60% of the conversation) via the small model.

    Merges with `existing_summary` if present, per the compaction.md contract. Returns
    the new rolling summary text (structured markdown under fixed headings).
    """
    system_prompt = load_compaction_prompt()

    rendered = "\n\n".join(_render_message_for_summary(m) for m in messages_to_compact)
    user_content_parts = []
    if existing_summary:
        user_content_parts.append(f"## Existing rolling summary\n\n{existing_summary}")
    user_content_parts.append(f"## New messages to fold in\n\n{rendered}")
    user_content = "\n\n".join(user_content_parts)

    chat_messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_content),
    ]
    summary = await llm.complete(chat_messages, small=True)
    return summary.strip()


def select_messages_to_compact(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split `messages` into (older_to_compact, remaining_recent) per the 0.6 fraction rule."""
    if not messages:
        return [], []
    cutoff = int(len(messages) * OLDER_FRACTION_TO_COMPACT)
    cutoff = max(1, cutoff) if len(messages) > 1 else 0
    return messages[:cutoff], messages[cutoff:]


def truncate_old_tool_outputs(messages: list[dict]) -> list[dict]:
    """Return a copy of `messages` with tool outputs older than the last N exchanges
    truncated to short previews. Full data lives in Firestore regardless.
    """
    # Identify indices of messages that carry tool_calls, from the end.
    tool_bearing_indices = [i for i, m in enumerate(messages) if m.get("tool_calls")]
    keep_full_indices = set(tool_bearing_indices[-RECENT_TOOL_EXCHANGES_KEPT_FULL:])

    result: list[dict] = []
    for i, msg in enumerate(messages):
        if i in keep_full_indices or not msg.get("tool_calls"):
            result.append(msg)
            continue
        new_msg = dict(msg)
        new_tool_calls = []
        for tc in msg["tool_calls"]:
            tc_copy = dict(tc)
            preview = str(tc_copy.get("output_preview", ""))
            if len(preview) > TOOL_OUTPUT_PREVIEW_CHARS:
                tc_copy["output_preview"] = preview[:TOOL_OUTPUT_PREVIEW_CHARS] + "... [truncated]"
            new_tool_calls.append(tc_copy)
        new_msg["tool_calls"] = new_tool_calls
        result.append(new_msg)
    return result
