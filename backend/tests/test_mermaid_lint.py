"""Heuristic Mermaid syntax linter: extraction, per-block checks, and the combined
markdown-level entry point used by write_section/update_section as a write-time guard.
"""

from __future__ import annotations

from pathlib import Path

from app.agent.mermaid_lint import (
    extract_mermaid_blocks,
    lint_markdown_mermaid,
    lint_mermaid_block,
)

_VISUAL_GUIDELINES_PATH = (
    Path(__file__).parent.parent / "app" / "agent" / "prompts" / "visual_guidelines.md"
)


def _load_visual_guidelines() -> str:
    """Read the real `visual_guidelines.md` prompt file from disk.

    Returns:
        str: The full file content, used to pull out its worked Mermaid examples so
            the linter is tested against the actual prompt file rather than a copy
            that could drift out of sync.
    """
    return _VISUAL_GUIDELINES_PATH.read_text()


def test_visual_guidelines_quoted_flowchart_example_passes():
    """The quoted flowchart example (~line 46-54) in visual_guidelines.md must lint clean."""
    markdown = _load_visual_guidelines()
    blocks = extract_mermaid_blocks(markdown)
    # The quoted flowchart is the first mermaid block in the file.
    quoted_flowchart = blocks[0]
    assert "Phone Screen" in quoted_flowchart
    assert lint_mermaid_block(quoted_flowchart) == []


def test_visual_guidelines_classdef_example_passes():
    """The classDef highlighting example (~line 62-70) in visual_guidelines.md must lint clean."""
    markdown = _load_visual_guidelines()
    blocks = extract_mermaid_blocks(markdown)
    # The classDef example is the second mermaid block in the file.
    classdef_example = blocks[1]
    assert "classDef risk" in classdef_example
    assert lint_mermaid_block(classdef_example) == []


def test_sequence_diagram_body_not_linted_even_with_parens():
    """A sequenceDiagram body with parens in message text passes — only flowchart/graph
    bodies get the deeper bracket/quote/label checks.
    """
    source = (
        "sequenceDiagram\n"
        "    participant A as Candidate (Alice)\n"
        "    A->>B: Hello (this has unbalanced ( parens and [brackets\n"
    )
    assert lint_mermaid_block(source) == []


def test_mindmap_body_not_linted_even_with_parens():
    """A mindmap body with parens in topic text passes — mindmap isn't a flowchart grammar."""
    source = "mindmap\n  root((System Design))\n    Scalability (horizontal scaling)\n"
    assert lint_mermaid_block(source) == []


def test_unknown_diagram_type_fails():
    """A first line that isn't a recognized Mermaid keyword is flagged as unknown."""
    problems = lint_mermaid_block("weirdchart TD\n    A --> B\n")
    assert len(problems) == 1
    assert "unknown diagram type" in problems[0]
    assert "weirdchart" in problems[0]


def test_unquoted_label_with_parens_fails():
    """The canonical failure case: A[Review (Optional)] must be flagged, naming the label."""
    problems = lint_mermaid_block("flowchart TD\n    A[Review (Optional)] --> B\n")
    assert len(problems) == 1
    assert "Review (Optional)" in problems[0]


def test_unbalanced_bracket_fails():
    """A line with a stray unmatched bracket is flagged by name."""
    problems = lint_mermaid_block('flowchart TD\n    A["Start" --> B\n')
    assert any("unbalanced bracket" in p for p in problems)


def test_unterminated_quote_fails():
    """A line with an opening quote that's never closed is flagged."""
    problems = lint_mermaid_block('flowchart TD\n    A["Start] --> B\n')
    assert any("unterminated quote" in p for p in problems)


def test_quoted_label_with_parens_passes():
    """Quoting a label containing parens (per the guardrails) clears the check."""
    problems = lint_mermaid_block('flowchart TD\n    A["Review (Optional)"] --> B["Next"]\n')
    assert problems == []


def test_edge_label_with_quoted_yes_passes():
    """An edge label like |"Yes"| (quoted) must not be flagged."""
    problems = lint_mermaid_block(
        'flowchart TD\n    A["Phone Screen"] --> B{"Pass?"}\n    B -->|"Yes"| C["Onsite"]\n'
    )
    assert problems == []


def test_markdown_with_no_mermaid_blocks_returns_none():
    """Markdown containing no ```mermaid fences returns None (nothing to lint)."""
    assert lint_markdown_mermaid("# Just a heading\n\nSome prose, no diagrams here.\n") is None


def test_unclosed_fence_fails():
    """A ```mermaid fence that's never closed with ``` is reported as a lint problem."""
    markdown = "```mermaid\nflowchart TD\n    A --> B\n"
    message = lint_markdown_mermaid(markdown)
    assert message is not None
    assert "never closed" in message


def test_multiple_blocks_only_second_broken_identifies_block_two():
    """When only the second of two blocks is broken, the combined message names block 2."""
    markdown = (
        "```mermaid\n"
        'flowchart TD\n    A["Good"] --> B["Also Good"]\n'
        "```\n\n"
        "```mermaid\n"
        "flowchart TD\n    A[Bad (Label)] --> B\n"
        "```\n"
    )
    message = lint_markdown_mermaid(markdown)
    assert message is not None
    assert "block 2" in message
    assert "block 1" not in message


def test_valid_markdown_with_mermaid_returns_none():
    """A full markdown doc with a single valid flowchart block returns None."""
    markdown = (
        "## Interview Loop\n\n"
        "```mermaid\n"
        'flowchart TD\n    A["Screen"] --> B["Onsite"]\n'
        "```\n\n"
        "Some trailing prose.\n"
    )
    assert lint_markdown_mermaid(markdown) is None
