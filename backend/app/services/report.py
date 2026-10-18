"""Final report assembly helpers: counts, usage and cost, file summaries, and job status."""

from __future__ import annotations

from collections import Counter

from app.agents.providers import LLMProvider
from app.agents.reviewers import ReviewerOutcome
from app.core.config import Settings
from app.schemas.enums import JobStatus
from app.schemas.findings import Finding
from app.schemas.reviews import FileSummary, ReviewerRun, SummaryCounts, ToolRunRecord, UsageSummary
from app.services.diff_parser import ParsedDiff
from app.services.python_context import is_python_candidate
from app.services.static_analysis import StaticAnalysisResult


def build_counts(findings: list[Finding], duplicates_merged: int, tests_suggested: int) -> SummaryCounts:
    return SummaryCounts(
        total_findings=len(findings),
        by_severity=dict(Counter(f.severity.value for f in findings)),
        by_category=dict(Counter(f.category.value for f in findings)),
        by_verification=dict(Counter(f.verification_status.value for f in findings)),
        by_source=dict(Counter(f.source_type.value for f in findings)),
        duplicates_merged=duplicates_merged,
        tests_suggested=tests_suggested,
    )


def build_reviewer_runs(outcomes: list[ReviewerOutcome]) -> list[ReviewerRun]:
    return [
        ReviewerRun(
            reviewer=o.reviewer,
            status=o.status,
            attempts=o.attempts,
            llm_calls=o.llm_calls,
            findings_proposed=len(o.drafts),
            duration_ms=round(o.duration_ms, 2),
            error_code=o.error_code,
            error_message=o.error_message,
            omitted_files=o.omitted_files,
        )
        for o in outcomes
    ]


def build_tool_runs(static: StaticAnalysisResult | None) -> list[ToolRunRecord]:
    if static is None:
        return []
    return [
        ToolRunRecord(
            tool=t.tool,
            status=t.status,
            duration_ms=round(t.duration_ms, 2),
            diagnostics=t.diagnostics,
            message=t.message,
        )
        for t in static.tool_runs
    ]


def build_usage(
    provider: LLMProvider,
    settings: Settings,
    outcomes: list[ReviewerOutcome],
    test_calls: int,
) -> UsageSummary:
    calls = sum(o.llm_calls for o in outcomes) + test_calls
    in_tok = sum(o.input_tokens for o in outcomes)
    out_tok = sum(o.output_tokens for o in outcomes)
    cost: float | None = None
    note = ""
    if provider.is_mock:
        cost = 0.0
        note = "mock provider: no API calls, no cost"
    elif settings.llm_input_price_per_mtok is None or settings.llm_output_price_per_mtok is None:
        note = "cost not measured: LLM_INPUT_PRICE_PER_MTOK and LLM_OUTPUT_PRICE_PER_MTOK are not set"
    elif in_tok == 0 and out_tok == 0 and calls > 0:
        note = "provider returned no usage metadata; cost not measurable"
    else:
        cost = round(
            in_tok / 1_000_000 * settings.llm_input_price_per_mtok
            + out_tok / 1_000_000 * settings.llm_output_price_per_mtok,
            6,
        )
        note = "estimated from configured per-million-token prices and provider-reported usage"
    return UsageSummary(
        provider=provider.name,
        model=provider.model,
        mock_mode=provider.is_mock,
        llm_calls=calls,
        input_tokens=in_tok,
        output_tokens=out_tok,
        estimated_cost_usd=cost,
        cost_note=note,
    )


def build_file_summaries(parsed: ParsedDiff, unsupported: list[str]) -> list[FileSummary]:
    out: list[FileSummary] = []
    for f in parsed.files:
        added = sum(1 for h in f.hunks for line in h.lines if line.kind == "added")
        deleted = sum(1 for h in f.hunks for line in h.lines if line.kind == "deleted")
        if f.is_binary:
            analyzed, reason = False, "binary file: not analyzed"
        elif f.status == "deleted":
            analyzed, reason = False, "deleted file: no new-side code to analyze"
        elif not is_python_candidate(f.path):
            analyzed, reason = False, "not a supported Python file"
        else:
            analyzed, reason = True, "analyzed from changed hunks (diff-only context)"
        out.append(
            FileSummary(
                path=f.path,
                status=f.status,
                hunks=len(f.hunks),
                added_lines=added,
                deleted_lines=deleted,
                analyzed=analyzed,
                reason=reason,
            )
        )
    return out


def derive_status(
    *,
    cancelled: bool,
    stage_failures: int,
    reviewer_failures: int,
    tool_failures: int,
) -> JobStatus:
    if cancelled:
        return JobStatus.cancelled
    if stage_failures > 0 and reviewer_failures == 0 and tool_failures == 0:
        return JobStatus.partial
    if reviewer_failures > 0 or tool_failures > 0 or stage_failures > 0:
        return JobStatus.partial
    return JobStatus.completed
