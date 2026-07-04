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
    """Load and cache the tiktoken `cl100k_base` encoder, if tiktoken is usable.

    Cached via `lru_cache` (no arguments, so effectively a memoized singleton) so the
    encoder is only constructed once per process. Falls back to `None` rather than
    raising when tiktoken's BPE data can't be loaded — e.g. in offline environments
    without cached encoding files — so callers must handle a `None` result.

    Returns:
        The loaded tiktoken encoder object, or `None` if tiktoken is unavailable/fails
        to load.
    """
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - exercised only when tiktoken data is unavailable
        logger.warning("tiktoken encoder unavailable; falling back to chars/4 token estimate")
        return None


def estimate_tokens(text: str) -> int:
    """Estimate the token count of `text`.

    Uses the cached tiktoken encoder when available; otherwise falls back to a
    chars/4 heuristic (`_FALLBACK_CHARS_PER_TOKEN`). Also falls back mid-call if the
    encoder raises during `encode` (e.g. transient tiktoken error), rather than
    propagating the exception.

    Args:
        text (str): The text to estimate the token count for.

    Returns:
        int: The estimated number of tokens. Always at least 1 for non-empty text
            when using the fallback heuristic, and 0 for empty/falsy input.
    """
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
    """Estimate total tokens across multiple text blocks (e.g. assembled messages).

    Args:
        texts (list[str]): The text blocks to estimate and sum token counts for.

    Returns:
        int: The sum of `estimate_tokens` over each block in `texts`.
    """
    return sum(estimate_tokens(t) for t in texts)
