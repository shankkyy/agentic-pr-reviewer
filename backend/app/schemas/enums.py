"""Explicit enums shared by findings, workflow state, and API responses."""

from enum import StrEnum


class Category(StrEnum):
    correctness = "correctness"
    security = "security"
    performance = "performance"
    testing = "testing"


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


SEVERITY_ORDER = {
    Severity.critical: 5,
    Severity.high: 4,
    Severity.medium: 3,
    Severity.low: 2,
    Severity.info: 1,
}


class SourceType(StrEnum):
    static_analysis = "static_analysis"  # Ruff or Bandit output
    ast_check = "ast_check"  # focused in-process AST rule
    llm_hypothesis = "llm_hypothesis"  # model assertion; never proof on its own


class VerificationStatus(StrEnum):
    verified = "verified"
    rejected = "rejected"
    needs_review = "needs_review"
    inconclusive = "inconclusive"


class TestStatus(StrEnum):
    not_generated = "not_generated"
    suggested_not_executed = "suggested_not_executed"
    passed = "passed"
    failed = "failed"
    error = "error"
    timeout = "timeout"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    partial = "partial"
    failed = "failed"
    cancelled = "cancelled"


class StageName(StrEnum):
    input_preparation = "input_preparation"
    deterministic_analysis = "deterministic_analysis"
    correctness_review = "correctness_review"
    security_review = "security_review"
    deduplication = "deduplication"
    verification = "verification"
    report_assembly = "report_assembly"


class StageStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
