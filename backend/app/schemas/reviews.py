"""Pydantic models for review jobs, stage records, usage, and the final report."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import JobStatus, StageName, StageStatus
from app.schemas.findings import Finding


class ErrorInfo(BaseModel):
    code: str
    message: str
    stage: str | None = None


class StageRecord(BaseModel):
    stage: StageName
    status: StageStatus
    duration_ms: float = 0.0
    detail: str = ""
    error: str | None = None


class ReviewerRun(BaseModel):
    reviewer: str
    status: str  # completed | failed | skipped
    attempts: int = 0
    llm_calls: int = 0
    findings_proposed: int = 0
    duration_ms: float = 0.0
    error_code: str | None = None
    error_message: str | None = None
    omitted_files: list[str] = Field(default_factory=list)


class ToolRunRecord(BaseModel):
    tool: str
    status: str  # completed | unavailable | failed | timeout | skipped
    duration_ms: float = 0.0
    diagnostics: int = 0
    message: str = ""


class UsageSummary(BaseModel):
    provider: str
    model: str
    mock_mode: bool
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float | None = None
    cost_note: str = ""


class SummaryCounts(BaseModel):
    total_findings: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_verification: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)
    duplicates_merged: int = 0
    tests_suggested: int = 0


class FileSummary(BaseModel):
    path: str
    status: str
    hunks: int
    added_lines: int
    deleted_lines: int
    analyzed: bool
    reason: str = ""


class ReviewJobView(BaseModel):
    """Status view returned by GET /api/reviews/{id}."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    status: JobStatus
    source_name: str
    mock_mode: bool
    created_at: datetime
    updated_at: datetime
    current_stage: str | None = None
    stages: list[StageRecord] = Field(default_factory=list)
    counts: SummaryCounts | None = None
    error: ErrorInfo | None = None


class ReviewListItem(BaseModel):
    review_id: str
    status: JobStatus
    source_name: str
    mock_mode: bool
    created_at: datetime
    completed_at: datetime | None = None
    total_findings: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)


class ReviewReport(BaseModel):
    review_id: str
    status: JobStatus
    source_name: str
    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: float | None = None
    input_sha256: str
    size_bytes: int
    mock_mode: bool
    provider: str
    model: str
    counts: SummaryCounts
    findings: list[Finding] = Field(default_factory=list)
    stages: list[StageRecord] = Field(default_factory=list)
    reviewers: list[ReviewerRun] = Field(default_factory=list)
    tools: list[ToolRunRecord] = Field(default_factory=list)
    usage: UsageSummary
    files: list[FileSummary] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None


class CreateReviewResponse(BaseModel):
    review_id: str
    status: JobStatus
    status_url: str
    report_url: str
