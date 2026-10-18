"""Review job lifecycle: submission, background execution, progress, cancellation, and reports.

Submission returns immediately with a review ID. Work runs on a bounded thread
pool. Stage progress is streamed from the LangGraph run and persisted after each
node, so the status endpoint reflects real progress. Repeated submissions with
the same Idempotency-Key return the original review.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from app.agents.providers import LLMProvider, build_provider
from app.agents.reviewers import ReviewerOutcome
from app.core.config import Settings
from app.core.observability import get_logger, review_id_var
from app.repositories.review_repository import ReviewRepository
from app.schemas.enums import JobStatus, StageName, StageStatus
from app.schemas.findings import Finding
from app.schemas.reviews import ErrorInfo, ReviewJobView, ReviewListItem, ReviewReport, StageRecord
from app.services.input_validation import ValidatedDiff
from app.services.report import (
    build_counts,
    build_file_summaries,
    build_reviewer_runs,
    build_tool_runs,
    build_usage,
    derive_status,
)
from app.services.static_analysis import StaticAnalysisResult
from app.workflows.review_graph import build_review_graph

log = get_logger("service")

TERMINAL = {JobStatus.completed, JobStatus.partial, JobStatus.failed, JobStatus.cancelled}
_REDUCER_KEYS = {"stage_records", "errors", "notes"}


class NotFoundError(LookupError):
    pass


class ReviewService:
    def __init__(
        self,
        settings: Settings,
        repository: ReviewRepository,
        provider: LLMProvider | None = None,
        graph: Any | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repository
        self.provider = provider or build_provider(settings)
        self._graph = graph or build_review_graph()
        self._executor = ThreadPoolExecutor(max_workers=settings.max_concurrent_reviews, thread_name_prefix="review")
        self._futures: dict[str, Future[None]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        interrupted = self.repo.mark_interrupted("the server restarted before this review finished")
        if interrupted:
            log.warning("interrupted_reviews_marked_failed", extra={"count": interrupted})

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- submission ---------------------------------------------------------

    def submit(self, diff: ValidatedDiff, idempotency_key: str | None = None) -> tuple[ReviewJobView, bool]:
        """Create a queued review. Returns (job, created). A repeated key returns the original job."""
        if idempotency_key:
            existing = self.repo.find_by_idempotency_key(idempotency_key)
            if existing:
                job = self.repo.get_job(existing)
                if job is not None:
                    return job, False
        now = datetime.now(UTC)
        review_id = f"rev_{uuid.uuid4().hex[:16]}"
        job = ReviewJobView(
            review_id=review_id,
            status=JobStatus.queued,
            source_name=diff.display_name,
            mock_mode=self.settings.mock_mode,
            created_at=now,
            updated_at=now,
        )
        self.repo.create_job(job, input_sha256=diff.sha256, size_bytes=diff.size_bytes, idempotency_key=idempotency_key)
        event = threading.Event()
        with self._lock:
            self._cancel_events[review_id] = event
            self._futures[review_id] = self._executor.submit(self._run, review_id, diff, event)
        log.info("review_queued", extra={"review_id": review_id, "size_bytes": diff.size_bytes})
        return job, True

    # -- queries ------------------------------------------------------------

    def get_job(self, review_id: str) -> ReviewJobView:
        job = self.repo.get_job(review_id)
        if job is None:
            raise NotFoundError(review_id)
        return job

    def get_report(self, review_id: str) -> ReviewReport:
        self.get_job(review_id)
        report = self.repo.get_report(review_id)
        if report is None:
            raise LookupError("report not ready")
        return report

    def get_findings(
        self,
        review_id: str,
        *,
        category: str | None = None,
        severity: str | None = None,
        verification_status: str | None = None,
        file_path: str | None = None,
    ) -> list[Finding]:
        report = self.get_report(review_id)
        out = report.findings
        if category:
            out = [f for f in out if f.category.value == category]
        if severity:
            out = [f for f in out if f.severity.value == severity]
        if verification_status:
            out = [f for f in out if f.verification_status.value == verification_status]
        if file_path:
            out = [f for f in out if f.file_path == file_path]
        return out

    def list_reviews(self, limit: int, offset: int) -> list[ReviewListItem]:
        return self.repo.list_items(limit, offset)

    def cancel(self, review_id: str) -> ReviewJobView:
        job = self.get_job(review_id)
        if job.status in TERMINAL:
            return job
        with self._lock:
            event = self._cancel_events.get(review_id)
            future = self._futures.get(review_id)
        if event is not None:
            event.set()
        if future is not None and future.cancel():
            job.status = JobStatus.cancelled
            job.updated_at = datetime.now(UTC)
            self.repo.update_job(job)
        return self.get_job(review_id)

    # -- execution ----------------------------------------------------------

    def _run(self, review_id: str, diff: ValidatedDiff, cancel_event: threading.Event) -> None:
        token = review_id_var.set(review_id)
        started = time.perf_counter()
        try:
            job = self.get_job(review_id)
            job.status = JobStatus.running
            job.updated_at = datetime.now(UTC)
            self.repo.update_job(job)
            state: dict[str, Any] = {
                "review_id": review_id,
                "settings": self.settings,
                "provider": self.provider,
                "diff": diff,
                "deadline": time.monotonic() + self.settings.review_timeout_seconds,
                "cancel_event": cancel_event,
                "stage_records": [],
                "errors": [],
                "notes": [],
            }
            acc: dict[str, Any] = {"stage_records": [], "errors": [], "notes": []}
            for update in self._graph.stream(state, stream_mode="updates"):
                for node, payload in update.items():
                    for key, value in payload.items():
                        if key in _REDUCER_KEYS:
                            acc[key].extend(value)
                        else:
                            acc[key] = value
                    job = self.get_job(review_id)
                    job.current_stage = node
                    job.stages = [self._to_stage(r) for r in acc["stage_records"]]
                    job.updated_at = datetime.now(UTC)
                    self.repo.update_job(job)
            self._finalize(review_id, diff, acc, started, cancelled=cancel_event.is_set())
        except Exception as exc:  # noqa: BLE001 - never leak internals to the client
            log.error("review_crashed", extra={"review_id": review_id, "error": type(exc).__name__})
            job = self.get_job(review_id)
            job.status = JobStatus.failed
            job.error = ErrorInfo(code="workflow_error", message="The review failed due to an internal error.")
            job.updated_at = datetime.now(UTC)
            self.repo.update_job(job)
        finally:
            review_id_var.reset(token)
            with self._lock:
                self._cancel_events.pop(review_id, None)
                self._futures.pop(review_id, None)

    @staticmethod
    def _to_stage(record: dict[str, Any]) -> StageRecord:
        return StageRecord(
            stage=StageName(record["stage"]),
            status=StageStatus(record["status"]),
            duration_ms=float(record.get("duration_ms") or 0.0),
            detail=str(record.get("detail") or ""),
            error=record.get("error"),
        )

    def _finalize(
        self,
        review_id: str,
        diff: ValidatedDiff,
        acc: dict[str, Any],
        started: float,
        *,
        cancelled: bool,
    ) -> None:
        now = datetime.now(UTC)
        job = self.get_job(review_id)
        stages = [self._to_stage(r) for r in acc["stage_records"]]
        stage_failures = sum(1 for s in stages if s.status == StageStatus.failed)
        input_failed = any(s.stage == StageName.input_preparation and s.status == StageStatus.failed for s in stages)

        static: StaticAnalysisResult | None = acc.get("static_result")
        outcomes: list[ReviewerOutcome] = [o for o in (acc.get("correctness"), acc.get("security")) if o is not None]
        reviewer_failures = sum(1 for o in outcomes if o.status == "failed")
        tool_failures = sum(1 for t in (static.tool_runs if static else []) if t.status in ("failed", "timeout"))

        warnings: list[str] = []
        py_ctx = acc.get("python_context")
        if py_ctx is not None and not py_ctx.python_files and not input_failed:
            warnings.append("No supported Python files in this diff; no analysis was run.")
        for o in outcomes:
            if o.status == "failed":
                warnings.append(f"{o.reviewer} reviewer failed: {o.error_message or o.error_code}")
            if o.omitted_files:
                warnings.append(f"{o.reviewer} reviewer omitted {len(o.omitted_files)} file(s) to stay within the prompt budget")
        for t in static.tool_runs if static else []:
            if t.status in ("unavailable", "failed", "timeout"):
                warnings.append(f"{t.tool} {t.status}: {t.message or 'no details'}")
        for err in acc["errors"]:
            if err.get("code") in ("timeout", "cancelled"):
                warnings.append(f"stage {err.get('stage')} stopped: {err['code']}")

        verified: list[Finding] = acc.get("verified_findings", [])
        counts = build_counts(verified, acc.get("duplicates_merged", 0), acc.get("tests_suggested", 0))
        status = derive_status(
            cancelled=cancelled,
            stage_failures=stage_failures,
            reviewer_failures=reviewer_failures,
            tool_failures=tool_failures,
        )
        error: ErrorInfo | None = None
        if input_failed:
            status = JobStatus.failed
            error = ErrorInfo(code="input_preparation_failed", message="The diff could not be prepared for analysis.")
        elif cancelled:
            error = ErrorInfo(code="cancelled", message="The review was cancelled.")

        unsupported = acc.get("python_context").unsupported_files if acc.get("python_context") else []
        report = ReviewReport(
            review_id=review_id,
            status=status,
            source_name=diff.display_name,
            created_at=job.created_at,
            completed_at=now,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            input_sha256=diff.sha256,
            size_bytes=diff.size_bytes,
            mock_mode=self.settings.mock_mode,
            provider=self.provider.name,
            model=self.provider.model,
            counts=counts,
            findings=verified,
            stages=stages,
            reviewers=build_reviewer_runs(outcomes),
            tools=build_tool_runs(static),
            usage=build_usage(self.provider, self.settings, outcomes, acc.get("test_calls", 0)),
            files=build_file_summaries(diff.parsed, unsupported),
            limitations=list(dict.fromkeys(acc["notes"])),
            warnings=warnings,
            error=error,
        )
        job.status = status
        job.stages = stages
        job.counts = counts
        job.error = error
        job.current_stage = None
        job.updated_at = now
        self.repo.save_report(report)
        self.repo.update_job(job)
        log.info(
            "review_finished",
            extra={
                "review_id": review_id,
                "status": status.value,
                "findings": counts.total_findings,
                "duration_ms": report.duration_ms,
                "reviewer_failures": reviewer_failures,
                "tool_failures": tool_failures,
            },
        )
