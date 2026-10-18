"""Shared stdlib diagnostic record produced by deterministic analyzers (stdlib only).

Analyzers return RawDiagnostic objects. The finding builder converts them into
the Pydantic Finding schema. Keeping this layer dependency-free lets the
analyzers be tested without installing the web stack.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawDiagnostic:
    tool: str  # "ruff", "bandit", or "ast"
    rule_id: str  # original identifier, e.g. "S608", "B608", "AST-SQL001"
    title: str
    message: str
    category: str  # "correctness" | "security" | "performance" | "testing"
    severity: str  # "critical" | "high" | "medium" | "low" | "info"
    confidence: float
    file_path: str
    line: int  # new-file line number (already mapped to an added line)
    excerpt: str
