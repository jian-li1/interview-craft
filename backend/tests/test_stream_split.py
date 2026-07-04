"""ThinkingStreamSplitter: routes <thinking>...</thinking> content to reasoning, rest to text.

Covers the provider-agnostic stream-splitting convention from spec 02 §3, including
chunk boundaries that split tags mid-way.
"""

from __future__ import annotations

from app.agent.stream_split import ThinkingStreamSplitter


def _feed_all(splitter: ThinkingStreamSplitter, chunks: list[str]):
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
    splitter = ThinkingStreamSplitter()
    reasoning, text = _feed_all(splitter, ["<thinking>plan the approach</thinking>Here is the answer."])
    assert reasoning == "plan the approach"
    assert text == "Here is the answer."


def test_no_thinking_block_all_text():
    splitter = ThinkingStreamSplitter()
    reasoning, text = _feed_all(splitter, ["Just a plain answer with no thinking block."])
    assert reasoning == ""
    assert text == "Just a plain answer with no thinking block."


def test_thinking_tag_split_across_chunks():
    splitter = ThinkingStreamSplitter()
    chunks = ["<thi", "nking>", "reasoning here", "</thi", "nking>", "final answer"]
    reasoning, text = _feed_all(splitter, chunks)
    assert reasoning == "reasoning here"
    assert text == "final answer"


def test_close_tag_split_across_many_tiny_chunks():
    splitter = ThinkingStreamSplitter()
    full = "<thinking>abc</thinking>xyz"
    # Feed one character at a time to stress-test the incremental buffering.
    chunks = list(full)
    reasoning, text = _feed_all(splitter, chunks)
    assert reasoning == "abc"
    assert text == "xyz"


def test_leading_whitespace_before_thinking_tag():
    splitter = ThinkingStreamSplitter()
    reasoning, text = _feed_all(splitter, ["   <thinking>plan</thinking>answer"])
    assert reasoning == "plan"
    assert text == "answer"


def test_unclosed_thinking_block_flushed_as_reasoning():
    splitter = ThinkingStreamSplitter()
    reasoning, text = _feed_all(splitter, ["<thinking>never closes"])
    assert reasoning == "never closes"
    assert text == ""


def test_empty_thinking_block():
    splitter = ThinkingStreamSplitter()
    reasoning, text = _feed_all(splitter, ["<thinking></thinking>answer only"])
    assert reasoning == ""
    assert text == "answer only"


def test_text_starting_with_angle_bracket_not_thinking():
    splitter = ThinkingStreamSplitter()
    reasoning, text = _feed_all(splitter, ["<b>bold not thinking</b>"])
    assert reasoning == ""
    assert text == "<b>bold not thinking</b>"
