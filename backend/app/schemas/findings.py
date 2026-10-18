"""Pydantic v2 contracts for findings and LLM responses.

`Finding` is the single shape used across analyzers, reviewers, verification,
persistence, and the API. `LLMReviewResponse` is the only shape accepted from a
model; anything that fails validation is retried or recorded as a failure.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import Category, Severity, SourceType, TestStatus, VerificationStatus


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=8, max_length=64)
    rule_id: str | None = Field(default=None, max_length=64)
    tool: str | None = Field(default=None, max_length=32, description="ruff, bandit, ast, or llm")
    category: Category
    severity: Severity
    title: str = Field(min_length=1, max_length=200)
    file_path: str = Field(min_length=1, max_length=1024)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    explanation: str = Field(default="", max_length=4000)
    evidence: list[str] = Field(default_factory=list, max_length=20)
    suggested_fix: str = Field(default="", max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)
    source_type: SourceType
    reviewers: list[str] = Field(default_factory=list, max_length=8, description="Reviewer/tool provenance")
    related_rules: list[str] = Field(default_factory=list, max_length=8)
    code_excerpt: str | None = Field(default=None, max_length=600)
    verification_status: VerificationStatus = VerificationStatus.needs_review
    verification_reason: str = Field(default="", max_length=600)
    test_status: TestStatus = TestStatus.not_generated
    suggested_test: str | None = Field(default=None, max_length=4000)
    suggested_test_behavior: str | None = Field(default=None, max_length=600)

    @model_validator(mode="after")
    def _check_line_range(self) -> "Finding":
        if self.start_line is not None and self.end_line is None:
            self.end_line = self.start_line
        if self.start_line is not None and self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class LLMFindingDraft(BaseModel):
    """One finding as produced by a reviewer model. Evidence is observed quoted diff text."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=200)
    severity: Severity
    file_path: str = Field(min_length=1, max_length=1024)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    evidence: list[str] = Field(min_length=1, max_length=5)
    observed: str = Field(min_length=3, max_length=1000, description="What the diff shows")
    inference: str = Field(min_length=3, max_length=1000, description="Why this is a problem; labelled as inference")
    suggested_fix: str = Field(min_length=5, max_length=1500)
    confidence: float = Field(ge=0.0, le=1.0)


class LLMReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[LLMFindingDraft] = Field(default_factory=list, max_length=20)


class LLMTestSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_code: str = Field(min_length=10, max_length=4000)
    expected_behavior: str = Field(min_length=5, max_length=600)


ReviewerName = Literal["correctness", "security"]
