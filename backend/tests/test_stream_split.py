"""ThinkingStreamSplitter: routes <thinking>...</thinking> content to reasoning, rest to text.

Covers the provider-agnostic stream-splitting convention from spec 02 §3, including
chunk boundaries that split tags mid-way.
"""

from __future__ import annotations

from app.agent.stream_split import ThinkingStreamSplitter


def _feed_all(splitter: ThinkingStreamSplitter, chunks: list[str]):
    """Feed a sequence of raw text chunks through a splitter and collect the results.

    Args:
        splitter (ThinkingStreamSplitter): The splitter instance under test.
        chunks (list[str]): Raw text chunks to feed in order, simulating an LLM stream.

    Returns:
        tuple[str, str]: The concatenated `(reasoning, text)` accumulated across all
            `feed()` calls plus the final `flush()`.
    """
    reasoning = ""
    text = ""
    for chunk in chunks:
        delta = splitter.feed(chunk)
        reasoning += delta.reasoning
        text += delta.text
    final = splitter.flush()
    reasoning += final.reasoning
    text += final.text
    return reasoning, text


def test_simple_thinking_then_text_single_chunk():
    """Verify a single chunk containing a full <thinking> block splits cleanly into
    reasoning and trailing user-facing text.
    """
    splitter = ThinkingStreamSplitter()
    reasoning, text = _feed_all(splitter, ["<thinking>plan the approach</thinking>Here is the answer."])
    assert reasoning == "plan the approach"
    assert text == "Here is the answer."


def test_no_thinking_block_all_text():
    """Verify text with no <thinking> tag at all is routed entirely to `text`."""
    splitter = ThinkingStreamSplitter()
    reasoning, text = _feed_all(splitter, ["Just a plain answer with no thinking block."])
    assert reasoning == ""
    assert text == "Just a plain answer with no thinking block."


def test_thinking_tag_split_across_chunks():
    """Verify the splitter correctly buffers and detects tags even when the opening
    and closing <thinking> tags are each split across multiple stream chunks.
    """
    splitter = ThinkingStreamSplitter()
    chunks = ["<thi", "nking>", "reasoning here", "</thi", "nking>", "final answer"]
    reasoning, text = _feed_all(splitter, chunks)
    assert reasoning == "reasoning here"
    assert text == "final answer"


def test_close_tag_split_across_many_tiny_chunks():
    """Verify the splitter handles the extreme case of one-character-at-a-time chunks
    without losing or misrouting any content."""
    splitter = ThinkingStreamSplitter()
    full = "<thinking>abc</thinking>xyz"
    # Feed one character at a time to stress-test the incremental buffering.
    chunks = list(full)
    reasoning, text = _feed_all(splitter, chunks)
    assert reasoning == "abc"
    assert text == "xyz"


def test_leading_whitespace_before_thinking_tag():
    """Verify leading whitespace before the opening <thinking> tag doesn't prevent
    detection of the tag."""
    splitter = ThinkingStreamSplitter()
    reasoning, text = _feed_all(splitter, ["   <thinking>plan</thinking>answer"])
    assert reasoning == "plan"
    assert text == "answer"


def test_unclosed_thinking_block_flushed_as_reasoning():
    """Verify a <thinking> block that's never closed is still flushed as reasoning
    (rather than lost or misrouted to text) when the stream ends."""
    splitter = ThinkingStreamSplitter()
    reasoning, text = _feed_all(splitter, ["<thinking>never closes"])
    assert reasoning == "never closes"
    assert text == ""


def test_empty_thinking_block():
    """Verify an empty <thinking></thinking> block yields empty reasoning and the
    remaining text is routed correctly."""
    splitter = ThinkingStreamSplitter()
    reasoning, text = _feed_all(splitter, ["<thinking></thinking>answer only"])
    assert reasoning == ""
    assert text == "answer only"


def test_text_starting_with_angle_bracket_not_thinking():
    """Verify ordinary markup-like text (e.g. an HTML-ish tag) that isn't a <thinking>
    tag is not misdetected and passes through entirely as text."""
    splitter = ThinkingStreamSplitter()
    reasoning, text = _feed_all(splitter, ["<b>bold not thinking</b>"])
    assert reasoning == ""
    assert text == "<b>bold not thinking</b>"
