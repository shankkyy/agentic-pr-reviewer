"""Structured JSON logging with request/review correlation IDs and secret redaction.

Logs never include diff contents or model output. Workflow code logs stage names,
durations, sizes, and error codes only.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
review_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("review_id", default=None)

_REDACT_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(x-api-key[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9._\-]{8,}"),
]

_secret_values: set[str] = set()


def register_secret(value: str | None) -> None:
    """Register a runtime secret so any occurrence is redacted from logs and error messages."""
    if value and len(value) >= 6:
        _secret_values.add(value)


def redact(text: str) -> str:
    out = text
    for secret in sorted(_secret_values, key=len, reverse=True):
        out = out.replace(secret, "[REDACTED]")
    for pattern in _REDACT_PATTERNS:
        out = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", out)
    return out


_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": redact(record.getMessage()),
        }
        request_id = request_id_var.get()
        review_id = review_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        if review_id:
            payload["review_id"] = review_id
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            # Keep only the exception type; tracebacks may echo source code or secrets.
            payload["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger("apr")
    if getattr(root, "_apr_configured", False):
        root.setLevel(level)
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    root._apr_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"apr.{name}")
