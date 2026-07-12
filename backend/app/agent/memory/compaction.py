"""Auto-compaction: summarizes older messages using the conversation's selected model when context grows large.

See docs/specs/02-agent-system-spec.md §5 and agent/prompts/compaction.md for the
contract this implements.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.llm.base import ChatMessage, LLMProvider

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Tool outputs older than this many recent exchanges get truncated to a short preview
# in the rebuilt context (full data still lives in Firestore saved sources / sections).
RECENT_TOOL_EXCHANGES_KEPT_FULL = 20
TOOL_OUTPUT_PREVIEW_CHARS = 300

# Fraction of older messages folded into the summary when compaction triggers.
OLDER_FRACTION_TO_COMPACT = 0.6


@dataclass(slots=True)
class CompactionResult:
    """Outcome of a compaction pass (currently unused as a return type — see `run_compaction`,
    which returns the summary string directly; kept as a documented shape for callers that
    want to track the full before/after picture).

    Attributes:
        summary (str): The new rolling summary text produced by compaction.
        compacted_through_seq (int): Sequence number of the last message folded into the
            summary; messages after this point remain verbatim in context.
        tokens_before (int): Estimated token count of the assembled context before
            compaction ran.
        tokens_after (int): Estimated token count of the assembled context after
            compaction ran.
    """

    summary: str
    compacted_through_seq: int
    tokens_before: int
    tokens_after: int


def load_compaction_prompt() -> str:
    """Load the compaction system prompt from `agent/prompts/compaction.md`.

    Returns:
        str: The raw markdown contents of `compaction.md`, used verbatim as the system
            prompt for the summarization call.
    """
    return (_PROMPTS_DIR / "compaction.md").read_text(encoding="utf-8")


def _render_message_for_summary(msg: dict) -> str:
    """Render a single stored message dict into a compact plain-text line for the summarizer.

    Includes role, sequence number, a truncated reasoning preview, the message content,
    and a truncated preview of any tool calls — enough detail for the summarizer to fold
    the message into the rolling summary without needing the full structured form.

    Args:
        msg (dict): A raw message document as stored in Firestore (role, content,
            optional reasoning, optional tool_calls).

    Returns:
        str: A single multi-line string representation of the message.
    """
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
    """Summarize `messages_to_compact` (older ~60% of the conversation) via `llm`.

    Merges with `existing_summary` if present, per the compaction.md contract. `llm` is
    the conversation's selected model (there is no separate "small model" anymore —
    compaction now runs on whatever model the user picked for the run).

    Args:
        llm (LLMProvider): The provider instance to call — the `compaction_llm` passed
            down from the orchestrator (the conversation's selected model).
        existing_summary (str | None): The prior rolling summary to merge new content
            into, or None if this is the first compaction for the conversation.
        messages_to_compact (list[dict]): The older messages (raw Firestore message
            dicts) to fold into the summary, as selected by `select_messages_to_compact`.

    Returns:
        str: The new rolling summary text (structured markdown under fixed headings, per
            compaction.md), stripped of leading/trailing whitespace.
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
    summary = await llm.complete(chat_messages)
    return summary.strip()


def select_messages_to_compact(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split `messages` into (older_to_compact, remaining_recent) per the 0.6 fraction rule.

    The cutoff index is `len(messages) * OLDER_FRACTION_TO_COMPACT` (i.e. the older ~60%
    of messages get folded into the summary), floored to an int, with a special case
    ensuring at least one message is compacted whenever there's more than one message
    (so compaction always makes forward progress once triggered).

    Args:
        messages (list[dict]): The candidate messages to split, in chronological order
            (already tool-output-truncated by `truncate_old_tool_outputs`).

    Returns:
        tuple[list[dict], list[dict]]: A `(older, remaining)` pair where `older` is the
            prefix to compact and `remaining` is the suffix to keep verbatim in context.
            Both are empty lists if `messages` is empty.
    """
    if not messages:
        return [], []
    cutoff = int(len(messages) * OLDER_FRACTION_TO_COMPACT)
    cutoff = max(1, cutoff) if len(messages) > 1 else 0
    return messages[:cutoff], messages[cutoff:]


def truncate_old_tool_outputs(messages: list[dict]) -> list[dict]:
    """Return a copy of `messages` with tool outputs older than the last N exchanges
    truncated to short previews. Full data lives in Firestore regardless.

    Runs on every `build_context` call, independent of whether compaction triggers this
    iteration — this keeps per-iteration context lean even when the conversation is well
    under the compaction threshold. Only the `RECENT_TOOL_EXCHANGES_KEPT_FULL` most recent
    tool-call-bearing messages keep their full `output_full` (the model-facing content);
    older ones are trimmed to `TOOL_OUTPUT_PREVIEW_CHARS` with a `"... [truncated]"` suffix.
    Messages without `tool_calls` are passed through untouched (and un-copied).

    Args:
        messages (list[dict]): The candidate messages (raw Firestore message dicts) to
            process, in chronological order.

    Returns:
        list[dict]: A new list with the same messages, except that outside the most
            recent `RECENT_TOOL_EXCHANGES_KEPT_FULL` tool-bearing messages, each tool
            call's `output_full` (the model-facing field) is truncated. Non-tool-bearing
            and recent tool-bearing messages are included as-is (not copied).
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
            # The model reads `output_full` (falling back to the legacy `output_preview`),
            # so truncate whichever field it would see — otherwise the full output of old
            # exchanges would defeat the leaning this function exists to provide.
            source = str(tc_copy.get("output_full") or tc_copy.get("output_preview", ""))
            if len(source) > TOOL_OUTPUT_PREVIEW_CHARS:
                tc_copy["output_full"] = source[:TOOL_OUTPUT_PREVIEW_CHARS] + "... [truncated]"
            new_tool_calls.append(tc_copy)
        new_msg["tool_calls"] = new_tool_calls
        result.append(new_msg)
    return result
