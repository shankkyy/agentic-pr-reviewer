"""Builds analyzable Python snippets from diff hunks (stdlib only).

A diff is not a complete module. For each hunk we keep only the new-side lines
(context + added), preserving an exact map from snippet line numbers back to
new-file line numbers. A snippet is analyzed only if it parses in isolation;
otherwise the hunk is reported as "insufficient context" and skipped.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from app.services.diff_parser import FileDiff, ParsedDiff

PYTHON_SUFFIXES = (".py", ".pyi")


@dataclass
class Snippet:
    file_path: str
    hunk_index: int
    text: str
    # snippet line number (1-based) -> new-file line number
    line_map: dict[int, int] = field(default_factory=dict)
    added_new_lines: set[int] = field(default_factory=set)
    excerpts: dict[int, str] = field(default_factory=dict)  # new line -> text of that line
    parseable: bool = True
    skip_reason: str | None = None

    @property
    def has_added_lines(self) -> bool:
        return bool(self.added_new_lines)


@dataclass
class PythonContext:
    snippets: list[Snippet]
    python_files: list[str]
    unsupported_files: list[str]
    limitations: list[str]


def is_python_candidate(path: str) -> bool:
    """Routing hint only. The extension is never trusted to prove the content is Python."""
    return path.lower().endswith(PYTHON_SUFFIXES)


def build_snippet(file: FileDiff, hunk_index: int) -> Snippet:
    hunk = file.hunks[hunk_index]
    snippet_lines: list[str] = []
    line_map: dict[int, int] = {}
    added: set[int] = set()
    excerpts: dict[int, str] = {}
    for hl in hunk.lines:
        if hl.kind == "deleted" or hl.new_no is None:
            continue
        snippet_lines.append(hl.text)
        line_map[len(snippet_lines)] = hl.new_no
        excerpts[hl.new_no] = hl.text
        if hl.kind == "added":
            added.add(hl.new_no)
    text = "\n".join(snippet_lines) + "\n"
    snippet = Snippet(
        file_path=file.path,
        hunk_index=hunk_index,
        text=text,
        line_map=line_map,
        added_new_lines=added,
        excerpts=excerpts,
    )
    if not added:
        snippet.skip_reason = "hunk has no added lines"
        return snippet
    try:
        ast.parse(text)
    except SyntaxError as exc:
        snippet.parseable = False
        snippet.skip_reason = (
            "insufficient context: hunk is not parseable in isolation "
            f"(line {exc.lineno}: {exc.msg})"
        )
    except (ValueError, MemoryError, RecursionError):
        snippet.parseable = False
        snippet.skip_reason = "insufficient context: hunk could not be parsed safely"
    return snippet


def build_python_context(parsed: ParsedDiff) -> PythonContext:
    snippets: list[Snippet] = []
    python_files: list[str] = []
    unsupported: list[str] = []
    limitations: list[str] = []
    for file in parsed.files:
        if file.is_binary or file.status == "deleted":
            unsupported.append(file.path)
            continue
        if not is_python_candidate(file.path):
            unsupported.append(file.path)
            continue
        python_files.append(file.path)
        for idx in range(len(file.hunks)):
            snippet = build_snippet(file, idx)
            if snippet.has_added_lines or snippet.skip_reason is None:
                snippets.append(snippet)
    if any(not s.parseable for s in snippets):
        limitations.append(
            "Some hunks are not parseable in isolation and were skipped for static analysis "
            "(insufficient context)."
        )
    limitations.append(
        "Analysis sees only changed hunks plus surrounding context lines. Names defined outside "
        "the hunks are unknown, so undefined-name checks are disabled."
    )
    return PythonContext(
        snippets=snippets,
        python_files=python_files,
        unsupported_files=unsupported,
        limitations=limitations,
    )
