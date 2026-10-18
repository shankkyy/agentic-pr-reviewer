"""Deterministic static-analysis service (stdlib only).

Runs AST checks in-process and Ruff and Bandit as subprocesses over snippet files
written to a private temporary directory. Snippets are only parsed by the tools,
never executed. Tool output is mapped back to changed lines only through the
snippet line map; anything else is discarded and counted.

Tool runs never raise into the workflow: missing tools, timeouts, non-zero exits
with unusable output, and malformed JSON are returned as ToolRun records.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.ast_checks import run_ast_checks
from app.services.diagnostics import RawDiagnostic
from app.services.python_context import PythonContext, Snippet

RUFF_SELECT = "E9,F63,F7,F632,B,S"
RUFF_IGNORE = "S101,B011"
MAX_TOOL_OUTPUT_BYTES = 5 * 1024 * 1024
BANDIT_SEVERITY = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
BANDIT_CONFIDENCE = {"HIGH": 0.9, "MEDIUM": 0.7, "LOW": 0.4}

Which = Callable[[str], "str | None"]
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass
class ToolRun:
    tool: str
    status: str  # completed | unavailable | failed | timeout | skipped
    duration_ms: float
    diagnostics: int = 0
    message: str = ""


@dataclass
class StaticAnalysisResult:
    diagnostics: list[RawDiagnostic] = field(default_factory=list)
    tool_runs: list[ToolRun] = field(default_factory=list)
    discarded_outside_change: int = 0
    snippets_analyzed: int = 0


def _safe_message(text: str, limit: int = 240) -> str:
    cleaned = " ".join(text.split())
    return cleaned[:limit]


def _map_snippet_line(snippet: Snippet, row: int) -> int | None:
    new_line = snippet.line_map.get(row)
    if new_line is None or new_line not in snippet.added_new_lines:
        return None
    return new_line


def _ruff_category(code: str) -> str:
    return "security" if code.startswith("S") else "correctness"


def _run_ruff(
    files_dir: Path,
    snippets_by_name: dict[str, Snippet],
    timeout: float,
    which: Which,
    runner: Runner,
    env: dict[str, str],
) -> tuple[ToolRun, list[RawDiagnostic], int]:
    start = time.perf_counter()
    binary = which("ruff")
    if binary is None:
        return ToolRun("ruff", "unavailable", 0.0, message="ruff is not installed"), [], 0
    cmd = [
        binary, "check", "--output-format", "json", "--no-cache", "--isolated",
        "--exit-zero", "--select", RUFF_SELECT, "--ignore", RUFF_IGNORE, str(files_dir),
    ]
    try:
        proc = runner(cmd, cwd=str(files_dir), env=env, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return ToolRun("ruff", "timeout", (time.perf_counter() - start) * 1000, message="ruff timed out"), [], 0
    except OSError as exc:
        return ToolRun("ruff", "failed", (time.perf_counter() - start) * 1000, message=f"ruff could not run: {type(exc).__name__}"), [], 0
    elapsed = (time.perf_counter() - start) * 1000
    if proc.returncode != 0 or len(proc.stdout) > MAX_TOOL_OUTPUT_BYTES:
        return ToolRun("ruff", "failed", elapsed, message=f"ruff exited with code {proc.returncode}"), [], 0
    try:
        items: list[dict[str, Any]] = json.loads(proc.stdout or "[]")
        if not isinstance(items, list):
            raise ValueError("expected a JSON list")
    except (ValueError, TypeError):
        return ToolRun("ruff", "failed", elapsed, message="ruff produced unparseable output"), [], 0

    diags: list[RawDiagnostic] = []
    discarded = 0
    seen: set[tuple[str, int, str]] = set()
    for item in items:
        code = item.get("code")
        filename = os.path.basename(str(item.get("filename", "")))
        snippet = snippets_by_name.get(filename)
        location = item.get("location") or {}
        row = location.get("row")
        if not code or snippet is None or not isinstance(row, int):
            discarded += 1
            continue
        new_line = _map_snippet_line(snippet, row)
        if new_line is None:
            discarded += 1
            continue
        key = (snippet.file_path, new_line, code)
        if key in seen:
            continue
        seen.add(key)
        diags.append(
            RawDiagnostic(
                tool="ruff",
                rule_id=code,
                title=_safe_message(str(item.get("message", "Ruff finding")), 120),
                message=_safe_message(str(item.get("message", ""))),
                category=_ruff_category(code),
                severity="medium" if code.startswith("S") else "low",
                confidence=0.6,
                file_path=snippet.file_path,
                line=new_line,
                excerpt=snippet.excerpts.get(new_line, "")[:300],
            )
        )
    return ToolRun("ruff", "completed", elapsed, diagnostics=len(diags)), diags, discarded


def _run_bandit(
    files_dir: Path,
    snippets_by_name: dict[str, Snippet],
    timeout: float,
    which: Which,
    runner: Runner,
    env: dict[str, str],
) -> tuple[ToolRun, list[RawDiagnostic], int]:
    start = time.perf_counter()
    binary = which("bandit")
    if binary is None:
        return ToolRun("bandit", "unavailable", 0.0, message="bandit is not installed"), [], 0
    cmd = [binary, "-q", "-f", "json", "-r", str(files_dir)]
    try:
        proc = runner(cmd, cwd=str(files_dir), env=env, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return ToolRun("bandit", "timeout", (time.perf_counter() - start) * 1000, message="bandit timed out"), [], 0
    except OSError as exc:
        return ToolRun("bandit", "failed", (time.perf_counter() - start) * 1000, message=f"bandit could not run: {type(exc).__name__}"), [], 0
    elapsed = (time.perf_counter() - start) * 1000
    # Bandit exits 1 when it reports issues; anything other than 0 or 1 is a failure.
    if proc.returncode not in (0, 1) or len(proc.stdout) > MAX_TOOL_OUTPUT_BYTES:
        return ToolRun("bandit", "failed", elapsed, message=f"bandit exited with code {proc.returncode}"), [], 0
    try:
        payload = json.loads(proc.stdout or "{}")
        results = payload.get("results", [])
        if not isinstance(results, list):
            raise ValueError("results is not a list")
    except (ValueError, TypeError, AttributeError):
        return ToolRun("bandit", "failed", elapsed, message="bandit produced unparseable output"), [], 0

    diags: list[RawDiagnostic] = []
    discarded = 0
    seen: set[tuple[str, int, str]] = set()
    for item in results:
        filename = os.path.basename(str(item.get("filename", "")))
        snippet = snippets_by_name.get(filename)
        row = item.get("line_number")
        test_id = item.get("test_id")
        if snippet is None or not isinstance(row, int) or not test_id:
            discarded += 1
            continue
        new_line = _map_snippet_line(snippet, row)
        if new_line is None:
            discarded += 1
            continue
        key = (snippet.file_path, new_line, str(test_id))
        if key in seen:
            continue
        seen.add(key)
        sev = str(item.get("issue_severity", "LOW")).upper()
        conf = str(item.get("issue_confidence", "LOW")).upper()
        diags.append(
            RawDiagnostic(
                tool="bandit",
                rule_id=str(test_id),
                title=_safe_message(str(item.get("test_name", "Bandit finding")).replace("_", " "), 120),
                message=_safe_message(str(item.get("issue_text", ""))),
                category="security",
                severity=BANDIT_SEVERITY.get(sev, "low"),
                confidence=BANDIT_CONFIDENCE.get(conf, 0.4),
                file_path=snippet.file_path,
                line=new_line,
                excerpt=snippet.excerpts.get(new_line, "")[:300],
            )
        )
    return ToolRun("bandit", "completed", elapsed, diagnostics=len(diags)), diags, discarded


def run_static_analysis(
    context: PythonContext,
    *,
    tool_timeout: float = 30.0,
    which: Which | None = None,
    runner: Runner | None = None,
    enable_tools: tuple[str, ...] = ("ruff", "bandit"),
) -> StaticAnalysisResult:
    """Run AST checks plus the configured external tools over every analyzable snippet.

    `which` and `runner` are resolved at call time (not import time) so tests can inject fakes.
    """
    which = which or shutil.which
    runner = runner or subprocess.run
    result = StaticAnalysisResult()
    analyzable = [s for s in context.snippets if s.parseable and s.has_added_lines]
    result.snippets_analyzed = len(analyzable)

    start = time.perf_counter()
    ast_diags: list[RawDiagnostic] = []
    for snippet in analyzable:
        ast_diags.extend(run_ast_checks(snippet))
    result.diagnostics.extend(ast_diags)
    result.tool_runs.append(
        ToolRun("ast", "completed", (time.perf_counter() - start) * 1000, diagnostics=len(ast_diags))
    )

    if not analyzable:
        for tool in enable_tools:
            result.tool_runs.append(ToolRun(tool, "skipped", 0.0, message="no analyzable Python snippets"))
        return result

    env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    with tempfile.TemporaryDirectory(prefix="apr-snippets-") as tmp:
        tmp_path = Path(tmp)
        env["HOME"] = tmp
        snippets_by_name: dict[str, Snippet] = {}
        for idx, snippet in enumerate(analyzable, start=1):
            name = f"snippet_{idx:04d}.py"
            (tmp_path / name).write_text(snippet.text, encoding="utf-8")
            snippets_by_name[name] = snippet
        if "ruff" in enable_tools:
            run, diags, discarded = _run_ruff(tmp_path, snippets_by_name, tool_timeout, which, runner, env)
            result.tool_runs.append(run)
            result.diagnostics.extend(diags)
            result.discarded_outside_change += discarded
        if "bandit" in enable_tools:
            run, diags, discarded = _run_bandit(tmp_path, snippets_by_name, tool_timeout, which, runner, env)
            result.tool_runs.append(run)
            result.diagnostics.extend(diags)
            result.discarded_outside_change += discarded
    return result
