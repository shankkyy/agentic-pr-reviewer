"""Persistence abstraction for review jobs and reports.

`ReviewRepository` is the interface the service depends on. `SQLiteReviewRepository`
is the MVP implementation. A PostgreSQL implementation can replace it without
changing the service or the API layer.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from app.schemas.enums import JobStatus
from app.schemas.reviews import ErrorInfo, ReviewJobView, ReviewListItem, ReviewReport


class ReviewRepository(Protocol):
    def create_job(self, job: ReviewJobView, *, input_sha256: str, size_bytes: int, idempotency_key: str | None) -> None: ...
    def update_job(self, job: ReviewJobView) -> None: ...
    def save_report(self, report: ReviewReport) -> None: ...
    def get_job(self, review_id: str) -> ReviewJobView | None: ...
    def get_report(self, review_id: str) -> ReviewReport | None: ...
    def list_items(self, limit: int, offset: int) -> list[ReviewListItem]: ...
    def find_by_idempotency_key(self, key: str) -> str | None: ...
    def mark_interrupted(self, message: str) -> int: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    source_name TEXT NOT NULL,
    mock_mode INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    total_findings INTEGER NOT NULL DEFAULT 0,
    by_severity_json TEXT NOT NULL DEFAULT '{}',
    input_sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    job_json TEXT NOT NULL,
    report_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_reviews_created ON reviews (created_at DESC);
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    review_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


class SQLiteReviewRepository:
    """SQLite-backed repository. Uses one connection guarded by a lock (safe for the thread pool)."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL" if path != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_job(self, job: ReviewJobView, *, input_sha256: str, size_bytes: int, idempotency_key: str | None) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO reviews (id, status, source_name, mock_mode, created_at, updated_at, completed_at,
                   total_findings, by_severity_json, input_sha256, size_bytes, job_json, report_json)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, 0, '{}', ?, ?, ?, NULL)""",
                (
                    job.review_id,
                    job.status.value,
                    job.source_name,
                    int(job.mock_mode),
                    _iso(job.created_at),
                    _iso(job.updated_at),
                    input_sha256,
                    size_bytes,
                    job.model_dump_json(),
                ),
            )
            if idempotency_key:
                self._conn.execute(
                    "INSERT INTO idempotency_keys (key, review_id, created_at) VALUES (?, ?, ?)",
                    (idempotency_key, job.review_id, _iso(datetime.now(UTC))),
                )
            self._conn.commit()

    def update_job(self, job: ReviewJobView) -> None:
        total = job.counts.total_findings if job.counts else 0
        by_sev = json.dumps(job.counts.by_severity) if job.counts else "{}"
        completed = job.updated_at if job.status in (JobStatus.completed, JobStatus.partial, JobStatus.failed, JobStatus.cancelled) else None
        with self._lock:
            self._conn.execute(
                """UPDATE reviews SET status = ?, updated_at = ?, completed_at = COALESCE(?, completed_at),
                   total_findings = ?, by_severity_json = ?, job_json = ? WHERE id = ?""",
                (
                    job.status.value,
                    _iso(job.updated_at),
                    _iso(completed),
                    total,
                    by_sev,
                    job.model_dump_json(),
                    job.review_id,
                ),
            )
            self._conn.commit()

    def save_report(self, report: ReviewReport) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE reviews SET report_json = ?, status = ?, completed_at = ? WHERE id = ?",
                (report.model_dump_json(), report.status.value, _iso(report.completed_at), report.review_id),
            )
            self._conn.commit()

    def get_job(self, review_id: str) -> ReviewJobView | None:
        with self._lock:
            row = self._conn.execute("SELECT job_json FROM reviews WHERE id = ?", (review_id,)).fetchone()
        return ReviewJobView.model_validate_json(row["job_json"]) if row else None

    def get_report(self, review_id: str) -> ReviewReport | None:
        with self._lock:
            row = self._conn.execute("SELECT report_json FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if row is None or row["report_json"] is None:
            return None
        return ReviewReport.model_validate_json(row["report_json"])

    def list_items(self, limit: int, offset: int) -> list[ReviewListItem]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, status, source_name, mock_mode, created_at, completed_at, total_findings, by_severity_json
                   FROM reviews ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return [
            ReviewListItem(
                review_id=r["id"],
                status=JobStatus(r["status"]),
                source_name=r["source_name"],
                mock_mode=bool(r["mock_mode"]),
                created_at=datetime.fromisoformat(r["created_at"]),
                completed_at=datetime.fromisoformat(r["completed_at"]) if r["completed_at"] else None,
                total_findings=r["total_findings"],
                by_severity=json.loads(r["by_severity_json"]),
            )
            for r in rows
        ]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0])

    def find_by_idempotency_key(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT review_id FROM idempotency_keys WHERE key = ?", (key,)).fetchone()
        return row["review_id"] if row else None

    def mark_interrupted(self, message: str) -> int:
        """On startup, jobs left queued or running by a previous process are marked failed."""
        now = datetime.now(UTC)
        interrupted = []
        with self._lock:
            rows = self._conn.execute("SELECT id, job_json FROM reviews WHERE status IN ('queued', 'running')").fetchall()
        for row in rows:
            job = ReviewJobView.model_validate_json(row["job_json"])
            job.status = JobStatus.failed
            job.updated_at = now
            job.error = ErrorInfo(code="interrupted", message=message, stage=job.current_stage)
            interrupted.append(job)
        for job in interrupted:
            self.update_job(job)
        return len(interrupted)
