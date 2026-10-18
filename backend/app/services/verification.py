"""Verification of findings against the diff and deterministic evidence.

Principles applied here:
- An LLM assertion alone is not proof. LLM-only findings stay `needs_review`
  unless their quoted evidence is absent from the diff (then `rejected`).
- A static-analysis or AST hit is evidence the pattern occurs on a changed line.
  It is `verified` as a pattern match, not as an exploitable vulnerability.
- Invalid line references are rejected with a reason.
- Findings that reference unchanged context lines remain `needs_review`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.enums import SourceType, VerificationStatus
from app.schemas.findings import Finding
from app.services.diff_parser import ParsedDiff

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Decision:
    status: VerificationStatus
    reason: str


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _hunk_covers(parsed: ParsedDiff, path: str, line: int) -> tuple[bool, bool]:
    """Return (inside a hunk's new-side range, is an added line)."""
    f = parsed.get_file(path)
    if f is None:
        return False, False
    inside = any(h.new_start <= line < h.new_start + h.new_count for h in f.hunks)
    return inside, line in f.added_line_numbers


def _added_corpus(parsed: ParsedDiff, path: str, start: int, end: int) -> str:
    f = parsed.get_file(path)
    if f is None:
        return ""
    added = f.added_text()
    return _norm("\n".join(added[n] for n in range(start, end + 1) if n in added))


def _new_side_corpus(parsed: ParsedDiff, path: str) -> str:
    """All new-side text (added and context lines) of the file, normalized."""
    f = parsed.get_file(path)
    if f is None:
        return ""
    return _norm(
        "\n".join(line.text for hunk in f.hunks for line in hunk.lines if line.kind != "deleted")
    )


def decide(finding: Finding, parsed: ParsedDiff, *, corroborated: bool) -> Decision:
    f = parsed.get_file(finding.file_path)
    if f is None:
        return Decision(VerificationStatus.rejected, "file is not part of the submitted change")
    if f.is_binary or f.status == "deleted":
        return Decision(VerificationStatus.rejected, "file has no new-side lines to reference")
    if finding.start_line is None:
        return Decision(VerificationStatus.inconclusive, "finding has no line reference")
    inside, is_added = _hunk_covers(parsed, finding.file_path, finding.start_line)
    if not inside:
        return Decision(
            VerificationStatus.rejected,
            f"invalid line reference: line {finding.start_line} is outside every changed hunk",
        )
    if not is_added:
        return Decision(VerificationStatus.needs_review, "references an unchanged context line in a changed hunk")

    if finding.source_type in (SourceType.static_analysis, SourceType.ast_check):
        return Decision(
            VerificationStatus.verified,
            f"deterministic {finding.tool or 'analyzer'} output matches an added line "
            f"({finding.rule_id}); this is a pattern match, not a proof of exploitability",
        )

    # LLM-originated findings from here on.
    if not finding.evidence:
        return Decision(VerificationStatus.inconclusive, "no observed evidence was quoted")
    corpus = _added_corpus(parsed, finding.file_path, finding.start_line, finding.end_line or finding.start_line)
    if not corpus:
        return Decision(VerificationStatus.rejected, "referenced lines contain no added code")
    full_corpus = _new_side_corpus(parsed, finding.file_path)
    for quote in finding.evidence:
        q = _norm(quote.lstrip("+"))
        if q and q not in full_corpus:
            return Decision(
                VerificationStatus.rejected,
                "quoted evidence was not found in the submitted diff (possible hallucination)",
            )
    if not finding.suggested_fix.strip() or finding.suggested_fix.strip() == finding.title.strip():
        return Decision(VerificationStatus.inconclusive, "no usable remediation was proposed")
    if corroborated:
        return Decision(VerificationStatus.verified, "model finding corroborated by deterministic analysis on the same line")
    return Decision(
        VerificationStatus.needs_review,
        "model-only finding: quoted evidence is present in the diff, but no deterministic tool corroborates it",
    )


def verify_findings(findings: list[Finding], parsed: ParsedDiff) -> list[Finding]:
    for finding in findings:
        # A merged finding is corroborated when a deterministic analyzer contributed to it.
        corroborated = finding.source_type != SourceType.llm_hypothesis or any(
            rel.startswith(("ruff:", "bandit:", "ast:")) for rel in finding.related_rules
        )
        decision = decide(finding, parsed, corroborated=corroborated)
        finding.verification_status = decision.status
        finding.verification_reason = decision.reason
    return findings
