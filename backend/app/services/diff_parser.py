"""Unified diff parser (stdlib only).

Parses git-style and plain unified diffs into dataclasses. Hunk bodies are
consumed by the counts declared in each hunk header, so truncated or
inconsistent hunks are rejected instead of silently accepted.

Line mapping: a diagnostic can be mapped to a changed line only when its
new-file line number is an *added* line inside a parsed hunk. Context lines
and deleted lines are never reported as changed lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

FileStatus = Literal["added", "deleted", "modified", "renamed", "binary"]

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
MAX_PATH_LENGTH = 1024


class DiffParseError(ValueError):
    """Raised when a diff is malformed. The message is safe to show to users."""


@dataclass(frozen=True)
class HunkLine:
    kind: Literal["context", "added", "deleted"]
    text: str
    old_no: int | None
    new_no: int | None


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    section: str
    lines: list[HunkLine] = field(default_factory=list)


@dataclass
class FileDiff:
    old_path: str | None
    new_path: str | None
    status: FileStatus
    hunks: list[Hunk] = field(default_factory=list)
    similarity: int | None = None
    is_binary: bool = False

    @property
    def path(self) -> str:
        """Path of the file after the change (old path for deletions)."""
        return self.new_path or self.old_path or ""

    @property
    def added_line_numbers(self) -> set[int]:
        return {
            line.new_no
            for hunk in self.hunks
            for line in hunk.lines
            if line.kind == "added" and line.new_no is not None
        }

    def added_text(self) -> dict[int, str]:
        return {
            line.new_no: line.text
            for hunk in self.hunks
            for line in hunk.lines
            if line.kind == "added" and line.new_no is not None
        }


@dataclass
class LineMapping:
    mapped: bool
    reason: str


@dataclass
class ParsedDiff:
    files: list[FileDiff]
    warnings: list[str] = field(default_factory=list)

    def get_file(self, path: str) -> FileDiff | None:
        for f in self.files:
            if f.path == path:
                return f
        return None

    def map_line(self, path: str, line: int) -> LineMapping:
        """Return whether `line` (new-file numbering) is an added line of `path`."""
        f = self.get_file(path)
        if f is None:
            return LineMapping(False, "file is not part of the diff")
        if f.is_binary:
            return LineMapping(False, "binary file has no line-level changes")
        if f.status == "deleted":
            return LineMapping(False, "file was deleted; no new-side lines")
        if line in f.added_line_numbers:
            return LineMapping(True, "line is an added line in a parsed hunk")
        return LineMapping(False, "line is not an added line in the diff")


def _strip_prefix(raw: str, prefix: str) -> str | None:
    raw = raw.split("\t", 1)[0].strip()
    if raw == "/dev/null":
        return None
    if raw.startswith(prefix):
        raw = raw[len(prefix):]
    return raw


def _parse_git_header(line: str) -> tuple[str, str]:
    """Parse `diff --git a/x b/y`. Paths with spaces are resolved via the ---/+++ lines later."""
    rest = line[len("diff --git ") :]
    parts = rest.split(" b/", 1)
    if len(parts) != 2 or not rest.startswith("a/"):
        raise DiffParseError(f"unrecognized git header: {line[:120]!r}")
    return parts[0][2:], parts[1]


def parse_diff(text: str, max_files: int = 50, max_hunks: int = 500) -> ParsedDiff:
    """Parse a unified diff into a ParsedDiff.

    Raises DiffParseError for malformed input, too many files, or too many hunks.
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    files: list[FileDiff] = []
    warnings: list[str] = []
    current: FileDiff | None = None
    total_hunks = 0
    pending_git: tuple[str, str] | None = None
    i = 0
    n = len(lines)

    def start_file(old: str | None, new: str | None, status: FileStatus) -> FileDiff:
        nonlocal current
        if len(files) >= max_files:
            raise DiffParseError(f"diff contains more than {max_files} files")
        current = FileDiff(old_path=old, new_path=new, status=status)
        files.append(current)
        return current

    while i < n:
        line = lines[i]
        lineno = i + 1
        if line.startswith("diff --git "):
            a_path, b_path = _parse_git_header(line)
            pending_git = (a_path, b_path)
            current = start_file(a_path, b_path, "modified")
            i += 1
            continue
        if current is not None and (
            line.startswith("new file mode")
            or line.startswith("deleted file mode")
            or line.startswith("rename from ")
            or line.startswith("rename to ")
            or line.startswith("similarity index ")
            or line.startswith("index ")
            or line.startswith("old mode ")
            or line.startswith("new mode ")
            or line.startswith("copy from ")
            or line.startswith("copy to ")
        ):
            if line.startswith("new file mode"):
                current.status = "added"
                current.old_path = None
            elif line.startswith("deleted file mode"):
                current.status = "deleted"
                current.new_path = None
            elif line.startswith("rename from "):
                current.status = "renamed"
                current.old_path = _validated_path(line[len("rename from ") :], lineno)
            elif line.startswith("rename to "):
                current.status = "renamed"
                current.new_path = _validated_path(line[len("rename to ") :], lineno)
            elif line.startswith("similarity index "):
                try:
                    current.similarity = int(line[len("similarity index ") :].rstrip("%"))
                except ValueError as exc:
                    raise DiffParseError(f"line {lineno}: invalid similarity index") from exc
            i += 1
            continue
        if current is not None and (line.startswith("Binary files ") or line.startswith("GIT binary patch")):
            current.is_binary = True
            current.status = "binary" if current.status == "modified" else current.status
            if line.startswith("GIT binary patch"):
                # Skip the binary payload until the next file header.
                i += 1
                while i < n and not lines[i].startswith("diff --git ") and not lines[i].startswith("--- "):
                    i += 1
                continue
            i += 1
            continue
        if line.startswith("--- "):
            old_raw = _strip_prefix(line[4:], "a/")
            if i + 1 >= n or not lines[i + 1].startswith("+++ "):
                raise DiffParseError(f"line {lineno}: '---' header not followed by '+++'")
            new_raw = _strip_prefix(lines[i + 1][4:], "b/")
            old_p = _validated_path(old_raw, lineno) if old_raw else None
            new_p = _validated_path(new_raw, lineno) if new_raw else None
            if pending_git is not None and current is not None:
                # Completes the file opened by a `diff --git` header.
                if old_p is None:
                    current.status = "added"
                    current.old_path = None
                elif new_p is None:
                    current.status = "deleted"
                    current.new_path = None
                else:
                    current.old_path = old_p
                    current.new_path = new_p
            else:
                # Plain unified diff: each ---/+++ pair starts a new file.
                status: FileStatus = "modified"
                if old_p is None:
                    status = "added"
                elif new_p is None:
                    status = "deleted"
                current = start_file(old_p, new_p, status)
            pending_git = None
            i += 2
            continue
        if line.startswith("@@"):
            if current is None:
                raise DiffParseError(f"line {lineno}: hunk header without a file header")
            m = HUNK_RE.match(line)
            if not m:
                raise DiffParseError(f"line {lineno}: malformed hunk header")
            total_hunks += 1
            if total_hunks > max_hunks:
                raise DiffParseError(f"diff contains more than {max_hunks} hunks")
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            hunk = Hunk(old_start, old_count, new_start, new_count, m.group(5).strip())
            old_no, new_no = old_start, new_start
            old_left, new_left = old_count, new_count
            i += 1
            while (old_left > 0 or new_left > 0) and i < n:
                body = lines[i]
                body_lineno = i + 1
                if body.startswith("\\"):
                    i += 1
                    continue
                # Next file/hunk header means this hunk's body was cut short.
                if body.startswith("diff --git ") or body.startswith("--- ") or (
                    body.startswith("@@") and HUNK_RE.match(body)
                ):
                    break
                prefix = body[:1]
                text = body[1:]
                if body == "":
                    # Some tools strip the single space of empty context lines.
                    prefix, text = " ", ""
                if prefix == " ":
                    if old_left <= 0 or new_left <= 0:
                        raise DiffParseError(f"line {body_lineno}: hunk line count mismatch")
                    hunk.lines.append(HunkLine("context", text, old_no, new_no))
                    old_no += 1
                    new_no += 1
                    old_left -= 1
                    new_left -= 1
                elif prefix == "-":
                    if old_left <= 0:
                        raise DiffParseError(f"line {body_lineno}: hunk line count mismatch")
                    hunk.lines.append(HunkLine("deleted", text, old_no, None))
                    old_no += 1
                    old_left -= 1
                elif prefix == "+":
                    if new_left <= 0:
                        raise DiffParseError(f"line {body_lineno}: hunk line count mismatch")
                    hunk.lines.append(HunkLine("added", text, None, new_no))
                    new_no += 1
                    new_left -= 1
                else:
                    raise DiffParseError(f"line {body_lineno}: unexpected character in hunk body")
                i += 1
            if old_left != 0 or new_left != 0:
                got_old, got_new = old_count - old_left, new_count - new_left
                raise DiffParseError(
                    f"line {lineno}: hunk ended before its declared line counts (truncated diff): "
                    f"@@ promised {old_count} old / {new_count} new lines, "
                    f"found {got_old} old / {got_new} new — fix the @@ counts or paste the full hunk"
                )
            while i < n and lines[i].startswith("\\"):
                i += 1
            current.hunks.append(hunk)
            continue
        if line.strip() == "":
            i += 1
            continue
        # Unrecognized header-level line (e.g. commit metadata). Tolerated, not analyzed.
        i += 1

    if not files:
        raise DiffParseError("no file headers found; input does not look like a unified diff")
    for f in files:
        if not f.hunks and not f.is_binary and f.status not in ("renamed", "added", "deleted"):
            warnings.append(f"{f.path}: no hunks; nothing to analyze")
        if f.status == "renamed" and f.hunks:
            warnings.append(f"{f.path}: renamed file with content changes")
    return ParsedDiff(files=files, warnings=warnings)


_FORBIDDEN_CHARS = re.compile(r"[\x00-\x1f\x7f\\]")


def _validated_path(raw: str | None, lineno: int) -> str:
    """Validate a repository-relative path taken from the diff. Rejects traversal and absolute paths."""
    if raw is None:
        raise DiffParseError(f"line {lineno}: missing path")
    if not raw or len(raw) > MAX_PATH_LENGTH:
        raise DiffParseError(f"line {lineno}: path is empty or too long")
    if _FORBIDDEN_CHARS.search(raw):
        raise DiffParseError(f"line {lineno}: path contains control characters or backslashes")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise DiffParseError(f"line {lineno}: absolute paths are not allowed")
    parts = raw.split("/")
    if any(p in ("..", ".") for p in parts) or any(p == "" for p in parts):
        raise DiffParseError(f"line {lineno}: path traversal or empty segment rejected")
    if parts[0] == ".git" or ".git" in parts:
        raise DiffParseError(f"line {lineno}: paths inside .git are not allowed")
    return raw
