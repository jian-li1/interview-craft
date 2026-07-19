"""Async generation of personalized dashboard PromptBox suggestions.

Triggered as a background task from `app.api.onboarding.put_onboarding` once the wizard
finishes (`onboarding_completed: true`) — see spec 01 §5/§6 and §7b for the schema/API/WS
shapes this module writes and emits.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.services import firestore as fs
from app.services.llm.base import ChatMessage
from app.services.llm.factory import get_llm_provider
from app.ws.dashboard import emit_suggestions_updated

logger = logging.getLogger(__name__)

# Validation caps mirroring the prompt file's instructions (loose hard caps, not the
# model's actual target lengths — see dashboard_suggestions.md for the real targets).
_MAX_SUGGESTIONS = 5
_MIN_VALID_SUGGESTIONS = 3
_SUGGESTION_MAX_CHARS = 100
_PLACEHOLDER_MAX_CHARS = 200


def _load_dashboard_suggestions_prompt() -> str:
    """Load the dashboard-suggestions system prompt markdown file from disk.

    Mirrors `onboarding._load_profile_synthesis_prompt`'s read-fresh-every-call pattern —
    this is only invoked once per onboarding completion, not a hot path.

    Returns:
        str: The full contents of `app/agent/prompts/dashboard_suggestions.md`.
    """
    path = Path(__file__).resolve().parent.parent / "agent" / "prompts" / "dashboard_suggestions.md"
    return path.read_text(encoding="utf-8")


def _parse_llm_output(raw: str) -> tuple[list[str], str] | None:
    """Tolerantly parse the model's JSON output into validated suggestions + placeholder.

    Strips ```json fences if the model added them despite the prompt's "STRICT JSON ONLY"
    instruction, then validates shape: suggestions must be a list of non-empty strings
    (trimmed, capped at `_SUGGESTION_MAX_CHARS`, capped at `_MAX_SUGGESTIONS` entries, with
    at least `_MIN_VALID_SUGGESTIONS` surviving); placeholder must be a non-empty string
    (trimmed, capped at `_PLACEHOLDER_MAX_CHARS`).

    Args:
        raw (str): The raw text returned by the LLM's `complete()` call.

    Returns:
        tuple[list[str], str] | None: `(suggestions, placeholder)` on success, or None if
            the output failed to parse or didn't meet the validation bar.
    """
    text = raw.strip()
    # Strip a ```json ... ``` or bare ``` ... ``` fence if the model wrapped its output
    # despite being told not to — defensive tolerance, not an expected path.
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    raw_suggestions = data.get("suggestions")
    raw_placeholder = data.get("placeholder")
    if not isinstance(raw_suggestions, list) or not isinstance(raw_placeholder, str):
        return None

    # Trim/cap each suggestion; drop anything that isn't a non-empty string post-trim.
    # Also drop duplicates — the frontend keys chips by the suggestion string itself.
    suggestions: list[str] = []
    for item in raw_suggestions:
        if isinstance(item, str) and item.strip():
            cleaned = item.strip()[:_SUGGESTION_MAX_CHARS]
            if cleaned not in suggestions:
                suggestions.append(cleaned)
        if len(suggestions) >= _MAX_SUGGESTIONS:
            break
    if len(suggestions) < _MIN_VALID_SUGGESTIONS:
        return None

    placeholder = raw_placeholder.strip()[:_PLACEHOLDER_MAX_CHARS]
    if not placeholder:
        return None

    return suggestions, placeholder


def _render_input_block(profile: dict) -> str:
    """Render the profile fields relevant to suggestion generation as `key: value` lines.

    Mirrors `onboarding._render_input_block`'s plain-text-block approach rather than
    requiring the model to parse JSON on the input side.

    Args:
        profile (dict): The raw Firestore profile document fields.

    Returns:
        str: A newline-separated `"{key}: {value}"` block for the user-turn message.
    """
    lines = [
        f"synthesized_profile: {profile.get('synthesized_profile') or ''}",
        f"target_roles: {profile.get('target_roles', [])}",
        f"skills: {profile.get('skills', [])}",
        f"experience_level: {profile.get('experience_level', '')}",
        f"timeline: {profile.get('timeline', '')}",
    ]
    return "\n".join(lines)


async def generate_prompt_suggestions(uid: str) -> None:
    """Generate personalized dashboard suggestions/placeholder and persist + broadcast them.

    Fire-and-forget background task spawned by `put_onboarding` right after it stamps
    `suggestions_status: "pending"`. Wraps the entire body in try/except: any failure
    (LLM error, malformed JSON, failed validation) falls back to
    `suggestions_status: None` so the frontend's PromptBox falls back to its hardcoded
    examples rather than getting stuck showing an empty suggestion row forever.

    Args:
        uid (str): The Firebase Auth uid whose profile to generate suggestions for.

    Returns:
        None:
    """
    try:
        profile = fs.get_profile(uid) or {}
        system_prompt = _load_dashboard_suggestions_prompt()
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=_render_input_block(profile)),
        ]
        # Server default model — same rationale as onboarding.synthesize_profile: no
        # conversation to inherit a selection from here.
        llm = get_llm_provider()
        raw = await llm.complete(messages)

        parsed = _parse_llm_output(raw)
        if parsed is None:
            raise ValueError(f"malformed or under-valid LLM output for uid={uid}")
        suggestions, placeholder = parsed

        fs.upsert_profile(
            uid,
            {
                "prompt_suggestions": suggestions,
                "prompt_placeholder": placeholder,
                "suggestions_status": "ready",
            },
        )
        # Push to any live dashboard sockets so the PromptBox updates without a refresh.
        await emit_suggestions_updated(uid, suggestions, placeholder)
    except Exception:
        # Never leave the profile stuck on "pending" — fall back to None so the frontend
        # treats this exactly like "never generated" and shows the hardcoded examples.
        logger.exception("dashboard prompt-suggestion generation failed", extra={"extra_fields": {"uid": uid}})
        try:
            fs.upsert_profile(uid, {"suggestions_status": None})
        except Exception:
            # Even the fallback write failed (e.g. Firestore down) — nothing more we can
            # do here; the profile will simply stay "pending" until the user retries
            # onboarding, which is an acceptable degraded state.
            logger.exception("failed to reset suggestions_status after generation failure")
