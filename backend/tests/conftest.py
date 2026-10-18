"""Shared fixtures. Tests use the mock provider and temporary SQLite databases; no paid API calls."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def fixture_text(rel: str) -> str:
    return (FIXTURES / rel).read_text(encoding="utf-8")


@pytest.fixture
def settings(tmp_path):
    from app.core.config import Settings

    return Settings(
        database_path=str(tmp_path / "reviews.db"),
        max_concurrent_reviews=2,
        llm_provider="mock",
        llm_model="mock-deterministic-v1",
        llm_retry_backoff_seconds=0.0,
        llm_timeout_seconds=5.0,
        enable_static_tools=(),  # deterministic tests run AST checks only; tool tests opt in
        review_timeout_seconds=60.0,
    )


@pytest.fixture
def make_service(settings):
    from app.repositories.review_repository import SQLiteReviewRepository
    from app.services.review_service import ReviewService

    created = []

    def factory(provider=None, cfg=None):
        cfg = cfg or settings
        repo = SQLiteReviewRepository(cfg.database_path)
        service = ReviewService(cfg, repo, provider=provider)
        created.append(service)
        return service

    yield factory
    for s in created:
        s.shutdown()


def wait_terminal(service, review_id: str, timeout: float = 30.0):
    from app.services.review_service import TERMINAL

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.get_job(review_id)
        if job.status in TERMINAL:
            return job
        time.sleep(0.02)
    raise AssertionError(f"review {review_id} did not finish within {timeout}s")
