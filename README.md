# Agentic PR Reviewer

A local developer tool that reviews unified Git diffs of Python code. You upload a `.diff` or `.patch` file (or paste diff text). The backend parses the diff, runs deterministic analyzers (Ruff, Bandit, focused AST checks), runs two specialist LLM reviewers (Correctness and Security) in parallel, deduplicates and verifies every finding against the diff, and stores the report in SQLite. The dashboard shows progress, findings, evidence, verification reasoning, and suggested (never executed) regression tests.

> **Status of this repository (read this first).** The code is complete for the MVP scope, but the authoring environment could not install Python packages or npm packages (no package-index access). Section [Verification status](#verification-status) lists exactly what was executed and what was not. Run the commands in [Local setup](#local-setup) and the test suite before relying on the application.

## Features

- Paste or upload a unified diff (1 MB default limit). Content is validated; filenames and extensions are not trusted.
- Diff parser for git-style and plain unified diffs: added, deleted, renamed, binary, and modified files; hunk counts are enforced, so truncated diffs are rejected.
- Path validation rejects traversal, absolute paths, backslashes, `.git` paths, and control characters.
- Deterministic analysis: Ruff (`E9,F63,F7,F632,B,S`), Bandit, and AST checks. Each diagnostic keeps its tool and rule ID. Only diagnostics on added lines are reported.
- LLM reviewers with schema validation, bounded output retries, provider timeouts, bounded transport retries with backoff, and Retry-After handling. Invalid model output is recorded as a failure, never converted to findings.
- Deduplication across analyzers and reviewers, with provenance kept in `reviewers` and `related_rules`.
- Verification with explicit decisions and reasons (`verified`, `rejected`, `needs_review`, `inconclusive`).
- Suggested regression tests labelled `SUGGESTED — NOT EXECUTED`. The MVP does not execute uploaded code or generated tests.
- Review jobs run in a background thread pool. Each job has states `queued`, `running`, `completed`, `partial`, `failed`, `cancelled`. Stage progress is persisted as it happens. Idempotency keys prevent duplicate reviews.
- SQLite persistence behind a repository interface, with review history.
- Mock mode: a deterministic provider runs the whole pipeline with no API key.

### Limitations

- **Diff-only context.** Analysis sees changed hunks plus their context lines. A hunk that does not parse on its own is reported as "insufficient context" and not analyzed by Ruff, Bandit, or the AST checks. Undefined-name checks are disabled because names may be defined outside the diff.
- **Pattern matches are not proof.** A Ruff, Bandit, or AST hit means the pattern occurs on a changed line. It does not establish that the code is exploitable.
- **Model-only findings stay `needs_review`** unless a deterministic check corroborates them. A model finding whose quoted evidence is not in the diff is `rejected` as a likely hallucination.
- **Mock mode is not an accuracy measurement.** Its rules were written with the fixtures in view, so mock results overstate what a real model would do. See [Evaluation](#evaluation).
- Python files only. Other languages are listed as unsupported.
- Single-user local tool. There is no authentication.

## Architecture

```
 Browser (Next.js)                          Backend (FastAPI)
 ┌──────────────────────┐   HTTP/JSON    ┌───────────────────────────────────────────────┐
 │ UploadPanel          │ ─────────────▶ │ api/routes.py  (validation + HTTP mapping)    │
 │ ProgressPanel (poll) │ ◀───────────── │   │                                           │
 │ FindingsDashboard    │                │   ▼                                           │
 │ FindingDetail        │                │ services/review_service.py                    │
 │ HistoryPanel         │                │   • job lifecycle, thread pool, cancel        │
 └──────────────────────┘                │   • streams LangGraph updates → job progress  │
                                         │   │                                           │
                                         │   ▼                                           │
                                         │ workflows/review_graph.py (LangGraph)         │
                                         │   input_preparation                           │
                                         │     ├─(no Python)──────────────┐              │
                                         │     ▼                          │              │
                                         │   deterministic_analysis       │              │
                                         │     ├─▶ correctness_review ──┐ │              │
                                         │     └─▶ security_review  ────┤ │              │
                                         │                              ▼ │              │
                                         │   deduplication (join) ◀─────┘ │              │
                                         │     ▼                          │              │
                                         │   verification                 │              │
                                         │     ▼                          │              │
                                         │   report_assembly ◀────────────┘              │
                                         │                                               │
                                         │ Services (no framework imports, stdlib only): │
                                         │   diff_parser · input_validation ·            │
                                         │   python_context · ast_checks ·               │
                                         │   static_analysis (Ruff/Bandit runners)       │
                                         │ Services: dedup · verification · report       │
                                         │ Agents: providers (mock/OpenAI/Anthropic) ·   │
                                         │   prompts · reviewers · Test Engineer         │
                                         │ repositories: ReviewRepository → SQLite       │
                                         └───────────────────────────────────────────────┘
```

### Workflow and agent responsibilities

| Stage | Responsibility | Failure behavior |
|---|---|---|
| `input_preparation` | Builds per-hunk Python snippets with an exact snippet-line → new-file-line map. Routes to report-only if the diff has no Python files. | Failure fails the job (`input_preparation_failed`). |
| `deterministic_analysis` | AST checks in-process; Ruff and Bandit on the snippets in a private temp directory. Missing tools are recorded as `unavailable`. | Tool failures and timeouts are recorded and make the job `partial`. |
| `correctness_review` | Correctness Reviewer (LLM). Validates output, retries malformed output up to `LLM_OUTPUT_RETRIES`. | Failed reviewer → `partial`. Other stages keep running. |
| `security_review` | Security Reviewer (LLM). Same contract as the Correctness Reviewer. | As above. |
| `deduplication` | Merges findings on the same file with overlapping lines and a shared category or similar title. The deterministic record is kept as primary. | — |
| `verification` | Checks line references against hunks, quoted evidence against the diff, corroboration, and remediation presence. | — |
| `report_assembly` | Test Engineer suggests tests for the top eligible findings (bounded by `MAX_TEST_SUGGESTIONS`). Builds counts, usage, and the report. | Test failures → `test_status: error`. |

Reviewers get the changed Python hunks with new-file line numbers, wrapped in `<untrusted_diff>` tags. The system prompt tells the model to treat that content as data. Output must be a JSON object matching `LLMReviewResponse`. Each finding separates `observed` (what the diff shows) from `inference` (labelled as inference). Quoted `evidence` must be exact added or context lines.

### Data contracts

`Finding` (Pydantic, `backend/app/schemas/findings.py`) has the fields `id`, `rule_id`, `tool`, `category`, `severity`, `title`, `file_path`, `start_line`, `end_line`, `explanation`, `evidence`, `suggested_fix`, `confidence`, `source_type`, `verification_status`, `verification_reason`, `test_status`, plus `reviewers`, `related_rules`, `code_excerpt`, `suggested_test`, and `suggested_test_behavior`. Enums are in `backend/app/schemas/enums.py`.

Workflow state is a `TypedDict`, which is LangGraph's native channel model. The values inside it are Pydantic models or explicit dataclasses. I chose this over a Pydantic state model because the reducer-based parallel merge is simpler to express with `TypedDict`.

## Technology stack

- Backend: Python 3.12, FastAPI 0.115, Pydantic 2.10, LangGraph 0.2.60, httpx, SQLite (stdlib `sqlite3`), Ruff 0.8.4, Bandit 1.8.0, pytest.
- Frontend: Next.js 14.2 (App Router), React 18.3, TypeScript 5.6, Tailwind CSS 3.4.
- LLM: `mock` (default), `openai` (any OpenAI-compatible Chat Completions endpoint), `anthropic` (Messages API).

## Local setup

Requirements: Python 3.12+, Node 20+. Docker is optional.

### Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# The app reads environment variables. Export them from the example file (never commit .env):
cp ../.env.example ../.env
set -a; source ../.env; set +a

uvicorn app.main:app --reload --port 8000
```

API docs are served at http://localhost:8000/docs.

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

Set `NEXT_PUBLIC_API_BASE_URL` if the backend is not at `http://localhost:8000`.

### Docker (optional)

```bash
docker compose up --build   # backend :8000, frontend :3000, mock mode by default
```

The Compose file has not been run in this environment (see [Verification status](#verification-status)).

### Regenerating fixtures

```bash
python3 fixtures/build_fixtures.py   # rewrites fixtures/**/*.diff and fixtures/benchmark/benchmark.json
```

## Environment variables

See `.env.example` for the full list with comments.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock`, `openai`, or `anthropic`. |
| `LLM_MODEL` | `mock-deterministic-v1` | Model name for the provider. |
| `LLM_API_KEY` | (empty) | Required for `openai`/`anthropic`. Never logged; redacted if it appears in an error. |
| `LLM_BASE_URL` | provider default | Override endpoint. |
| `LLM_TIMEOUT_SECONDS` | `60` | Per-call timeout. |
| `LLM_MAX_RETRIES` | `2` | Transport retries (timeouts, 429, 5xx). |
| `LLM_OUTPUT_RETRIES` | `1` | Retries when model output fails validation. |
| `LLM_RETRY_BACKOFF_SECONDS` | `1.0` | Exponential backoff base. Retry-After is honored up to 30 s. |
| `LLM_MAX_OUTPUT_TOKENS` | `2048` | Output cap per call. |
| `LLM_INPUT_PRICE_PER_MTOK`, `LLM_OUTPUT_PRICE_PER_MTOK` | (empty) | Set both to report estimated cost; otherwise cost is "not measured". |
| `MAX_UPLOAD_BYTES` | `1048576` | Upload size limit (1 MB). |
| `MAX_FILES`, `MAX_HUNKS` | `50`, `500` | Structural limits for the diff. |
| `MAX_REVIEW_PROMPT_CHARS` | `40000` | Reviewer prompt budget. Files beyond it are listed as omitted. |
| `MAX_TEST_SUGGESTIONS` | `5` | Test Engineer calls per review. |
| `MAX_CONCURRENT_REVIEWS` | `2` | Worker threads. |
| `REVIEW_TIMEOUT_SECONDS` | `300` | Whole-review deadline; remaining stages are skipped and recorded. |
| `STATIC_TOOL_TIMEOUT_SECONDS` | `30` | Per Ruff/Bandit run. |
| `ENABLE_STATIC_TOOLS` | `ruff,bandit` | Missing tools are reported as `unavailable`. |
| `DATABASE_PATH` | `data/reviews.db` | SQLite file. |
| `CORS_ORIGINS` | localhost:3000 | Allowed frontend origins. |
| `LOG_LEVEL` | `INFO` | Structured JSON logs to stdout. |

## Mock mode

With `LLM_PROVIDER=mock` (the default), no external call is made and no key is needed. The mock provider applies fixed pattern rules to added lines and returns schema-valid JSON, so the full pipeline (validation, dedup, verification, persistence, UI) runs end to end. The UI shows a "MOCK MODE · no API calls" badge, and every report has `mock_mode: true`. Mock findings are pattern-based and are not a model's judgment.

## API

All responses are JSON. Errors have the shape `{"error": {"code", "message", "request_id"}}` and never include stack traces or credentials. Every response carries `X-Request-ID`.

| Method and path | Purpose | Notes |
|---|---|---|
| `GET /health` | Health, mode, provider, enabled tools. | |
| `POST /api/reviews` | Create a review. Returns **202** with `review_id`. | `multipart/form-data` with a `file` field, or `application/json` `{"diff_text", "name"}`. Requires `Content-Length`. Optional `Idempotency-Key` header. |
| `GET /api/reviews?limit=&offset=` | Review history. | Newest first. |
| `GET /api/reviews/{id}` | Status, current stage, stage timings, counts, error. | Poll this while `queued` or `running`. |
| `GET /api/reviews/{id}/findings` | Findings. | Filters: `category`, `severity`, `verification_status`, `file_path`. **409** until the review finishes. |
| `GET /api/reviews/{id}/report` | Full report: findings, stages, reviewer runs, tool runs, usage, files, limitations, warnings. | **409** until the review finishes. |
| `POST /api/reviews/{id}/cancel` | Cancel a queued or running review. | Terminal reviews are returned unchanged. |

Status codes: 202 accepted, 400 bad idempotency key, 404 unknown review, 409 report not ready, 411 missing Content-Length, 413 too large, 415 unsupported media type, 422 malformed or unsafe diff, 500 internal error (generic message).

Example:

```bash
curl -s -X POST localhost:8000/api/reviews -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys;print(json.dumps({"diff_text":open("fixtures/buggy/off_by_one_pagination.diff").read(),"name":"demo.diff"}))')"
# → {"review_id":"rev_…","status":"queued",…}
curl -s localhost:8000/api/reviews/rev_…/findings | python3 -m json.tool
```

## Tests

```bash
cd backend
pytest                       # full suite (requires requirements-dev.txt)
cd tests && PYTHONPATH=.. python -m unittest test_diff_parser test_python_analysis test_static_analysis  # stdlib-only subset, no installs
```

Test files:

- `test_diff_parser.py`: header and hunk parsing, line mapping, rename/delete/binary, malformed and traversal inputs, limits, input validation, display-name sanitization.
- `test_python_analysis.py`: snippet construction, parseability, AST checks, tool-output mapping rules.
- `test_static_analysis.py`: missing tools, mapping, discarded out-of-change output, timeouts, crashes, bad JSON, and a real-Ruff/Bandit test that skips when the tools are absent.
- `test_findings_logic.py`: schema contracts, dedup, verification decisions (invalid line references, context lines, hallucinated evidence, missing evidence).
- `test_workflow.py`: the real LangGraph graph with fixtures: clean, logic bug, SQL injection, demo, invalid model output, schema-invalid output with bounded retries, reviewer timeout, static tool failure, missing tools, non-Python diffs, idempotency.
- `test_providers_api.py`: provider retry and rate-limit behavior via `httpx.MockTransport`, no secret leakage in errors, repository round-trips and interrupted-job recovery, API contract tests.

No test calls a paid API. The suite uses the mock provider and fake HTTP transports.

Frontend checks:

```bash
cd frontend
npm run lint
npm run typecheck
npm run build
```

## Evaluation

Benchmark: `fixtures/benchmark/benchmark.json`. It has 11 diffs: 5 clean changes and 6 changes that each contain one labelled issue (2 logic errors, 3 security issues detectable by deterministic rules, and 1 security issue that only the model path detects). Expected lines are computed from marker text by `fixtures/build_fixtures.py`, so labels track the fixture contents.

Matching: a predicted finding matches when the file and category are equal and the line is within ±1 of the label. Localization accuracy is the share of predicted findings that point at an added line, checked against the parsed diff.

```bash
cd backend
python -m eval.run_eval --mode ast                       # stdlib only: parser → context → AST checks
python -m eval.run_eval --mode full --provider mock      # full LangGraph pipeline, mock model
python -m eval.run_eval --mode full --provider mock --tools ruff,bandit   # with Ruff and Bandit installed
```

Results are written to `backend/eval/results/<mode>.json`.

**Measured: AST-only pipeline (`--mode ast`), run in the authoring sandbox.**

| Metric | Value |
|---|---|
| Cases | 11 (5 clean, 6 with one issue each) |
| True positives / false positives / false negatives | 3 / 0 / 3 |
| Precision | 1.000 |
| Recall | 0.500 (3 of 6) |
| False-positive rate on clean cases | 0 of 5 |
| Localization accuracy | 1.000 (3 of 3 predictions on added lines) |
| Latency per case, median / p95 | 0.32 ms / 0.39 ms (parse + context + AST checks, in-process) |
| Cost | not applicable (no LLM calls) |

The three missed issues are an off-by-one error, a `range(len(x) - 1)` loop bound, and `verify=False`. These need the model path or a rule that is not in the AST set. The sample is small: six issue cases cannot support a reliable precision or recall estimate.

**Not measured:** full mode (LangGraph, both reviewers, verification) with the mock and with real models, Ruff and Bandit recall, verification-outcome distribution, and cost per review with a real provider. Full mode was not run in this environment because the dependencies could not be installed. Its numbers would also overstate real-model performance, because the mock rules were written with these fixtures in view.

## Verification status

**Executed in the authoring sandbox** (Linux, Python 3.10.12 because Python 3.12 could not be downloaded; no network access to PyPI or npm):

- `python3 fixtures/build_fixtures.py`: generated all fixtures; benchmark markers each match exactly one line.
- `python3 -m unittest test_diff_parser test_python_analysis test_static_analysis`: **37 tests, all passed, 1 skipped.** The skipped test is the real Ruff/Bandit run, which requires those tools to be installed.
- `python3 -m py_compile` over every file in `backend/app`, `backend/tests`, and `backend/eval`: no errors.
- `python -m eval.run_eval --mode ast`: results above.

**Not executed.** These require the dependencies or Node packages, which were not available:

- The pytest suite beyond the stdlib subset. The `test_findings_logic.py`, `test_providers_api.py`, and most of `test_workflow.py` depend on Pydantic, FastAPI, httpx, and LangGraph. They have not been run, so expect at least some failures to fix on first run.
- Ruff and Bandit execution, including the real-tool test.
- The FastAPI server and the LangGraph graph at runtime.
- Frontend `npm install`, `npm run lint`, `npm run typecheck`, `npm run build`. TypeScript and React code was written carefully but not type-checked.
- Docker builds and `docker compose up`.
- Full-mode evaluation.

First step on a fresh machine: `pip install -r backend/requirements-dev.txt && cd backend && pytest`, then `npm run typecheck && npm run lint` in `frontend/`. Send back any failures.

## Security boundaries

- Uploaded code is never executed. Snippets are parsed (`ast.parse`) and passed to Ruff and Bandit as files. Tools run with a minimal environment, no shell, a temp working directory, and a timeout.
- No URL fetching and no repository cloning. Paths in the diff are validated and never used to read the local filesystem.
- Model output is treated as untrusted. It must validate against a Pydantic schema, and quoted evidence must appear in the diff. Reviewed code is fenced as data in prompts.
- Errors and logs do not include diff contents, model output, stack traces, or credentials. Known secret values and common key patterns are redacted from logs.
- Limits: upload size, file count, hunk count, prompt size, retries, timeouts, concurrent jobs, and test suggestions.
- The frontend displays only backend-provided text. Diff excerpts are rendered as text, not HTML.
- The application is intended for trusted local use. It has no authentication or multi-user isolation and should not be exposed to the internet.

## Design decisions and trade-offs

- **Stdlib core, Pydantic at the boundary.** Parsing, validation, snippet building, AST checks, and tool runners use only the standard library, so they can be tested without installing anything. Contracts that cross module or API boundaries are Pydantic models.
- **Per-hunk snippets instead of reconstructed files.** Each hunk becomes its own snippet with an exact line map. This avoids false positives from missing definitions, at the cost of seeing less context. Hunks that do not parse alone are skipped and reported.
- **Mapping only on added lines.** A finding on an unchanged context line is not reported as a changed-line finding. It is `needs_review` when a model proposes it, and dropped for tool output.
- **Parallel reviewers.** Both reviewers run in the same LangGraph superstep and join at deduplication. Each writes its own state key, so there are no write conflicts.
- **Failure isolation.** Nodes never raise into the graph. A failed reviewer, tool, or stage makes the job `partial` and keeps the other results.
- **Bounded retries only.** Model calls are bounded by `LLM_MAX_RETRIES` (transport) and `LLM_OUTPUT_RETRIES` (validation). There are no agent loops.
- **Background jobs in threads.** `ThreadPoolExecutor` keeps the MVP dependency-free. Jobs still in `queued` or `running` at restart are marked `failed` with code `interrupted`.
- **SQLite behind a repository protocol.** A PostgreSQL implementation only needs to satisfy `ReviewRepository`.
- **Tests are not executions.** Suggested tests are stored with `suggested_not_executed`. The MVP has no isolated test runner, and the interface for one is the separate `suggest_test` path, which can be extended later.

## Next recommended step

Run the full backend and frontend checks on a machine with package access (see [Verification status](#verification-status)) and fix what fails. Then add a real-model evaluation: run `--mode full --provider openai` (or `anthropic`) against the same benchmark with a labelled set several times larger than this one, and report precision, recall, false-positive rate, and cost per review from provider usage. After that, add the isolated test-execution service described above.
