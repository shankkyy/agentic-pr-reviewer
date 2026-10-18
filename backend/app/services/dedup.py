"""Deduplication of findings from analyzers and reviewers.

Two findings are duplicates when they point to the same file, their line ranges
overlap within one line of tolerance, and they are either in the same category
or their titles are substantially similar. The most trustworthy finding (static
or AST before LLM, then higher severity and confidence) is kept as the primary
record; the others contribute provenance and evidence to it.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from app.schemas.enums import SEVERITY_ORDER, SourceType
from app.schemas.findings import Finding

_SOURCE_RANK = {SourceType.static_analysis: 0, SourceType.ast_check: 0, SourceType.llm_hypothesis: 1}


def _ranges_overlap(a: Finding, b: Finding, tolerance: int = 1) -> bool:
    if a.start_line is None or b.start_line is None:
        return False
    a_start, a_end = a.start_line, a.end_line or a.start_line
    b_start, b_end = b.start_line, b.end_line or b.start_line
    return a_start <= b_end + tolerance and b_start <= a_end + tolerance


def _similar_titles(a: Finding, b: Finding) -> bool:
    if a.rule_id and b.rule_id and a.rule_id == b.rule_id:
        return True
    return SequenceMatcher(None, a.title.lower(), b.title.lower()).ratio() >= 0.6


def is_duplicate(a: Finding, b: Finding) -> bool:
    if a.file_path != b.file_path or not _ranges_overlap(a, b):
        return False
    return a.category == b.category or _similar_titles(a, b)


def _priority(f: Finding) -> tuple[int, int, float]:
    return (_SOURCE_RANK[f.source_type], -SEVERITY_ORDER[f.severity], -f.confidence)


def _merge_into(primary: Finding, other: Finding) -> None:
    for reviewer in other.reviewers:
        if reviewer not in primary.reviewers:
            primary.reviewers.append(reviewer)
    if other.rule_id:
        label = f"{other.tool}:{other.rule_id}"
    else:
        label = f"{other.tool or 'llm'}:{'/'.join(other.reviewers) or 'unknown'}"
    if label not in primary.related_rules and label != (
        f"{primary.tool or 'llm'}:{primary.rule_id or primary.tool or 'unknown'}"
    ):
        primary.related_rules.append(label)
    for item in other.evidence:
        if item not in primary.evidence and len(primary.evidence) < 20:
            primary.evidence.append(item)


def deduplicate(findings: list[Finding]) -> tuple[list[Finding], int]:
    """Return (unique findings, number of duplicates merged)."""
    ordered = sorted(findings, key=_priority)
    unique: list[Finding] = []
    merged = 0
    for candidate in ordered:
        target = next((f for f in unique if is_duplicate(f, candidate)), None)
        if target is None:
            unique.append(candidate)
        else:
            _merge_into(target, candidate)
            merged += 1
    return unique, merged
