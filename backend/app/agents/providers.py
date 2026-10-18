"""LLM providers: deterministic mock, OpenAI-compatible, and Anthropic.

Every provider returns raw text plus usage metadata. Parsing and validation happen
in the reviewers, so providers never decide whether output is acceptable.

Retries: transport-level failures (timeouts, connection errors, HTTP 429 and 5xx)
are retried a bounded number of times with exponential backoff. Retry-After is
honored up to 30 seconds. Other HTTP errors fail immediately. Error messages never
include response bodies or credentials.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import Settings
from app.core.observability import get_logger

log = get_logger("llm")

MAX_RETRY_AFTER_SECONDS = 30.0


class LLMError(Exception):
    """A provider call failed. `code` is one of: timeout, rate_limited, http_error, transport_error, misconfigured."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass
class LLMRequest:
    role: str  # "correctness" | "security" | "test_engineer"
    system: str
    user: str
    max_tokens: int
    timeout: float
    # Structured context for the deterministic mock. Real providers ignore it.
    mock_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: float


class LLMProvider(Protocol):
    name: str
    model: str
    is_mock: bool

    def complete(self, request: LLMRequest) -> LLMResponse: ...


# ---------------------------------------------------------------------------
# Deterministic mock provider
# ---------------------------------------------------------------------------

_MOCK_RULES: list[dict[str, Any]] = [
    {
        "role": "correctness",
        "pattern": re.compile(r"range\(\s*len\([^)]*\)\s*-\s*1\s*\)"),
        "title": "Loop bound skips the final element",
        "severity": "high",
        "fix": "Use `range(len(items))` or iterate directly over `items`.",
        "inference": "A `len(...) - 1` bound excludes the last index, which is usually unintended.",
    },
    {
        "role": "correctness",
        "pattern": re.compile(r"\b(end|stop|limit|upper)\w*\s*=.*\+\s*1\b"),
        "title": "Boundary value shifted by one",
        "severity": "medium",
        "fix": "Confirm the intended bound (exclusive vs inclusive) and remove the extra `+ 1` if unintended.",
        "inference": "An extra `+ 1` in a bound changes how many items a slice or range returns.",
    },
    {
        "role": "security",
        "pattern": re.compile(r"\.(execute|executemany)\(\s*(f[\"']|[\"'][^\"']*[\"']\s*%|[\"'][^\"']*[\"']\s*\.format\()"),
        "title": "Possible SQL injection via string-built query",
        "severity": "high",
        "fix": "Use bound parameters: pass values as a tuple argument to execute().",
        "inference": "The query text is built with interpolation, so untrusted input could alter the SQL statement.",
    },
    {
        "role": "security",
        "pattern": re.compile(r"\bpickle\.loads?\("),
        "title": "Deserialization of potentially untrusted data",
        "severity": "high",
        "fix": "Use JSON or another data-only format for data that crosses a trust boundary.",
        "inference": "pickle can execute code during loading; the input source is not validated in the diff.",
    },
    {
        "role": "security",
        "pattern": re.compile(r"(?i)\b(api_?key|secret|password|token)\w*\s*=\s*[\"'][^\"']{8,}[\"']"),
        "title": "Credential-like literal committed to source",
        "severity": "high",
        "fix": "Load the secret from the environment or a secrets manager and rotate the exposed value.",
        "inference": "A string literal assigned to a credential-like name appears to be a hard-coded secret.",
    },
    {
        "role": "security",
        "pattern": re.compile(r"\bverify\s*=\s*False\b"),
        "title": "TLS certificate verification disabled",
        "severity": "medium",
        "fix": "Remove `verify=False` or pin a trusted CA bundle.",
        "inference": "Disabling verification allows man-in-the-middle interception of the request.",
    },
]


def _mock_findings(role: str, added_lines: list[tuple[str, int, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path, line_no, text in added_lines:
        for rule in _MOCK_RULES:
            if rule["role"] != role or not rule["pattern"].search(text):
                continue
            quote = text.strip()
            out.append(
                {
                    "title": rule["title"],
                    "severity": rule["severity"],
                    "file_path": path,
                    "start_line": line_no,
                    "end_line": line_no,
                    "evidence": [quote[:300]],
                    "observed": f"Added line {line_no} contains `{quote[:120]}`.",
                    "inference": rule["inference"],
                    "suggested_fix": rule["fix"],
                    "confidence": 0.55,
                }
            )
    return out


class MockProvider:
    """Deterministic provider for offline runs and tests. Output is pattern-based and labelled as mock."""

    name = "mock"
    is_mock = True

    def __init__(self, model: str = "mock-deterministic-v1") -> None:
        self.model = model

    def complete(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        if request.role == "test_engineer":
            finding = request.mock_context.get("finding", {})
            title = str(finding.get("title", "finding"))
            slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40] or "finding"
            path = str(finding.get("file_path", "module.py"))
            line = finding.get("start_line", 1)
            payload = {
                "test_code": (
                    f"def test_{slug}_regression():\n"
                    f"    # Mock template: replace the placeholder with a real call to the code at {path}:{line}.\n"
                    f"    result = None  # TODO: call the changed function with a failing input\n"
                    f"    assert result is not None\n"
                ),
                "expected_behavior": f"Fails on the unpatched code path near {path}:{line} and passes after the suggested fix.",
            }
            text = json.dumps(payload)
        else:
            added = request.mock_context.get("added_lines", [])
            text = json.dumps({"findings": _mock_findings(request.role, added)})
        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=0,
            output_tokens=0,
            latency_ms=(time.perf_counter() - start) * 1000,
        )


# ---------------------------------------------------------------------------
# HTTP providers
# ---------------------------------------------------------------------------


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return min(float(raw), MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        return None


class _HTTPProviderBase:
    is_mock = False

    def __init__(
        self,
        *,
        name: str,
        model: str,
        base_url: str,
        api_key: str,
        max_retries: int,
        backoff_seconds: float,
        client_factory: Callable[[], httpx.Client] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._max_retries = max(0, max_retries)
        self._backoff = max(0.0, backoff_seconds)
        self._client_factory = client_factory or (lambda: httpx.Client())
        self._sleep = sleep

    def _build(self, request: LLMRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
        raise NotImplementedError

    def _parse(self, data: dict[str, Any]) -> tuple[str, int | None, int | None]:
        raise NotImplementedError

    def complete(self, request: LLMRequest) -> LLMResponse:
        if not self._api_key:
            raise LLMError("misconfigured", "LLM_API_KEY is not set for the configured provider")
        url, headers, body = self._build(request)
        attempts = self._max_retries + 1
        last: LLMError | None = None
        for attempt in range(attempts):
            start = time.perf_counter()
            try:
                with self._client_factory() as client:
                    resp = client.post(url, headers=headers, json=body, timeout=request.timeout)
            except httpx.TimeoutException as exc:
                last = LLMError("timeout", f"{self.name} request timed out", retryable=True)
                log.warning("llm_timeout", extra={"attempt": attempt + 1, "error": type(exc).__name__})
            except httpx.HTTPError as exc:
                last = LLMError("transport_error", f"{self.name} transport error: {type(exc).__name__}", retryable=True)
                log.warning("llm_transport_error", extra={"attempt": attempt + 1})
            else:
                if resp.status_code == 200:
                    try:
                        text, in_tok, out_tok = self._parse(resp.json())
                    except (ValueError, KeyError, IndexError, TypeError) as exc:
                        raise LLMError("invalid_response", f"{self.name} returned an unexpected payload") from exc
                    return LLMResponse(
                        text=text,
                        model=self.model,
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        latency_ms=(time.perf_counter() - start) * 1000,
                    )
                if resp.status_code == 429:
                    last = LLMError("rate_limited", f"{self.name} rate limit reached", retryable=True)
                    retry_after = _retry_after_seconds(resp)
                elif resp.status_code >= 500:
                    last = LLMError("http_error", f"{self.name} server error {resp.status_code}", retryable=True)
                    retry_after = None
                else:
                    raise LLMError("http_error", f"{self.name} rejected the request (HTTP {resp.status_code})")
                if attempt < attempts - 1:
                    delay = retry_after if retry_after is not None else self._backoff * (2**attempt)
                    self._sleep(min(delay, MAX_RETRY_AFTER_SECONDS))
                    continue
            if attempt < attempts - 1:
                self._sleep(min(self._backoff * (2**attempt), MAX_RETRY_AFTER_SECONDS))
        assert last is not None
        raise last


class OpenAICompatibleProvider(_HTTPProviderBase):
    def _build(self, request: LLMRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": request.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
        }
        return url, headers, body

    def _parse(self, data: dict[str, Any]) -> tuple[str, int | None, int | None]:
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        return str(text), usage.get("prompt_tokens"), usage.get("completion_tokens")


class AnthropicProvider(_HTTPProviderBase):
    def _build(self, request: LLMRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = f"{self._base_url}/v1/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "temperature": 0,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
        }
        return url, headers, body

    def _parse(self, data: dict[str, Any]) -> tuple[str, int | None, int | None]:
        parts = [block["text"] for block in data["content"] if block.get("type") == "text"]
        usage = data.get("usage") or {}
        return "".join(parts), usage.get("input_tokens"), usage.get("output_tokens")


def build_provider(settings: Settings, client_factory: Callable[[], httpx.Client] | None = None) -> LLMProvider:
    if settings.llm_provider == "mock":
        return MockProvider(settings.llm_model or "mock-deterministic-v1")
    common = dict(
        model=settings.llm_model,
        base_url=settings.effective_base_url,
        api_key=settings.llm_api_key,
        max_retries=settings.llm_max_retries,
        backoff_seconds=settings.llm_retry_backoff_seconds,
        client_factory=client_factory,
    )
    if settings.llm_provider == "openai":
        return OpenAICompatibleProvider(name="openai", **common)
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(name="anthropic", **common)
    raise ValueError(f"unsupported provider {settings.llm_provider!r}")
