"""Input validation for uploaded or pasted diffs (stdlib only).

Filenames and extensions are never trusted: the decision to accept an input
is based on its size, encoding, and parsed diff structure only.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.services.diff_parser import DiffParseError, ParsedDiff, parse_diff


class InputValidationError(ValueError):
    """Input rejected. `code` is a stable machine-readable identifier; `message` is user-safe."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedDiff:
    text: str
    parsed: ParsedDiff
    size_bytes: int
    sha256: str
    display_name: str


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_display_name(name: str | None) -> str:
    """Reduce a client-supplied name to a short, printable, basename-only label. Used for display only."""
    if not name:
        return "pasted-diff"
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = _CONTROL.sub("", base).strip()[:120]
    return base or "uploaded-diff"


def validate_diff_bytes(
    data: bytes,
    *,
    max_bytes: int,
    max_files: int,
    max_hunks: int,
    display_name: str | None = None,
) -> ValidatedDiff:
    """Validate raw bytes from an upload. Enforces size, encoding, and structure."""
    if len(data) == 0:
        raise InputValidationError("empty_diff", "The diff is empty.")
    if len(data) > max_bytes:
        raise InputValidationError(
            "payload_too_large",
            f"The diff is {len(data)} bytes; the limit is {max_bytes} bytes.",
            status_code=413,
        )
    if b"\x00" in data:
        raise InputValidationError("binary_content", "The input contains NUL bytes and is not a text diff.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputValidationError("invalid_encoding", "The diff must be UTF-8 encoded text.") from exc
    return validate_diff_text(
        text,
        max_bytes=max_bytes,
        max_files=max_files,
        max_hunks=max_hunks,
        display_name=display_name,
    )


def validate_diff_text(
    text: str,
    *,
    max_bytes: int,
    max_files: int,
    max_hunks: int,
    display_name: str | None = None,
) -> ValidatedDiff:
    if not text or not text.strip():
        raise InputValidationError("empty_diff", "The diff is empty.")
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        raise InputValidationError(
            "payload_too_large",
            f"The diff is {len(encoded)} bytes; the limit is {max_bytes} bytes.",
            status_code=413,
        )
    if "\x00" in text:
        raise InputValidationError("binary_content", "The input contains NUL bytes and is not a text diff.")
    try:
        parsed = parse_diff(text, max_files=max_files, max_hunks=max_hunks)
    except DiffParseError as exc:
        message = str(exc)
        code = "too_many_files" if "files" in message and "more than" in message else (
            "too_many_hunks" if "hunks" in message and "more than" in message else "malformed_diff"
        )
        raise InputValidationError(code, f"Malformed or unsupported diff: {message}") from exc
    return ValidatedDiff(
        text=text,
        parsed=parsed,
        size_bytes=len(encoded),
        sha256=hashlib.sha256(encoded).hexdigest(),
        display_name=sanitize_display_name(display_name),
    )
