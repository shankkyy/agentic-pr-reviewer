"""Schema contracts, deduplication, and verification decisions (pure logic, no LLM calls)."""

import pytest
from pydantic import ValidationError

from app.schemas.enums import Category, Severity, SourceType, VerificationStatus
from app.schemas.findings import Finding, LLMFindingDraft, LLMReviewResponse
from app.services.dedup import deduplicate
from app.services.diff_parser import parse_diff
from app.services.verification import decide, verify_findings
from tests.conftest import fixture_text


def make_finding(**overrides):
    base = dict(
        id="f_aaaaaaaaaaaa",
        tool="ruff",
        rule_id="S608",
        category=Category.security,
        severity=Severity.high,
        title="Possible SQL injection",
        file_path="app/repositories/users.py",
        start_line=6,
        end_line=6,
        explanation="x",
        evidence=["ruff S608"],
        suggested_fix="Use bound parameters.",
        confidence=0.7,
        source_type=SourceType.static_analysis,
        reviewers=["ruff"],
    )
    base.update(overrides)
    return Finding(**base)


def llm_finding(**overrides):
    base = dict(
        id="f_bbbbbbbbbbbb",
        tool="llm",
        category=Category.security,
        severity=Severity.high,
        title="SQL built by string interpolation",
        file_path="app/repositories/users.py",
        start_line=6,
        end_line=6,
        explanation="Observed: ...",
        evidence=['cur.execute(f"SELECT id, email FROM users WHERE name = \'{username}\'")'],
        suggested_fix="Use bound parameters.",
        confidence=0.6,
        source_type=SourceType.llm_hypothesis,
        reviewers=["security"],
    )
    base.update(overrides)
    return Finding(**base)


# -- schema contracts ----------------------------------------------------------

def test_finding_rejects_unknown_enum_and_extra_fields():
    with pytest.raises(ValidationError):
        make_finding(severity="catastrophic")
    with pytest.raises(ValidationError):
        make_finding(verification_status="maybe")
    with pytest.raises(ValidationError):
        make_finding(unexpected_field=1)


def test_finding_rejects_inverted_line_range_and_bad_confidence():
    with pytest.raises(ValidationError):
        make_finding(start_line=10, end_line=5)
    with pytest.raises(ValidationError):
        make_finding(confidence=1.5)


def test_llm_response_requires_full_shape():
    with pytest.raises(ValidationError):
        LLMReviewResponse.model_validate({"findings": [{"title": "only a title"}]})
    ok = LLMReviewResponse.model_validate({"findings": []})
    assert ok.findings == []
    with pytest.raises(ValidationError):
        LLMFindingDraft.model_validate({
            "title": "t", "severity": "high", "file_path": "a.py", "start_line": 1, "end_line": 1,
            "evidence": [], "observed": "o", "inference": "i", "suggested_fix": "fix it", "confidence": 0.5,
        })


# -- deduplication -------------------------------------------------------------

def test_duplicates_from_different_reviewers_are_merged():
    static = make_finding()
    model = llm_finding()
    unique, merged = deduplicate([model, static])
    assert merged == 1
    assert len(unique) == 1
    assert unique[0].source_type == SourceType.static_analysis  # deterministic record is primary
    assert "security" in unique[0].reviewers or "security" in [r.split(":")[-1] for r in unique[0].related_rules]


def test_distinct_lines_or_files_are_not_merged():
    a = make_finding(start_line=6, end_line=6)
    b = make_finding(start_line=40, end_line=40, id="f_cccccccccccc")
    c = make_finding(file_path="other.py", id="f_dddddddddddd")
    unique, merged = deduplicate([a, b, c])
    assert merged == 0
    assert len(unique) == 3


def test_adjacent_line_tolerance():
    a = make_finding(start_line=6, end_line=6)
    b = make_finding(start_line=7, end_line=7, id="f_eeeeeeeeeeee", title="Unrelated thing", rule_id=None,
                     category=Category.correctness, source_type=SourceType.llm_hypothesis, tool="llm")
    unique, merged = deduplicate([a, b])
    assert merged == 0


# -- verification --------------------------------------------------------------

@pytest.fixture
def parsed_sql():
    return parse_diff(fixture_text("security/sql_injection.diff"))


def test_static_finding_on_added_line_is_verified_as_pattern_match(parsed_sql):
    f = make_finding()
    d = decide(f, parsed_sql, corroborated=True)
    assert d.status == VerificationStatus.verified
    assert "not a proof of exploitability" in d.reason


def test_invalid_line_reference_is_rejected(parsed_sql):
    f = make_finding(start_line=999, end_line=999)
    assert decide(f, parsed_sql, corroborated=True).status == VerificationStatus.rejected


def test_context_line_reference_needs_review(parsed_sql):
    f = make_finding(start_line=4, end_line=4)  # `def find_user(...)` is unchanged context
    d = decide(f, parsed_sql, corroborated=True)
    assert d.status == VerificationStatus.needs_review


def test_unknown_file_is_rejected(parsed_sql):
    f = make_finding(file_path="not/in/diff.py")
    assert decide(f, parsed_sql, corroborated=True).status == VerificationStatus.rejected


def test_llm_only_finding_with_present_evidence_needs_review(parsed_sql):
    f = llm_finding()
    d = decide(f, parsed_sql, corroborated=False)
    assert d.status == VerificationStatus.needs_review
    assert "no deterministic tool corroborates" in d.reason


def test_hallucinated_evidence_is_rejected(parsed_sql):
    f = llm_finding(evidence=["cur.execute(conn.dangerous_call_that_does_not_exist())"])
    d = decide(f, parsed_sql, corroborated=False)
    assert d.status == VerificationStatus.rejected
    assert "hallucination" in d.reason


def test_missing_evidence_is_inconclusive(parsed_sql):
    f = llm_finding(evidence=[])
    assert decide(f, parsed_sql, corroborated=False).status == VerificationStatus.inconclusive


def test_verify_findings_sets_fields_in_place(parsed_sql):
    out = verify_findings([make_finding(), make_finding(start_line=999, end_line=999, id="f_ffffffffffff")], parsed_sql)
    statuses = [f.verification_status for f in out]
    assert statuses == [VerificationStatus.verified, VerificationStatus.rejected]
    assert all(f.verification_reason for f in out)
