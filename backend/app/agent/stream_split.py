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
    """Output of feeding one chunk into the splitter."""

    reasoning: str = ""
    text: str = ""


class ThinkingStreamSplitter:
    """Incremental parser routing streamed text into reasoning vs. answer text."""

    def __init__(self) -> None:
        self._buffer = ""
        self._in_thinking = False
        self._seen_thinking = False
        # Once we've emitted any non-thinking text, treat the rest of the stream as
        # plain text even if a stray "<thinking>"-like fragment appears — the model is
        # only expected to open the block at the very start of a response.
        self._finished_thinking_phase = False

    def feed(self, chunk: str) -> SplitDelta:
        """Feed a raw text chunk, returning the reasoning/text to emit for it."""
        self._buffer += chunk
        out = SplitDelta()

        while True:
            if self._finished_thinking_phase:
                out.text += self._buffer
                self._buffer = ""
                return out

            if not self._in_thinking and not self._seen_thinking:
                # Looking for the opening tag at the very start of the stream.
                stripped = self._buffer.lstrip()
                leading_ws_len = len(self._buffer) - len(stripped)
                if stripped.startswith(_OPEN_TAG):
                    self._in_thinking = True
                    self._seen_thinking = True
                    self._buffer = stripped[len(_OPEN_TAG) :]
                    continue
                # If we have enough buffered text to be sure it's not a (partial) open
                # tag, or the buffer contains a character that couldn't lead into the
                # tag, flush it as plain text and stop looking for thinking forever.
                if self._could_be_partial_open_tag(stripped):
                    # Wait for more chunks before deciding.
                    return out
                out.text += self._buffer
                self._buffer = ""
                self._finished_thinking_phase = True
                return out

            if self._in_thinking:
                close_idx = self._buffer.find(_CLOSE_TAG)
                if close_idx == -1:
                    # Emit everything except a possibly-partial closing tag at the end.
                    safe_len = self._safe_emit_length(self._buffer, _CLOSE_TAG)
                    out.reasoning += self._buffer[:safe_len]
                    self._buffer = self._buffer[safe_len:]
                    return out
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
        """Call at end-of-stream to flush any remaining buffered content as plain text."""
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
        if not stripped:
            return True
        return _OPEN_TAG.startswith(stripped) and len(stripped) < len(_OPEN_TAG)

    @staticmethod
    def _safe_emit_length(buffer: str, tag: str) -> int:
        """Return how much of `buffer` is safe to emit without possibly splitting `tag`."""
        max_check = min(len(tag) - 1, len(buffer))
        for i in range(max_check, 0, -1):
            if tag.startswith(buffer[-i:]):
                return len(buffer) - i
        return len(buffer)
