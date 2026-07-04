"""Token estimation utilities.

Uses tiktoken when available (cached encoder), falling back to a chars/4 heuristic if
tiktoken's encoder can't be loaded (e.g. offline environments without cached BPE files).
"""

from __future__ import annotations

from functools import lru_cache

from app.core.logging import get_logger

logger = get_logger(__name__)

_FALLBACK_CHARS_PER_TOKEN = 4


@lru_cache
def _get_encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - exercised only when tiktoken data is unavailable
        logger.warning("tiktoken encoder unavailable; falling back to chars/4 token estimate")
        return None


def estimate_tokens(text: str) -> int:
    """Estimate the token count of `text`."""
    if not text:
        return 0
    encoder = _get_encoder()
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception:
            logger.warning("tiktoken encode failed; falling back to chars/4 for this call")
    return max(1, len(text) // _FALLBACK_CHARS_PER_TOKEN)


def estimate_messages_tokens(texts: list[str]) -> int:
    """Estimate total tokens across multiple text blocks (e.g. assembled messages)."""
    return sum(estimate_tokens(t) for t in texts)
