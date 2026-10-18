"""Converts analyzer diagnostics and validated model drafts into Finding objects."""

from __future__ import annotations

import hashlib

from app.schemas.enums import Category, Severity, SourceType
from app.schemas.findings import Finding, LLMFindingDraft
from app.services.diagnostics import RawDiagnostic
from app.services.diff_parser import ParsedDiff

# Remediation guidance for deterministic rules. Unknown rules get a generic instruction.
REMEDIATION_BY_RULE: dict[str, str] = {
    "AST-SQL001": "Pass values as bound parameters (e.g. `cursor.execute(sql, (value,))`) instead of building the SQL string.",
    "S608": "Pass values as bound parameters instead of building the SQL string with f-strings, %, or concatenation.",
    "B608": "Pass values as bound parameters instead of building the SQL string with f-strings, %, or concatenation.",
    "AST-DESER001": "Do not deserialize untrusted data with pickle or marshal; use JSON or another data-only format.",
    "S301": "Do not deserialize untrusted data with pickle; use JSON or another data-only format.",
    "B301": "Do not deserialize untrusted data with pickle; use JSON or another data-only format.",
    "AST-DESER002": "Use `yaml.safe_load` or pass `Loader=yaml.SafeLoader`.",
    "S506": "Use `yaml.safe_load` or pass `Loader=yaml.SafeLoader`.",
    "B506": "Use `yaml.safe_load` or pass `Loader=yaml.SafeLoader`.",
    "AST-CMD001": "Pass the command as an argument list without `shell=True`, and validate any dynamic parts.",
    "S602": "Pass the command as an argument list without `shell=True`, and validate any dynamic parts.",
    "B602": "Pass the command as an argument list without `shell=True`, and validate any dynamic parts.",
    "AST-COR001": "Catch the specific exception types you expect (for example `except ValueError:`).",
    "E722": "Catch the specific exception types you expect (for example `except ValueError:`).",
    "AST-COR002": "Use `None` as the default and create the mutable object inside the function body.",
}
GENERIC_REMEDIATION = "Review the flagged line against the tool's rule documentation and address the reported pattern."


def make_id(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"f_{digest}"


def finding_from_diagnostic(diag: RawDiagnostic, index: int) -> Finding:
    source = SourceType.ast_check if diag.tool == "ast" else SourceType.static_analysis
    return Finding(
        id=make_id("static", diag.tool, diag.rule_id, diag.file_path, str(diag.line), str(index)),
        rule_id=diag.rule_id,
        tool=diag.tool,
        category=Category(diag.category),
        severity=Severity(diag.severity),
        title=diag.title or diag.rule_id,
        file_path=diag.file_path,
        start_line=diag.line,
        end_line=diag.line,
        explanation=diag.message or diag.title,
        evidence=[f"{diag.tool} {diag.rule_id}: {diag.message}"[:500]] if diag.message else [f"{diag.tool} {diag.rule_id}"],
        suggested_fix=REMEDIATION_BY_RULE.get(diag.rule_id, GENERIC_REMEDIATION),
        confidence=diag.confidence,
        source_type=source,
        reviewers=[diag.tool],
        code_excerpt=diag.excerpt or None,
    )


def excerpt_for_range(parsed: ParsedDiff, path: str, start: int, end: int) -> str | None:
    f = parsed.get_file(path)
    if f is None:
        return None
    added = f.added_text()
    lines = [f"+{added[n]}" for n in range(start, end + 1) if n in added]
    if not lines:
        return None
    return "\n".join(lines)[:600]


def finding_from_llm(draft: LLMFindingDraft, reviewer: str, parsed: ParsedDiff, index: int) -> Finding:
    explanation = f"Observed in diff: {draft.observed}\n\nInference (not directly observed): {draft.inference}"
    start, end = draft.start_line, max(draft.start_line, draft.end_line)
    category = Category(reviewer)
    return Finding(
        id=make_id("llm", reviewer, draft.file_path, str(start), draft.title, str(index)),
        rule_id=None,
        tool="llm",
        category=category,
        severity=draft.severity,
        title=draft.title,
        file_path=draft.file_path,
        start_line=start,
        end_line=end,
        explanation=explanation,
        evidence=list(draft.evidence),
        suggested_fix=draft.suggested_fix,
        confidence=draft.confidence,
        source_type=SourceType.llm_hypothesis,
        reviewers=[reviewer],
        code_excerpt=excerpt_for_range(parsed, draft.file_path, start, end),
    )
