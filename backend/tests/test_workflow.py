"""End-to-end workflow tests through the real LangGraph graph with the mock provider and fault-injecting providers."""

import dataclasses
import json
from unittest import mock

from app.agents.providers import LLMError, LLMRequest, LLMResponse, MockProvider
from app.schemas.enums import JobStatus, TestStatus, VerificationStatus
from app.services import static_analysis
from app.services.input_validation import validate_diff_text
from app.workflows.review_graph import route_after_input
from tests.conftest import fixture_text, wait_terminal

LIMITS = dict(max_bytes=1024 * 1024, max_files=50, max_hunks=500)


def submit(service, text, name="fixture.diff"):
    diff = validate_diff_text(text, display_name=name, **LIMITS)
    job, _ = service.submit(diff)
    return wait_terminal(service, job.review_id)


class InvalidOutputProvider:
    name = "invalid"
    model = "invalid-test"
    is_mock = True

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(text="Sure! Here are my findings: not json", model=self.model,
                           input_tokens=10, output_tokens=5, latency_ms=1.0)


class TimeoutProvider:
    name = "timeout"
    model = "timeout-test"
    is_mock = True

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise LLMError("timeout", "timed out", retryable=True)


class WrongSchemaProvider(MockProvider):
    def complete(self, request: LLMRequest) -> LLMResponse:
        if request.role == "test_engineer":
            return super().complete(request)
        return LLMResponse(text=json.dumps({"findings": [{"title": "x"}]}), model="m",
                           input_tokens=0, output_tokens=0, latency_ms=0.0)


def test_clean_change_produces_no_findings(make_service):
    service = make_service(provider=MockProvider())
    job = submit(service, fixture_text("clean/clean_change.diff"))
    assert job.status == JobStatus.completed
    report = service.get_report(job.review_id)
    assert report.counts.total_findings == 0
    assert report.mock_mode is True
    assert report.usage.estimated_cost_usd == 0.0


def test_logic_bug_found_by_model_but_not_verified_without_corroboration(make_service):
    service = make_service(provider=MockProvider())
    job = submit(service, fixture_text("buggy/off_by_one_pagination.diff"))
    report = service.get_report(job.review_id)
    assert job.status == JobStatus.completed
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.category.value == "correctness"
    assert finding.source_type.value == "llm_hypothesis"
    assert finding.verification_status == VerificationStatus.needs_review
    assert finding.start_line == 3
    assert "model-only" in finding.verification_reason


def test_sql_injection_verified_by_deterministic_check_and_deduplicated(make_service):
    service = make_service(provider=MockProvider())
    job = submit(service, fixture_text("security/sql_injection.diff"))
    report = service.get_report(job.review_id)
    sql = [f for f in report.findings if f.rule_id == "AST-SQL001"]
    assert len(sql) == 1
    assert sql[0].verification_status == VerificationStatus.verified
    # The model's SQL finding on the same line is merged rather than reported twice.
    assert any(rel.startswith("llm:") for rel in sql[0].related_rules)
    assert report.counts.duplicates_merged >= 1
    assert sql[0].test_status in (TestStatus.suggested_not_executed, TestStatus.error)


def test_demo_has_multiple_findings_across_files(make_service):
    service = make_service(provider=MockProvider())
    job = submit(service, fixture_text("demo/demo_review.diff"))
    report = service.get_report(job.review_id)
    files = {f.file_path for f in report.findings}
    assert {"app/services/pagination.py", "app/repositories/users.py", "app/auth/session.py"} <= files


def test_invalid_model_output_is_failure_not_success(make_service):
    service = make_service(provider=InvalidOutputProvider())
    job = submit(service, fixture_text("buggy/off_by_one_pagination.diff"))
    report = service.get_report(job.review_id)
    assert job.status == JobStatus.partial
    assert [r.error_code for r in report.reviewers if r.reviewer == "correctness"] == ["invalid_response"]
    assert report.counts.total_findings == 0
    assert any("failed" in w for w in report.warnings)


def test_schema_invalid_output_is_rejected_after_bounded_retries(make_service):
    service = make_service(provider=WrongSchemaProvider())
    job = submit(service, fixture_text("buggy/off_by_one_pagination.diff"))
    report = service.get_report(job.review_id)
    run = next(r for r in report.reviewers if r.reviewer == "correctness")
    assert run.status == "failed"
    assert run.error_code == "invalid_response"
    assert run.attempts == service.settings.llm_output_retries + 1


def test_reviewer_timeout_yields_partial_with_deterministic_results(make_service):
    service = make_service(provider=TimeoutProvider())
    job = submit(service, fixture_text("security/sql_injection.diff"))
    report = service.get_report(job.review_id)
    assert job.status == JobStatus.partial
    codes = {r.reviewer: r.error_code for r in report.reviewers}
    assert codes == {"correctness": "timeout", "security": "timeout"}
    # Deterministic AST result survives the reviewer failure.
    assert [f.rule_id for f in report.findings] == ["AST-SQL001"]


def test_static_tool_failure_is_partial_not_crash(make_service, settings, monkeypatch):
    cfg = dataclasses.replace(settings, enable_static_tools=("ruff",))
    service = make_service(provider=MockProvider(), cfg=cfg)

    def bad_run(cmd, **kwargs):
        return mock.Mock(returncode=2, stdout="", stderr="boom")

    monkeypatch.setattr(static_analysis.shutil, "which", lambda name: "/fake/ruff")
    monkeypatch.setattr(static_analysis.subprocess, "run", bad_run)
    job = submit(service, fixture_text("security/sql_injection.diff"))
    report = service.get_report(job.review_id)
    assert job.status == JobStatus.partial
    assert {t.tool: t.status for t in report.tools}["ruff"] == "failed"
    assert any(f.rule_id == "AST-SQL001" for f in report.findings)


def test_missing_static_tools_are_recorded_as_unavailable_not_failed(make_service, settings, monkeypatch):
    cfg = dataclasses.replace(settings, enable_static_tools=("ruff", "bandit"))
    service = make_service(provider=MockProvider(), cfg=cfg)
    monkeypatch.setattr(static_analysis.shutil, "which", lambda name: None)
    job = submit(service, fixture_text("security/sql_injection.diff"))
    report = service.get_report(job.review_id)
    assert job.status == JobStatus.completed
    assert {t.tool: t.status for t in report.tools}["bandit"] == "unavailable"


def test_non_python_diff_skips_analysis(make_service):
    text = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n"
    service = make_service(provider=MockProvider())
    job = submit(service, text, name="readme.patch")
    report = service.get_report(job.review_id)
    assert job.status == JobStatus.completed
    assert report.reviewers == []
    assert any("No supported Python files" in w for w in report.warnings)


def test_routing_function():
    class Ctx:
        python_files = []

    assert route_after_input({"python_context": Ctx()}) == "skip"
    Ctx.python_files = ["a.py"]
    assert route_after_input({"python_context": Ctx()}) == "analyze"


def test_cancel_marks_job_cancelled_or_leaves_terminal_job_alone(make_service):
    service = make_service(provider=MockProvider())
    diff = validate_diff_text(fixture_text("clean/clean_change.diff"), **LIMITS)
    job, _ = service.submit(diff)
    done = wait_terminal(service, job.review_id)
    # Cancelling a finished job is a no-op that returns the terminal state.
    assert service.cancel(job.review_id).status == done.status


def test_idempotency_key_returns_original_review(make_service):
    service = make_service(provider=MockProvider())
    diff = validate_diff_text(fixture_text("clean/clean_change.diff"), **LIMITS)
    first, created_first = service.submit(diff, idempotency_key="same-key-0001")
    second, created_second = service.submit(diff, idempotency_key="same-key-0001")
    assert created_first is True
    assert created_second is False
    assert first.review_id == second.review_id
    wait_terminal(service, first.review_id)
