"""Typed LangGraph state for one review run.

Keys written by parallel nodes use list reducers (operator.add) so concurrent
updates merge instead of conflicting. Values are validated Pydantic models or
explicit dataclasses; the state container itself is a TypedDict, which is
LangGraph's native channel model.
"""

from __future__ import annotations

import operator
import threading
from typing import Annotated, Any, TypedDict

from app.agents.providers import LLMProvider
from app.agents.reviewers import ReviewerOutcome
from app.core.config import Settings
from app.schemas.findings import Finding
from app.services.input_validation import ValidatedDiff
from app.services.python_context import PythonContext
from app.services.static_analysis import StaticAnalysisResult


class ReviewState(TypedDict, total=False):
    # Inputs (set once before the graph runs)
    review_id: str
    settings: Settings
    provider: LLMProvider
    diff: ValidatedDiff
    deadline: float  # time.monotonic() deadline for the whole review
    cancel_event: threading.Event

    # Stage outputs
    python_context: PythonContext
    static_result: StaticAnalysisResult
    correctness: ReviewerOutcome
    security: ReviewerOutcome
    candidate_findings: list[Finding]
    unique_findings: list[Finding]
    duplicates_merged: int
    verified_findings: list[Finding]
    tests_suggested: int
    test_calls: int
    report_summary: dict[str, Any]

    # Shared, append-only records
    stage_records: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[dict[str, Any]], operator.add]
    notes: Annotated[list[str], operator.add]
