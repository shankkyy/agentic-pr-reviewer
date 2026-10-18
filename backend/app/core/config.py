"""Application settings loaded from environment variables (stdlib only).

Secrets (LLM_API_KEY) are read from the environment only and are never logged
or returned by any endpoint.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_float(name: str, default: float | None) -> float | None:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


_DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}
_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-5-5",
    "mock": "mock-deterministic-v1",
}


@dataclass(frozen=True)
class Settings:
    app_name: str = "Agentic PR Reviewer"
    app_version: str = "0.1.0"
    database_path: str = "data/reviews.db"
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
    max_upload_bytes: int = 1024 * 1024
    max_files: int = 50
    max_hunks: int = 500
    max_concurrent_reviews: int = 2
    review_timeout_seconds: float = 300.0
    static_tool_timeout_seconds: float = 30.0
    enable_static_tools: tuple[str, ...] = ("ruff", "bandit")
    llm_provider: str = "mock"
    llm_model: str = _DEFAULT_MODELS["mock"]
    llm_api_key: str = field(default="", repr=False)
    llm_base_url: str = ""
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_output_retries: int = 1
    llm_retry_backoff_seconds: float = 1.0
    llm_max_output_tokens: int = 2048
    llm_input_price_per_mtok: float | None = None
    llm_output_price_per_mtok: float | None = None
    max_review_prompt_chars: int = 40_000
    max_test_suggestions: int = 5
    log_level: str = "INFO"

    @property
    def mock_mode(self) -> bool:
        return self.llm_provider == "mock"

    @property
    def effective_base_url(self) -> str:
        return self.llm_base_url or _DEFAULT_BASE_URLS.get(self.llm_provider, "")

    @classmethod
    def from_env(cls) -> "Settings":
        provider = _env_str("LLM_PROVIDER", "mock").lower()
        if provider not in ("mock", "openai", "anthropic"):
            raise ValueError("LLM_PROVIDER must be one of: mock, openai, anthropic")
        tools = tuple(
            t.strip() for t in _env_str("ENABLE_STATIC_TOOLS", "ruff,bandit").split(",") if t.strip()
        )
        origins = tuple(
            o.strip() for o in _env_str("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()
        )
        return cls(
            database_path=_env_str("DATABASE_PATH", "data/reviews.db"),
            cors_origins=origins,
            max_upload_bytes=_env_int("MAX_UPLOAD_BYTES", 1024 * 1024),
            max_files=_env_int("MAX_FILES", 50),
            max_hunks=_env_int("MAX_HUNKS", 500),
            max_concurrent_reviews=max(1, _env_int("MAX_CONCURRENT_REVIEWS", 2)),
            review_timeout_seconds=_env_float("REVIEW_TIMEOUT_SECONDS", 300.0) or 300.0,
            static_tool_timeout_seconds=_env_float("STATIC_TOOL_TIMEOUT_SECONDS", 30.0) or 30.0,
            enable_static_tools=tools,
            llm_provider=provider,
            llm_model=_env_str("LLM_MODEL", _DEFAULT_MODELS.get(provider, "mock-deterministic-v1")),
            llm_api_key=_env_str("LLM_API_KEY", ""),
            llm_base_url=_env_str("LLM_BASE_URL", ""),
            llm_timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 60.0) or 60.0,
            llm_max_retries=_env_int("LLM_MAX_RETRIES", 2),
            llm_output_retries=_env_int("LLM_OUTPUT_RETRIES", 1),
            llm_retry_backoff_seconds=_env_float("LLM_RETRY_BACKOFF_SECONDS", 1.0) or 1.0,
            llm_max_output_tokens=_env_int("LLM_MAX_OUTPUT_TOKENS", 2048),
            llm_input_price_per_mtok=_env_float("LLM_INPUT_PRICE_PER_MTOK", None),
            llm_output_price_per_mtok=_env_float("LLM_OUTPUT_PRICE_PER_MTOK", None),
            max_review_prompt_chars=_env_int("MAX_REVIEW_PROMPT_CHARS", 40_000),
            max_test_suggestions=_env_int("MAX_TEST_SUGGESTIONS", 5),
            log_level=_env_str("LOG_LEVEL", "INFO").upper(),
        )
