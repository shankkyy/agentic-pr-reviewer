"""FastAPI application factory.

Run locally:  uvicorn app.main:app --reload --port 8000  (from the backend directory)
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.routes import router
from app.core.config import Settings
from app.core.errors import APIError
from app.core.observability import configure_logging, get_logger, register_secret, request_id_var
from app.repositories.review_repository import SQLiteReviewRepository
from app.services.review_service import ReviewService

log = get_logger("http")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")


def _error_body(code: str, message: str, request_id: str | None) -> dict:
    return {"error": {"code": code, "message": message, "request_id": request_id}}


def create_app(settings: Settings | None = None, service: ReviewService | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)
    register_secret(settings.llm_api_key)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        app.state.service.shutdown()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.state.settings = settings
    if service is None:
        repo = SQLiteReviewRepository(settings.database_path)
        service = ReviewService(settings, repo)
    app.state.service = service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_var.reset(token)

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, request_id_var.get()),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        message = f"Invalid request parameter{': ' + loc if loc else ''}."
        return JSONResponse(
            status_code=422,
            content=_error_body("invalid_request", message, request_id_var.get()),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", extra={"error": type(exc).__name__, "path": request.url.path})
        return JSONResponse(
            status_code=500,
            content=_error_body("internal_error", "An internal error occurred.", request_id_var.get()),
        )

    app.include_router(router)
    return app


_default_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    """Lazily build the default app so `uvicorn app.main:app` works without importing side effects in tests."""
    global _default_app
    if name == "app":
        if _default_app is None:
            _default_app = create_app()
        return _default_app
    raise AttributeError(name)
