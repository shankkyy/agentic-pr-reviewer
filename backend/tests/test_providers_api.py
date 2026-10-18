"""Provider retry behavior, repository round-trips, and API contract tests (mock provider only)."""

import json
import time
from datetime import UTC, datetime

import httpx
import pytest

from app.agents.providers import AnthropicProvider, LLMError, LLMRequest, MockProvider, OpenAICompatibleProvider
from app.agents.reviewers import parse_review_response
from app.repositories.review_repository import SQLiteReviewRepository
from app.schemas.enums import JobStatus
from app.schemas.reviews import ReviewJobView
from tests.conftest import fixture_text, wait_terminal


def request_obj(role="correctness"):
    return LLMRequest(role=role, system="s", user="u", max_tokens=100, timeout=5.0, mock_context={"added_lines": []})


def openai_provider(handler, retries=2):
    sleeps = []
    provider = OpenAICompatibleProvider(
        name="openai",
        model="gpt-test",
        base_url="https://example.invalid/v1",
        api_key="test-key-1234567",
        max_retries=retries,
        backoff_seconds=0.5,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )
    return provider, sleeps


OK_BODY = {
    "choices": [{"message": {"content": json.dumps({"findings": []})}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 7},
}


def test_mock_provider_is_deterministic():
    req = LLMRequest(role="security", system="s", user="u", max_tokens=10, timeout=1.0,
                     mock_context={"added_lines": [("a.py", 3, "cur.execute(f'SELECT {x}')")]})
    a = MockProvider().complete(req).text
    b = MockProvider().complete(req).text
    assert a == b
    assert json.loads(a)["findings"][0]["file_path"] == "a.py"


def test_openai_retries_rate_limit_then_succeeds_and_tracks_usage():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "2"}, json={"error": "slow down"})
        return httpx.Response(200, json=OK_BODY)

    provider, sleeps = openai_provider(handler)
    resp = provider.complete(request_obj())
    assert calls["n"] == 2
    assert sleeps == [2.0]  # Retry-After honored
    assert resp.input_tokens == 120 and resp.output_tokens == 7


def test_openai_gives_up_after_bounded_retries():
    provider, sleeps = openai_provider(lambda r: httpx.Response(503), retries=2)
    with pytest.raises(LLMError) as exc:
        provider.complete(request_obj())
    assert exc.value.code == "http_error"
    assert len(sleeps) == 2  # attempts = retries + 1, sleeping between them


def test_client_error_is_not_retried_and_message_has_no_body():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, text="secret echo sk-THISSHOULDNOTLEAK")

    provider, _ = openai_provider(handler)
    with pytest.raises(LLMError) as exc:
        provider.complete(request_obj())
    assert calls["n"] == 1
    assert "sk-THIS" not in exc.value.message


def test_timeout_is_classified():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    provider, _ = openai_provider(handler, retries=0)
    with pytest.raises(LLMError) as exc:
        provider.complete(request_obj())
    assert exc.value.code == "timeout"


def test_missing_api_key_is_misconfigured():
    provider = OpenAICompatibleProvider(name="openai", model="m", base_url="https://x", api_key="",
                                        max_retries=0, backoff_seconds=0)
    with pytest.raises(LLMError) as exc:
        provider.complete(request_obj())
    assert exc.value.code == "misconfigured"


def test_anthropic_request_shape_and_parse():
    seen = {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"findings": []}'}],
                                         "usage": {"input_tokens": 5, "output_tokens": 2}})

    provider = AnthropicProvider(name="anthropic", model="claude-haiku-5-5", base_url="https://api.example",
                                 api_key="k" * 12, max_retries=0, backoff_seconds=0,
                                 client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    resp = provider.complete(request_obj())
    assert seen["headers"]["x-api-key"] == "k" * 12
    assert seen["body"]["model"] == "claude-haiku-5-5"
    assert resp.output_tokens == 2


def test_invalid_model_output_never_becomes_findings():
    for bad in ["not json", "[]", '{"findings": [{"title": "x"}]}', '{"findings": "none"}']:
        with pytest.raises((ValueError, Exception)):
            parse_review_response(bad)
    assert parse_review_response('```json\n{"findings": []}\n```').findings == []


# -- repository --------------------------------------------------------------

def test_repository_roundtrip_and_interrupted_jobs(tmp_path):
    repo = SQLiteReviewRepository(str(tmp_path / "r.db"))
    now = datetime.now(UTC)
    job = ReviewJobView(review_id="rev_test000000000001", status=JobStatus.running, source_name="a.diff",
                        mock_mode=True, created_at=now, updated_at=now)
    repo.create_job(job, input_sha256="0" * 64, size_bytes=10, idempotency_key="key-abcdefgh")
    assert repo.find_by_idempotency_key("key-abcdefgh") == "rev_test000000000001"
    assert repo.get_report("rev_test000000000001") is None
    assert len(repo.list_items(10, 0)) == 1
    assert repo.mark_interrupted("restart") == 1
    assert repo.get_job("rev_test000000000001").status == JobStatus.failed
    assert repo.get_job("rev_test000000000001").error.code == "interrupted"


# -- API ---------------------------------------------------------------------

@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.review_service import ReviewService

    repo = SQLiteReviewRepository(settings.database_path)
    service = ReviewService(settings, repo, provider=MockProvider())
    app = create_app(settings, service=service)
    with TestClient(app) as c:
        yield c


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["mock_mode"] is True


def test_paste_review_end_to_end(client):
    resp = client.post("/api/reviews", json={"diff_text": fixture_text("buggy/off_by_one_pagination.diff"),
                                              "name": "bug.patch"})
    assert resp.status_code == 202
    review_id = resp.json()["review_id"]
    assert resp.headers["x-request-id"]
    # Poll the status endpoint until terminal.
    status = None
    for _ in range(600):
        status = client.get(f"/api/reviews/{review_id}").json()["status"]
        if status in ("completed", "partial", "failed", "cancelled"):
            break
        time.sleep(0.02)
    assert status == "completed"
    findings = client.get(f"/api/reviews/{review_id}/findings").json()
    assert len(findings) == 1
    assert findings[0]["verification_status"] == "needs_review"
    report = client.get(f"/api/reviews/{review_id}/report").json()
    assert report["source_name"] == "bug.patch"
    assert report["mock_mode"] is True
    listing = client.get("/api/reviews").json()
    assert listing[0]["review_id"] == review_id


def test_upload_multipart_accepted(client):
    data = fixture_text("security/sql_injection.diff").encode()
    resp = client.post("/api/reviews", files={"file": ("anything.txt", data, "text/plain")})
    assert resp.status_code == 202


def test_malformed_diff_rejected_with_message(client):
    resp = client.post("/api/reviews", json={"diff_text": fixture_text("malformed/bad_hunk_counts.diff")})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "malformed_diff"


def test_path_traversal_rejected(client):
    resp = client.post("/api/reviews", json={"diff_text": fixture_text("malformed/path_traversal.diff")})
    assert resp.status_code == 422
    assert "traversal" in resp.json()["error"]["message"]


def test_empty_and_wrong_content_type(client):
    assert client.post("/api/reviews", json={"diff_text": "   "}).status_code == 422
    assert client.post("/api/reviews", content=b"x", headers={"content-type": "text/plain"}).status_code == 415


def test_oversized_upload_rejected(client, settings):
    big = b"+" * (settings.max_upload_bytes + 10)
    resp = client.post("/api/reviews", files={"file": ("big.diff", big, "text/plain")})
    assert resp.status_code == 413


def test_unknown_review_is_404_and_bad_idempotency_key_is_400(client):
    assert client.get("/api/reviews/rev_missing0000000").status_code == 404
    resp = client.post("/api/reviews", json={"diff_text": fixture_text("clean/clean_change.diff")},
                       headers={"Idempotency-Key": "bad key!"})
    assert resp.status_code == 400


def test_errors_never_expose_traceback(client):
    body = client.get("/api/reviews/rev_missing0000000").text
    assert "Traceback" not in body
    assert "error" in json.loads(body)
