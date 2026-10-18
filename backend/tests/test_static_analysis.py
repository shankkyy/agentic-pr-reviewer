"""Static-analysis service tests with fake tool runners (stdlib unittest).

Real Ruff/Bandit runs are covered by tests that skip when the tools are not installed.
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from app.services.diff_parser import parse_diff
from app.services.python_context import build_python_context
from app.services.static_analysis import run_static_analysis

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def sql_context():
    return build_python_context(parse_diff((FIXTURES / "security/sql_injection.diff").read_text()))


def fake_which(available):
    def which(name):
        return f"/usr/bin/{name}" if name in available else None

    return which


def completed(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def ruff_payload(filename, row, code, message="msg"):
    return json.dumps(
        [{"code": code, "message": message, "filename": f"/tmp/x/{filename}",
          "location": {"row": row, "column": 1}}]
    )


def bandit_payload(filename, line, test_id="B608"):
    return json.dumps(
        {"results": [{"filename": f"/tmp/x/{filename}", "line_number": line, "test_id": test_id,
                      "test_name": "hardcoded_sql_expressions", "issue_severity": "MEDIUM",
                      "issue_confidence": "HIGH", "issue_text": "Possible SQL injection"}],
         "errors": []}
    )


class StaticAnalysisTests(unittest.TestCase):
    def test_missing_tools_are_reported_not_raised(self):
        result = run_static_analysis(sql_context(), which=fake_which(set()), runner=None)
        statuses = {r.tool: r.status for r in result.tool_runs}
        self.assertEqual(statuses["ruff"], "unavailable")
        self.assertEqual(statuses["bandit"], "unavailable")
        self.assertEqual(statuses["ast"], "completed")
        # AST still produces the deterministic finding without external tools.
        self.assertEqual([d.rule_id for d in result.diagnostics], ["AST-SQL001"])

    def test_ruff_and_bandit_output_mapped_to_added_line(self):
        def runner(cmd, **kwargs):
            if "ruff" in cmd[0]:
                # Snippet row 4 is new-file line 6 (the hunk starts at new line 3).
                return completed(ruff_payload("snippet_0001.py", 4, "S608"))
            return completed(bandit_payload("snippet_0001.py", 4), returncode=1)

        result = run_static_analysis(sql_context(), which=fake_which({"ruff", "bandit"}), runner=runner)
        by_tool = {(d.tool, d.rule_id): d for d in result.diagnostics}
        self.assertIn(("ruff", "S608"), by_tool)
        self.assertIn(("bandit", "B608"), by_tool)
        self.assertEqual(by_tool[("ruff", "S608")].line, 6)
        self.assertEqual(by_tool[("bandit", "B608")].category, "security")
        self.assertEqual(by_tool[("bandit", "B608")].severity, "medium")

    def test_tool_output_on_context_line_is_discarded(self):
        def runner(cmd, **kwargs):
            if "ruff" in cmd[0]:
                # Row 1 is the unchanged `import sqlite3` context line.
                return completed(ruff_payload("snippet_0001.py", 1, "S608"))
            return completed(bandit_payload("snippet_0001.py", 1), returncode=0)

        result = run_static_analysis(sql_context(), which=fake_which({"ruff", "bandit"}), runner=runner)
        self.assertEqual([d.tool for d in result.diagnostics], ["ast"])  # only AST remains
        self.assertEqual(result.discarded_outside_change, 2)

    def test_tool_timeout_is_recorded(self):
        def runner(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 1)

        result = run_static_analysis(sql_context(), which=fake_which({"ruff", "bandit"}), runner=runner)
        statuses = {r.tool: r.status for r in result.tool_runs}
        self.assertEqual(statuses["ruff"], "timeout")
        self.assertEqual(statuses["bandit"], "timeout")

    def test_tool_crash_and_bad_json_are_failures(self):
        def crash(cmd, **kwargs):
            return completed("", returncode=2)

        result = run_static_analysis(sql_context(), which=fake_which({"ruff", "bandit"}), runner=crash)
        self.assertEqual({r.tool: r.status for r in result.tool_runs}["ruff"], "failed")

        def garbage(cmd, **kwargs):
            return completed("not json at all", returncode=0)

        result = run_static_analysis(sql_context(), which=fake_which({"ruff", "bandit"}), runner=garbage)
        statuses = {r.tool: r.status for r in result.tool_runs}
        self.assertEqual(statuses["ruff"], "failed")
        self.assertEqual(statuses["bandit"], "failed")
        # The workflow still gets the deterministic AST result.
        self.assertTrue(any(d.tool == "ast" for d in result.diagnostics))

    def test_oserror_from_runner_does_not_escape(self):
        def boom(cmd, **kwargs):
            raise PermissionError("denied")

        result = run_static_analysis(sql_context(), which=fake_which({"ruff", "bandit"}), runner=boom)
        self.assertEqual({r.tool: r.status for r in result.tool_runs}["bandit"], "failed")

    def test_no_python_snippets_skips_tools(self):
        ctx = build_python_context(parse_diff((FIXTURES / "rename_delete/rename_delete_binary.diff").read_text()))
        result = run_static_analysis(ctx, which=fake_which({"ruff", "bandit"}), runner=None)
        self.assertEqual({r.tool: r.status for r in result.tool_runs}["ruff"], "skipped")
        self.assertEqual(result.snippets_analyzed, 0)

    @unittest.skipUnless(shutil.which("ruff") and shutil.which("bandit"), "ruff and bandit not installed")
    def test_real_tools_flag_sql_injection(self):
        result = run_static_analysis(sql_context())
        rules = {(d.tool, d.rule_id) for d in result.diagnostics}
        self.assertIn(("ruff", "S608"), rules)
        self.assertIn(("bandit", "B608"), rules)


if __name__ == "__main__":
    unittest.main()
