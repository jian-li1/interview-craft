"""Heuristic server-side linter for Mermaid diagram blocks embedded in section markdown.

Per `visual_guidelines.md`, the frontend renders ```mermaid fenced blocks via the
`mermaid` library; broken syntax renders as an ugly error box in the UI. This module is
a pure-function, stdlib-only (re) heuristic pass run at write time (see
`app/agent/tools/curriculum.py`'s `WriteSectionTool`/`UpdateSectionTool`) so the ReAct
loop can self-correct on a precise error observation instead of the user seeing a
broken diagram after the fact.

Deliberately conservative: a false positive on valid Mermaid is worse than a missed
bug, since it can loop the agent retrying content that was actually fine. Only
`flowchart`/`graph` bodies get the deeper bracket/quote/label checks below — other
grammars (sequenceDiagram, mindmap, etc.) differ too much to lint safely beyond the
diagram-type check.
"""

from __future__ import annotations

import re

# Diagram-type keywords Mermaid recognizes as the first line of a block. Matched
# case-sensitively against the real syntax (Mermaid keywords are case-sensitive).
_KNOWN_DIAGRAM_TYPES = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "mindmap",
    "classDiagram",
    "stateDiagram-v2",
    "stateDiagram",
    "erDiagram",
    "gantt",
    "pie",
    "journey",
    "timeline",
    "quadrantChart",
    "gitGraph",
)

# Only these diagram types get the deeper flowchart-body checks (brackets/quotes/labels).
_FLOWCHART_TYPES = ("flowchart", "graph")

# Line prefixes with their own special syntax — still quote/bracket-checked, but
# exempted from the unquoted-label scan (they aren't node/edge label definitions).
_SPECIAL_LINE_PREFIXES = (
    "classDef", "class", "style", "linkStyle", "click", "subgraph", "direction", "end",
)

# Label delimiter (open, close) pairs, longest/most-specific first so multi-char shapes
# (e.g. `[[...]]` double-bracket subroutine shape) aren't mis-split by `[...]`.
_LABEL_DELIMITERS = (
    ("[[", "]]"),
    ("([", "])"),
    ("[(", ")]"),
    ("((", "))"),
    ("{{", "}}"),
    ("[/", "/]"),
    ("[\\", "\\]"),
    ("[", "]"),
    ("(", ")"),
    ("{", "}"),
)

# Characters that make an unquoted label risky (the #1 real-world Mermaid parse failure).
_RISKY_LABEL_CHARS = set('()[]{}";')


def extract_mermaid_blocks(markdown: str) -> list[str]:
    """Extract the contents of every ```mermaid fenced code block in `markdown`.

    Handles fences with trailing whitespace after the ```mermaid marker. If a
    ```mermaid fence is opened but never closed, the rest of the document (from the
    fence to EOF) is still returned as a block — `lint_markdown_mermaid` separately
    detects and reports the missing closing fence as a lint problem.

    Args:
        markdown (str): The full section markdown to scan.

    Returns:
        list[str]: The raw text content of each mermaid block, in document order
            (not including the fence lines themselves).
    """
    blocks: list[str] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        # Match a fence opener allowing trailing whitespace after "mermaid".
        if re.match(r"^```mermaid\s*$", lines[i]):
            start = i + 1
            end = start
            closed = False
            while end < len(lines):
                if lines[end].strip() == "```":
                    closed = True
                    break
                end += 1
            blocks.append("\n".join(lines[start:end]))
            # Unclosed fence: stop scanning here since the rest of the doc was consumed
            # as this block's content (mirrors what a real parser would attempt).
            if not closed:
                break
            i = end + 1
        else:
            i += 1
    return blocks


def _first_content_line(source: str) -> str | None:
    """Return the first non-empty, non-`%%`-comment line of a mermaid block body.

    Args:
        source (str): The raw mermaid block content.

    Returns:
        str | None: The stripped first meaningful line, or None if the block is
            entirely empty/comments.
    """
    for line in source.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("%%"):
            return stripped
    return None


def _diagram_type(first_line: str) -> str | None:
    """Match `first_line` against the known Mermaid diagram-type keywords.

    Args:
        first_line (str): The stripped first content line of a mermaid block.

    Returns:
        str | None: The matched keyword (e.g. "flowchart"), or None if `first_line`
            doesn't start with any known diagram type.
    """
    for keyword in _KNOWN_DIAGRAM_TYPES:
        # Word-boundary check so e.g. "graph" doesn't spuriously match "graphite".
        if first_line == keyword or first_line.startswith(keyword + " "):
            return keyword
    return None


def _check_quotes_and_brackets(line: str) -> list[str]:
    """Check one line for an unterminated quote or unbalanced bracket nesting.

    Walks the line char by char tracking whether we're inside a double-quoted string;
    bracket counting only applies outside quotes (a `(` inside a quoted label is fine).

    Args:
        line (str): A single line from a flowchart/graph body (comments already
            filtered out by the caller).

    Returns:
        list[str]: Human-readable problem strings for this line (empty if clean).
    """
    problems: list[str] = []
    in_quotes = False
    balance = {"[": 0, "(": 0, "{": 0}
    closers = {"]": "[", ")": "(", "}": "{"}
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
        elif not in_quotes:
            if ch in balance:
                balance[ch] += 1
            elif ch in closers:
                balance[closers[ch]] -= 1
    if in_quotes:
        problems.append(f"unterminated quote on line: {line.strip()!r}")
    if any(count != 0 for count in balance.values()):
        problems.append(f"unbalanced bracket(s) on line: {line.strip()!r}")
    return problems


def _find_label_spans(line: str) -> list[str]:
    """Extract every node-label / edge-label span from a flowchart/graph line.

    Recognizes shape delimiters (`[[...]]`, `([...])`, `[(...)]`, `((...))`, `{{...}}`,
    `[/.../]`, `[\\...\\]`, `[...]`, `(...)`, `{...}`) and edge labels (`|...|`). Longest
    delimiter pairs are tried first so multi-char shapes aren't mis-split by a shorter
    pattern (e.g. `((Start))` isn't read as `(` + `(Start)` + `)`).

    Args:
        line (str): A single flowchart/graph body line.

    Returns:
        list[str]: The raw text found strictly between each matched delimiter pair, in
            the order encountered.
    """
    spans: list[str] = []
    # Edge labels: |label text| — order-independent of node shapes, scan first.
    spans.extend(re.findall(r"\|([^|]*)\|", line))

    # Node-shape labels: try longest/most-specific delimiters first via alternation,
    # ordered so e.g. "[[" is attempted before "[". re.escape guards regex metachars.
    alternation = "|".join(
        re.escape(open_) + r"(.*?)" + re.escape(close) for open_, close in _LABEL_DELIMITERS
    )
    pattern = re.compile(alternation)
    pos = 0
    while pos < len(line):
        match = pattern.search(line, pos)
        if not match:
            break
        # Whichever alternative matched, exactly one group is non-None.
        label = next(g for g in match.groups() if g is not None)
        spans.append(label)
        pos = match.end()
    return spans


def _check_unquoted_labels(line: str) -> list[str]:
    """Flag labels on a flowchart/graph line that contain risky chars but aren't quoted.

    A label counts as quoted when, after trimming whitespace, it starts and ends with
    `"`. Risky unquoted chars: `( ) [ ] { } " ;` — these are the characters most likely
    to break Mermaid's flowchart grammar when left unquoted (e.g. `A[Review (Optional)]`).

    Args:
        line (str): A single flowchart/graph body line (not a `classDef`/`class`/
            `style`/etc. special-syntax line — caller skips those before calling this).

    Returns:
        list[str]: One problem string per offending label, naming the label and
            suggesting how to quote it.
    """
    problems: list[str] = []
    for label in _find_label_spans(line):
        trimmed = label.strip()
        if not trimmed:
            continue
        is_quoted = trimmed.startswith('"') and trimmed.endswith('"')
        if is_quoted:
            continue
        if any(ch in _RISKY_LABEL_CHARS for ch in trimmed):
            problems.append(
                f'unquoted label {trimmed!r} contains risky characters — use "{trimmed}" instead'
            )
    return problems


def lint_mermaid_block(source: str) -> list[str]:
    """Run heuristic syntax checks over a single mermaid block's content.

    Args:
        source (str): The raw content of one ```mermaid fenced block (fence lines
            excluded).

    Returns:
        list[str]: Human-readable problem strings, empty when the block passes all
            checks. Only the diagram-type check runs for non-flowchart/graph types;
            the deeper bracket/quote/label checks are flowchart/graph-only, since other
            Mermaid grammars differ too much to lint safely.
    """
    first_line = _first_content_line(source)
    if first_line is None:
        return ["block is empty (no diagram type declared)"]

    diagram_type = _diagram_type(first_line)
    if diagram_type is None:
        # Report just the first token so the message stays short and readable.
        first_token = first_line.split()[0] if first_line.split() else first_line
        return [f"unknown diagram type {first_token!r} on first line: {first_line!r}"]

    if diagram_type not in _FLOWCHART_TYPES:
        # Non-flowchart grammars (sequenceDiagram, mindmap, etc.) aren't body-linted.
        return []

    problems: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        # Quote/bracket balance checks run on every line, including special syntax.
        problems.extend(_check_quotes_and_brackets(line))
        # Unquoted-label scan is skipped for special-syntax lines (classDef/class/
        # style/etc.) — they have their own grammar, not node/edge label definitions.
        if stripped.startswith(_SPECIAL_LINE_PREFIXES):
            continue
        problems.extend(_check_unquoted_labels(line))
    return problems


def lint_markdown_mermaid(markdown: str) -> str | None:
    """Extract and lint every mermaid block in `markdown`, combining results into one message.

    This is the entry point called from `write_section`/`update_section`. The returned
    message is fed verbatim into an LLM-facing error observation, so it identifies each
    broken block by index and first line, and quotes the offending line/label so the
    model can locate and fix it without re-reading the whole document.

    Args:
        markdown (str): The full section markdown to check (may contain zero or more
            mermaid blocks).

    Returns:
        str | None: None when every block passes (or there are no mermaid blocks at
            all); otherwise one combined human-readable message enumerating each
            broken block's problems.
    """
    # Detect an unclosed fence up front — extract_mermaid_blocks still returns the
    # trailing content as a block, but we need to flag the missing closer explicitly.
    fence_opens = len(re.findall(r"^```mermaid\s*$", markdown, flags=re.MULTILINE))
    fence_closes_after_open = markdown.count("```") - fence_opens
    unclosed = fence_closes_after_open < fence_opens

    blocks = extract_mermaid_blocks(markdown)
    messages: list[str] = []
    for idx, block in enumerate(blocks, start=1):
        problems = lint_mermaid_block(block)
        # The last block absorbs the unclosed-fence problem, since extraction treated
        # the remainder of the document as its content.
        if unclosed and idx == len(blocks):
            problems = [*problems, "mermaid fence opened with ```mermaid was never closed with ```"]
        if problems:
            first_line = _first_content_line(block) or "(empty)"
            problem_text = "; ".join(problems)
            messages.append(f"block {idx} (starts {first_line!r}): {problem_text}")

    if not messages:
        return None
    return "Mermaid lint found problems: " + " | ".join(messages)
