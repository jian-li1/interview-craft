"""Splits a raw text delta stream into reasoning (<thinking>...</thinking>) and answer text.

Per spec 02 §3: the system prompt instructs the model to open each response with a
`<thinking>...</thinking>` block. This parser is provider-agnostic — it works on the raw
text delta stream regardless of which LLM produced it, routing content inside the block
to reasoning and everything else to the user-visible answer.

Implemented as an incremental state machine so it can be fed streaming chunks (which may
split the `<thinking>`/`</thinking>` tags across arbitrary chunk boundaries).
"""

from __future__ import annotations

from dataclasses import dataclass

_OPEN_TAG = "<thinking>"
_CLOSE_TAG = "</thinking>"


@dataclass(slots=True)
class SplitDelta:
    """Output of feeding one chunk into the splitter.

    Attributes:
        reasoning (str): Portion of the fed chunk that belongs inside the
            `<thinking>...</thinking>` block, to be emitted as a `reasoning_delta` WS event.
        text (str): Portion of the fed chunk that is user-visible answer text, to be
            emitted as a `text_delta` WS event.
    """

    reasoning: str = ""
    text: str = ""


class ThinkingStreamSplitter:
    """Incremental parser routing streamed text into reasoning vs. answer text.

    Implemented as a small state machine over three states, tracked via the
    `_in_thinking`/`_seen_thinking`/`_finished_thinking_phase` flags:

    1. Not yet seen `<thinking>` (looking for the opening tag at the very start of the
       stream, ignoring leading whitespace).
    2. Inside the `<thinking>` block (accumulating reasoning text until `</thinking>`).
    3. Finished with the thinking phase (either the block closed, or no opening tag was
       found) — from here on, everything fed is routed to plain answer text.

    The state machine buffers text internally so that opening/closing tags split across
    arbitrary chunk boundaries (a streaming LLM API may emit `<think` then `ing>` as two
    separate deltas) are still detected correctly.
    """

    def __init__(self) -> None:
        """Initialize a fresh splitter with an empty buffer, ready for state 1 (pre-thinking)."""
        self._buffer = ""
        self._in_thinking = False
        self._seen_thinking = False
        # Once we've emitted any non-thinking text, treat the rest of the stream as
        # plain text even if a stray "<thinking>"-like fragment appears — the model is
        # only expected to open the block at the very start of a response.
        self._finished_thinking_phase = False

    def feed(self, chunk: str) -> SplitDelta:
        """Feed a raw text chunk, returning the reasoning/text to emit for it.

        Runs the internal state machine to completion for the newly buffered content,
        looping until either the buffer is fully consumed or what remains might be part
        of a tag that hasn't fully arrived yet (in which case it stays buffered for the
        next `feed` call).

        Args:
            chunk (str): The next raw text delta from the LLM provider's stream.

        Returns:
            SplitDelta: The reasoning/text extracted from this chunk (combined with any
                previously buffered content that could now be resolved).
        """
        self._buffer += chunk
        out = SplitDelta()

        while True:
            if self._finished_thinking_phase:
                # State 3: thinking phase over: everything remaining is plain text.
                out.text += self._buffer
                self._buffer = ""
                return out

            if not self._in_thinking and not self._seen_thinking:
                # State 1: looking for the opening tag at the very start of the stream.
                stripped = self._buffer.lstrip()
                leading_ws_len = len(self._buffer) - len(stripped)
                if stripped.startswith(_OPEN_TAG):
                    # Found the full opening tag: transition into state 2 (in_thinking).
                    self._in_thinking = True
                    self._seen_thinking = True
                    self._buffer = stripped[len(_OPEN_TAG) :]
                    continue
                # If we have enough buffered text to be sure it's not a (partial) open
                # tag, or the buffer contains a character that couldn't lead into the
                # tag, flush it as plain text and stop looking for thinking forever.
                if self._could_be_partial_open_tag(stripped):
                    # Wait for more chunks before deciding (tag may still be arriving).
                    return out
                # Definitely not a thinking block: transition straight to state 3.
                out.text += self._buffer
                self._buffer = ""
                self._finished_thinking_phase = True
                return out

            if self._in_thinking:
                # State 2: accumulating reasoning text until the closing tag appears.
                close_idx = self._buffer.find(_CLOSE_TAG)
                if close_idx == -1:
                    # Emit everything except a possibly-partial closing tag at the end.
                    safe_len = self._safe_emit_length(self._buffer, _CLOSE_TAG)
                    out.reasoning += self._buffer[:safe_len]
                    self._buffer = self._buffer[safe_len:]
                    return out
                # Closing tag found: emit reasoning up to it, drop the tag itself, and
                # transition to state 3 (finished) — the model only opens the block once.
                out.reasoning += self._buffer[:close_idx]
                self._buffer = self._buffer[close_idx + len(_CLOSE_TAG) :]
                self._in_thinking = False
                self._finished_thinking_phase = True
                continue

            # seen_thinking but not in_thinking and not finished: shouldn't happen, but
            # guard against infinite loop.
            out.text += self._buffer
            self._buffer = ""
            self._finished_thinking_phase = True
            return out

    def flush(self) -> SplitDelta:
        """Call at end-of-stream to flush any remaining buffered content as plain text.

        Handles the edge case where the stream ends mid-tag or mid-reasoning-block: any
        content still sitting in the internal buffer (e.g. a partial tag that never
        resolved, or trailing reasoning text with no closing tag) is emitted as-is rather
        than silently dropped.

        Returns:
            SplitDelta: Whatever was left in the buffer, routed to `reasoning` if the
                stream ended while still inside a `<thinking>` block, else to `text`.
        """
        out = SplitDelta()
        if self._buffer:
            if self._in_thinking:
                out.reasoning = self._buffer
            else:
                out.text = self._buffer
            self._buffer = ""
        return out

    @staticmethod
    def _could_be_partial_open_tag(stripped: str) -> bool:
        """Check whether `stripped` could still grow into the full opening tag.

        Args:
            stripped (str): The buffered text with leading whitespace removed.

        Returns:
            bool: True if `stripped` is empty or is a strict prefix of `<thinking>`,
                meaning more chunks are needed before we can decide either way.
        """
        if not stripped:
            return True
        return _OPEN_TAG.startswith(stripped) and len(stripped) < len(_OPEN_TAG)

    @staticmethod
    def _safe_emit_length(buffer: str, tag: str) -> int:
        """Return how much of `buffer` is safe to emit without possibly splitting `tag`.

        Args:
            buffer (str): The currently buffered text (known to not yet contain `tag`
                in full).
            tag (str): The tag to guard against splitting (here, always `</thinking>`).

        Returns:
            int: The length of the prefix of `buffer` that cannot be the start of a
                partial `tag` at the very end of the buffer — safe to flush immediately.
        """
        max_check = min(len(tag) - 1, len(buffer))
        for i in range(max_check, 0, -1):
            if tag.startswith(buffer[-i:]):
                return len(buffer) - i
        return len(buffer)
