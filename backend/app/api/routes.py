"""HTTP endpoints. Thin layer: validation and HTTP mapping only; logic lives in services."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Header, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings
from app.core.errors import APIError
from app.schemas.findings import Finding
from app.schemas.reviews import CreateReviewResponse, ReviewJobView, ReviewListItem, ReviewReport
from app.services.input_validation import InputValidationError, ValidatedDiff, validate_diff_bytes, validate_diff_text
from app.services.review_service import NotFoundError, ReviewService

router = APIRouter()

MULTIPART_OVERHEAD_BYTES = 256 * 1024
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_\-.:]{8,128}$")


class PasteReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diff_text: str = Field(min_length=1)
    name: str | None = Field(default=None, max_length=200)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _service(request: Request) -> ReviewService:
    return request.app.state.service


def _not_found(review_id: str) -> APIError:
    return APIError(status.HTTP_404_NOT_FOUND, "review_not_found", f"No review with id {review_id!r}.")


def _input_error(exc: InputValidationError) -> APIError:
    return APIError(exc.status_code, exc.code, exc.message)


def _require_length(request: Request, limit: int) -> None:
    raw = request.headers.get("content-length")
    if raw is None:
        raise APIError(status.HTTP_411_LENGTH_REQUIRED, "length_required", "Requests must include a Content-Length header.")
    try:
        declared = int(raw)
    except ValueError as exc:
        raise APIError(status.HTTP_400_BAD_REQUEST, "bad_content_length", "Content-Length is not a number.") from exc
    if declared > limit:
        raise APIError(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "payload_too_large",
            f"The request is larger than the {limit}-byte limit.",
        )


@router.get("/health", tags=["system"])
def health(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    return {
        "status": "ok",
        "version": settings.app_version,
        "mock_mode": settings.mock_mode,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "static_tools_enabled": list(settings.enable_static_tools),
    }


@router.post("/api/reviews", status_code=status.HTTP_202_ACCEPTED, response_model=CreateReviewResponse, tags=["reviews"])
async def create_review(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CreateReviewResponse:
    """Create a review from a multipart upload (field `file`) or a JSON body `{diff_text, name}`.

    Returns 202 with the review ID immediately. Poll `GET /api/reviews/{id}` for status.
    """
    settings = _settings(request)
    service = _service(request)
    if idempotency_key is not None and not IDEMPOTENCY_RE.match(idempotency_key):
        raise APIError(status.HTTP_400_BAD_REQUEST, "bad_idempotency_key", "Idempotency-Key has an invalid format.")

    content_type = (request.headers.get("content-type") or "").lower()
    validated: ValidatedDiff
    if content_type.startswith("multipart/form-data"):
        _require_length(request, settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES)
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise APIError(status.HTTP_422_UNPROCESSABLE_ENTITY, "missing_file", "Multipart requests must include a `file` field.")
        data = await upload.read(settings.max_upload_bytes + 1)
        try:
            validated = validate_diff_bytes(
                data,
                max_bytes=settings.max_upload_bytes,
                max_files=settings.max_files,
                max_hunks=settings.max_hunks,
                display_name=getattr(upload, "filename", None),
            )
        except InputValidationError as exc:
            raise _input_error(exc) from exc
    elif content_type.startswith("application/json"):
        _require_length(request, settings.max_upload_bytes * 6 + 4096)
        raw = await request.body()
        try:
            payload = PasteReviewRequest.model_validate(json.loads(raw))
        except (ValueError, ValidationError) as exc:
            raise APIError(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_request", "Body must be JSON with a non-empty `diff_text`.") from exc
        try:
            validated = validate_diff_text(
                payload.diff_text,
                max_bytes=settings.max_upload_bytes,
                max_files=settings.max_files,
                max_hunks=settings.max_hunks,
                display_name=payload.name,
            )
        except InputValidationError as exc:
            raise _input_error(exc) from exc
    else:
        raise APIError(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "unsupported_media_type",
            "Send multipart/form-data with a `file` field, or application/json with `diff_text`.",
        )

    job, created = service.submit(validated, idempotency_key)
    return CreateReviewResponse(
        review_id=job.review_id,
        status=job.status,
        status_url=f"/api/reviews/{job.review_id}",
        report_url=f"/api/reviews/{job.review_id}/report",
    )


@router.get("/api/reviews", response_model=list[ReviewListItem], tags=["reviews"])
def list_reviews(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> list[ReviewListItem]:
    return _service(request).list_reviews(limit, offset)


@router.get("/api/reviews/{review_id}", response_model=ReviewJobView, tags=["reviews"])
def get_review(request: Request, review_id: str) -> ReviewJobView:
    try:
        return _service(request).get_job(review_id)
    except NotFoundError as exc:
        raise _not_found(review_id) from exc


@router.get("/api/reviews/{review_id}/findings", response_model=list[Finding], tags=["reviews"])
def get_findings(
    request: Request,
    review_id: str,
    category: str | None = Query(default=None, pattern="^(correctness|security|performance|testing)$"),
    severity: str | None = Query(default=None, pattern="^(critical|high|medium|low|info)$"),
    verification_status: str | None = Query(
        default=None, pattern="^(verified|rejected|needs_review|inconclusive)$"
    ),
    file_path: str | None = Query(default=None, max_length=1024),
) -> list[Finding]:
    service = _service(request)
    try:
        service.get_job(review_id)
    except NotFoundError as exc:
        raise _not_found(review_id) from exc
    try:
        return service.get_findings(
            review_id,
            category=category,
            severity=severity,
            verification_status=verification_status,
            file_path=file_path,
        )
    except LookupError as exc:
        raise APIError(status.HTTP_409_CONFLICT, "report_not_ready", "The review has not finished yet.") from exc


@router.get("/api/reviews/{review_id}/report", response_model=ReviewReport, tags=["reviews"])
def get_report(request: Request, review_id: str) -> ReviewReport:
    service = _service(request)
    try:
        service.get_job(review_id)
    except NotFoundError as exc:
        raise _not_found(review_id) from exc
    try:
        return service.get_report(review_id)
    except LookupError as exc:
        raise APIError(status.HTTP_409_CONFLICT, "report_not_ready", "The review has not finished yet.") from exc


@router.post("/api/reviews/{review_id}/cancel", response_model=ReviewJobView, tags=["reviews"])
def cancel_review(request: Request, review_id: str) -> ReviewJobView:
    try:
        return _service(request).cancel(review_id)
    except NotFoundError as exc:
        raise _not_found(review_id) from exc
