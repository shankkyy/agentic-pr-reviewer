"""LangGraph review workflow.

Topology:
  input_preparation --(has Python files)--> deterministic_analysis
                    --(no Python files)--> report_assembly
  deterministic_analysis -> correctness_review  \\
  deterministic_analysis -> security_review     -> deduplication -> verification -> report_assembly -> END

The two reviewers run in parallel (same superstep). The deduplication node is
a join that waits for both. Nodes never raise into the graph: failures become
stage records and error entries, and the run continues with partial data.
Business logic lives in services/ and agents/; this module only sequences it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.reviewers import ReviewerOutcome, run_reviewer, suggest_tests
from app.core.observability import get_logger
from app.schemas.enums import StageName, StageStatus
from app.schemas.findings import LLMFindingDraft
from app.services.dedup import deduplicate
from app.services.finding_builders import finding_from_diagnostic, finding_from_llm
from app.services.input_validation import ValidatedDiff
from app.services.python_context import build_python_context
from app.services.report import build_counts
from app.services.static_analysis import run_static_analysis
from app.services.verification import verify_findings
from app.workflows.state import ReviewState

log = get_logger("workflow")

NodeFn = Callable[[ReviewState], dict[str, Any]]


def _stopped(state: ReviewState) -> str | None:
    event = state.get("cancel_event")
    if event is not None and event.is_set():
        return "cancelled"
    deadline = state.get("deadline")
    if deadline is not None and time.monotonic() > deadline:
        return "timeout"
    return None


def _stage(name: StageName, body: NodeFn) -> NodeFn:
    """Wrap a node with timing, cancellation and timeout checks, and failure isolation."""

    def wrapper(state: ReviewState) -> dict[str, Any]:
        start = time.perf_counter()
        stop_reason = _stopped(state)
        if stop_reason is not None:
            record = {
                "stage": name.value,
                "status": StageStatus.skipped.value,
                "duration_ms": 0.0,
                "detail": f"skipped: {stop_reason}",
                "error": None,
            }
            return {"stage_records": [record], "errors": [{"stage": name.value, "code": stop_reason}]}
        try:
            update = body(state)
            status, detail, error = StageStatus.completed, update.pop("_detail", ""), None
        except Exception as exc:  # noqa: BLE001 - isolate stage failures
            update = {}
            status, detail = StageStatus.failed, "stage raised an unexpected error"
            error = type(exc).__name__
            log.error("stage_failed", extra={"stage": name.value, "error": error})
        elapsed = round((time.perf_counter() - start) * 1000, 2)
        record = {
            "stage": name.value,
            "status": status.value,
            "duration_ms": elapsed,
            "detail": detail,
            "error": error,
        }
        log.info("stage_finished", extra={"stage": name.value, "status": status.value, "duration_ms": elapsed})
        update["stage_records"] = [record]
        if error:
            update["errors"] = [{"stage": name.value, "code": "stage_exception", "detail": error}]
        return update

    return wrapper


def _input_preparation(state: ReviewState) -> dict[str, Any]:
    diff: ValidatedDiff = state["diff"]
    ctx = build_python_context(diff.parsed)
    notes = list(ctx.limitations)
    return {
        "python_context": ctx,
        "notes": notes,
        "_detail": f"{len(ctx.python_files)} Python file(s), {len(ctx.snippets)} hunk snippet(s)",
    }


def _deterministic(state: ReviewState) -> dict[str, Any]:
    settings = state["settings"]
    ctx = state["python_context"]
    result = run_static_analysis(
        ctx,
        tool_timeout=settings.static_tool_timeout_seconds,
        enable_tools=settings.enable_static_tools,
    )
    return {
        "static_result": result,
        "_detail": f"{len(result.diagnostics)} diagnostic(s) on changed lines",
    }


def _reviewer(role: str) -> NodeFn:
    def body(state: ReviewState) -> dict[str, Any]:
        settings = state["settings"]
        ctx = state["python_context"]
        started = time.perf_counter()
        outcome: ReviewerOutcome = run_reviewer(
            role,
            state["provider"],
            settings,
            state["diff"].parsed,
            ctx.python_files,
        )
        outcome.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        key = "correctness" if role == "correctness" else "security"
        return {
            key: outcome,
            "_detail": f"{outcome.status}: {len(outcome.drafts)} proposed finding(s)",
        }

    return body


def _dedup(state: ReviewState) -> dict[str, Any]:
    diff = state["diff"].parsed
    candidates = []
    static = state.get("static_result")
    if static is not None:
        candidates.extend(finding_from_diagnostic(d, i) for i, d in enumerate(static.diagnostics))
    for key in ("correctness", "security"):
        outcome: ReviewerOutcome | None = state.get(key)
        if outcome is None:
            continue
        for i, draft in enumerate(outcome.drafts):
            if isinstance(draft, LLMFindingDraft):
                candidates.append(finding_from_llm(draft, key, diff, i))
    unique, merged = deduplicate(candidates)
    return {
        "candidate_findings": candidates,
        "unique_findings": unique,
        "duplicates_merged": merged,
        "_detail": f"{len(candidates)} candidate(s) -> {len(unique)} unique ({merged} merged)",
    }


def _verification(state: ReviewState) -> dict[str, Any]:
    findings = verify_findings(list(state.get("unique_findings", [])), state["diff"].parsed)
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.verification_status.value] = counts.get(f.verification_status.value, 0) + 1
    return {"verified_findings": findings, "_detail": f"verification outcomes: {counts or 'none'}"}


def _report(state: ReviewState) -> dict[str, Any]:
    findings = list(state.get("verified_findings", []))
    settings = state["settings"]
    tests = 0
    calls = 0
    if findings and state.get("provider") is not None and not _stopped(state):
        tests, calls = suggest_tests(findings, state["provider"], settings)
    counts = build_counts(findings, state.get("duplicates_merged", 0), tests)
    return {
        "verified_findings": findings,
        "tests_suggested": tests,
        "test_calls": calls,
        "report_summary": counts.model_dump(),
        "_detail": f"{len(findings)} finding(s); {tests} test suggestion(s)",
    }


def route_after_input(state: ReviewState) -> str:
    """Skip analysis and reviewers when the diff contains no Python files."""
    ctx = state.get("python_context")
    if ctx is None or not ctx.python_files:
        return "skip"
    return "analyze"


def build_review_graph():
    graph = StateGraph(ReviewState)
    graph.add_node(StageName.input_preparation.value, _stage(StageName.input_preparation, _input_preparation))
    graph.add_node(StageName.deterministic_analysis.value, _stage(StageName.deterministic_analysis, _deterministic))
    graph.add_node(StageName.correctness_review.value, _stage(StageName.correctness_review, _reviewer("correctness")))
    graph.add_node(StageName.security_review.value, _stage(StageName.security_review, _reviewer("security")))
    graph.add_node(StageName.deduplication.value, _stage(StageName.deduplication, _dedup))
    graph.add_node(StageName.verification.value, _stage(StageName.verification, _verification))
    graph.add_node(StageName.report_assembly.value, _stage(StageName.report_assembly, _report))

    graph.add_edge(START, StageName.input_preparation.value)
    graph.add_conditional_edges(
        StageName.input_preparation.value,
        route_after_input,
        {"analyze": StageName.deterministic_analysis.value, "skip": StageName.report_assembly.value},
    )
    graph.add_edge(StageName.deterministic_analysis.value, StageName.correctness_review.value)
    graph.add_edge(StageName.deterministic_analysis.value, StageName.security_review.value)
    graph.add_edge(
        [StageName.correctness_review.value, StageName.security_review.value],
        StageName.deduplication.value,
    )
    graph.add_edge(StageName.deduplication.value, StageName.verification.value)
    graph.add_edge(StageName.verification.value, StageName.report_assembly.value)
    graph.add_edge(StageName.report_assembly.value, END)
    return graph.compile()
