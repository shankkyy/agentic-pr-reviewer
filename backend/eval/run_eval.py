"""Evaluation harness for the labeled benchmark (fixtures/benchmark/benchmark.json).

Modes:
  ast   Stdlib-only pipeline: diff parsing -> Python context -> AST checks.
        No LLM, no Ruff/Bandit, no third-party packages. Runs anywhere Python 3.11+ runs.
  full  The real review service (LangGraph workflow) with the configured provider and
        static tools. Requires backend requirements to be installed.

Matching rule: a predicted finding matches an expected issue when the file and
category are equal and the predicted line is within +/- 1 of the labeled line.
Localization accuracy is the share of predicted findings that point at an added
line of the diff (checked against the parsed diff, not the analyzer's claim).

Usage (from backend/):
  python -m eval.run_eval --mode ast
  python -m eval.run_eval --mode full --provider mock
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = REPO_ROOT / "fixtures" / "benchmark" / "benchmark.json"
RESULTS_DIR = REPO_ROOT / "backend" / "eval" / "results"
LINE_TOLERANCE = 1


@dataclass
class Prediction:
    file_path: str
    line: int | None
    category: str
    source: str
    verification: str | None = None
    on_added_line: bool | None = None


@dataclass
class CaseResult:
    case_id: str
    label: str
    expected: list[dict[str, Any]]
    predictions: list[Prediction] = field(default_factory=list)
    latency_ms: float = 0.0
    error: str | None = None
    llm_calls: int = 0
    cost_usd: float | None = None


def load_cases() -> list[dict[str, Any]]:
    data = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    return data["cases"]


def _diff_text(case: dict[str, Any]) -> str:
    return (REPO_ROOT / case["diff"]).read_text(encoding="utf-8")


def run_ast_mode(case: dict[str, Any]) -> CaseResult:
    from app.services.diff_parser import parse_diff
    from app.services.python_context import build_python_context
    from app.services.static_analysis import run_static_analysis

    result = CaseResult(case_id=case["id"], label=case["label"], expected=case["expected"])
    start = time.perf_counter()
    text = _diff_text(case)
    parsed = parse_diff(text)
    ctx = build_python_context(parsed)
    static = run_static_analysis(ctx, enable_tools=())
    result.latency_ms = (time.perf_counter() - start) * 1000
    for d in static.diagnostics:
        mapped = parsed.map_line(d.file_path, d.line).mapped
        result.predictions.append(
            Prediction(d.file_path, d.line, d.category, f"{d.tool}:{d.rule_id}", None, mapped)
        )
    return result


def run_full_mode(case: dict[str, Any], provider_name: str, enable_tools: tuple[str, ...]) -> CaseResult:
    import tempfile

    from app.agents.providers import MockProvider
    from app.core.config import Settings
    from app.repositories.review_repository import SQLiteReviewRepository
    from app.services.diff_parser import parse_diff
    from app.services.input_validation import validate_diff_text
    from app.services.review_service import TERMINAL, ReviewService

    result = CaseResult(case_id=case["id"], label=case["label"], expected=case["expected"])
    with tempfile.TemporaryDirectory(prefix="apr-eval-") as tmp:
        cfg = Settings(
            database_path=str(Path(tmp) / "eval.db"),
            llm_provider="mock",
            llm_model="mock-deterministic-v1",
            enable_static_tools=enable_tools,
            llm_retry_backoff_seconds=0.0,
        )
        provider = MockProvider(cfg.llm_model) if provider_name == "mock" else _NullProvider()
        service = ReviewService(cfg, SQLiteReviewRepository(cfg.database_path), provider=provider)
        try:
            diff = validate_diff_text(
                _diff_text(case),
                max_bytes=cfg.max_upload_bytes,
                max_files=cfg.max_files,
                max_hunks=cfg.max_hunks,
                display_name=case["id"],
            )
            parsed = parse_diff(diff.text)
            start = time.perf_counter()
            job, _ = service.submit(diff)
            while service.get_job(job.review_id).status not in TERMINAL:
                time.sleep(0.02)
            job = service.get_job(job.review_id)
            result.latency_ms = (time.perf_counter() - start) * 1000
            report = service.get_report(job.review_id)
            result.llm_calls = report.usage.llm_calls
            result.cost_usd = report.usage.estimated_cost_usd
            for f in report.findings:
                mapped = parsed.map_line(f.file_path, f.start_line).mapped if f.start_line else False
                result.predictions.append(
                    Prediction(
                        f.file_path,
                        f.start_line,
                        f.category.value,
                        f"{f.source_type.value}:{f.rule_id or f.tool}",
                        f.verification_status.value,
                        mapped,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - record and continue the benchmark
            result.error = type(exc).__name__
        finally:
            service.shutdown()
    return result


class _NullProvider:
    """Model that returns no findings. Measures the deterministic pipeline alone."""

    name = "none"
    model = "none"
    is_mock = True

    def complete(self, request: Any) -> Any:
        from app.agents.providers import LLMResponse

        return LLMResponse(text='{"findings": []}', model="none", input_tokens=0, output_tokens=0, latency_ms=0.0)


def score(results: list[CaseResult]) -> dict[str, Any]:
    tp = fp = fn = 0
    clean_cases = [r for r in results if r.label == "clean" and r.error is None]
    clean_with_fp = 0
    localization_total = localization_ok = 0
    verification_counts: dict[str, int] = {}
    per_case = []
    for r in results:
        if r.error is not None:
            per_case.append({"id": r.case_id, "error": r.error})
            continue
        unmatched_expected = list(r.expected)
        unmatched_pred = []
        for p in r.predictions:
            hit = None
            for e in unmatched_expected:
                if (
                    e["file"] == p.file_path
                    and e["category"] == p.category
                    and p.line is not None
                    and abs(e["line"] - p.line) <= LINE_TOLERANCE
                ):
                    hit = e
                    break
            if hit is None:
                unmatched_pred.append(p)
            else:
                unmatched_expected.remove(hit)
                tp += 1
            if p.on_added_line is not None:
                localization_total += 1
                localization_ok += int(bool(p.on_added_line))
            if p.verification is not None:
                verification_counts[p.verification] = verification_counts.get(p.verification, 0) + 1
        fp += len(unmatched_pred)
        fn += len(unmatched_expected)
        if r.label == "clean" and r.predictions:
            clean_with_fp += 1
        per_case.append(
            {
                "id": r.case_id,
                "label": r.label,
                "expected": len(r.expected),
                "predicted": len(r.predictions),
                "latency_ms": round(r.latency_ms, 2),
                "llm_calls": r.llm_calls,
                "cost_usd": r.cost_usd,
            }
        )
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    latencies = [r.latency_ms for r in results if r.error is None]
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    return {
        "cases_total": len(results),
        "cases_clean": len(clean_cases),
        "cases_with_issue": sum(1 for r in results if r.label == "issue"),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": None if precision is None else round(precision, 3),
        "recall": None if recall is None else round(recall, 3),
        "false_positive_rate_clean_cases": round(clean_with_fp / len(clean_cases), 3) if clean_cases else None,
        "localization_accuracy": round(localization_ok / localization_total, 3) if localization_total else None,
        "verification_outcomes": verification_counts,
        "latency_ms_median": round(statistics.median(latencies), 2) if latencies else None,
        "latency_ms_p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else None,
        "total_cost_usd": round(sum(costs), 6) if costs else None,
        "errors": [r.case_id for r in results if r.error],
        "per_case": per_case,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["ast", "full"], default="ast")
    parser.add_argument("--provider", choices=["mock", "none"], default="mock", help="full mode only")
    parser.add_argument("--tools", default="", help="full mode: comma-separated ruff,bandit (default none)")
    parser.add_argument("--out", default=None, help="write JSON results to this path")
    args = parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT / "backend"))
    cases = load_cases()
    results: list[CaseResult] = []
    for case in cases:
        if args.mode == "ast":
            results.append(run_ast_mode(case))
        else:
            tools = tuple(t for t in args.tools.split(",") if t)
            results.append(run_full_mode(case, args.provider, tools))

    summary = score(results)
    payload = {
        "mode": args.mode,
        "provider": "n/a" if args.mode == "ast" else args.provider,
        "tools": "n/a" if args.mode == "ast" else (args.tools or "none"),
        "benchmark": str(BENCHMARK.relative_to(REPO_ROOT)),
        "summary": summary,
    }
    out = Path(args.out) if args.out else RESULTS_DIR / f"{args.mode}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "per_case"}, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
