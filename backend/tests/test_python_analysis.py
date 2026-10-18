"""Python context and focused AST check tests (stdlib unittest)."""

import unittest
from pathlib import Path

from app.services.ast_checks import run_ast_checks
from app.services.diff_parser import parse_diff
from app.services.python_context import build_python_context

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def diagnostics_for(text: str):
    ctx = build_python_context(parse_diff(text))
    return [d for s in ctx.snippets for d in run_ast_checks(s)], ctx


def single_file_diff(new_lines, old_lines=None, path="app/m.py"):
    """Build a one-hunk diff replacing old_lines with new_lines (exact counts)."""
    old_lines = old_lines or []
    body = [f"-{line}" for line in old_lines] + [f"+{line}" for line in new_lines]
    return (
        f"--- a/{path}\n+++ b/{path}\n"
        f"@@ -1,{len(old_lines)} +1,{len(new_lines)} @@\n" + "\n".join(body) + "\n"
    )


class AstChecksTests(unittest.TestCase):
    def test_clean_fixture_has_no_findings(self):
        diags, ctx = diagnostics_for((FIXTURES / "clean/clean_change.diff").read_text())
        self.assertEqual(diags, [])
        self.assertEqual(ctx.python_files, ["app/utils/totals.py"])

    def test_sql_fstring_flagged_on_added_line(self):
        diags, _ = diagnostics_for((FIXTURES / "security/sql_injection.diff").read_text())
        self.assertEqual([d.rule_id for d in diags], ["AST-SQL001"])
        self.assertEqual(diags[0].category, "security")
        self.assertEqual(diags[0].line, 6)
        self.assertEqual(diags[0].tool, "ast")

    def test_pickle_loads_flagged(self):
        diags, _ = diagnostics_for((FIXTURES / "security/unsafe_pickle.diff").read_text())
        self.assertEqual([d.rule_id for d in diags], ["AST-DESER001"])
        self.assertEqual(diags[0].line, 5)

    def test_parameterized_query_not_flagged(self):
        text = single_file_diff(
            ['    cur.execute("SELECT * FROM t WHERE id = ?", (uid,))'],
        )
        diags, _ = diagnostics_for(text)
        self.assertEqual(diags, [])

    def test_yaml_with_safe_loader_not_flagged_but_unsafe_flagged(self):
        safe = single_file_diff(["import yaml", "data = yaml.load(raw, Loader=yaml.SafeLoader)"])
        unsafe = single_file_diff(["import yaml", "data = yaml.load(raw)"])
        self.assertEqual(diagnostics_for(safe)[0], [])
        self.assertEqual([d.rule_id for d in diagnostics_for(unsafe)[0]], ["AST-DESER002"])

    def test_shell_true_with_computed_command(self):
        text = single_file_diff(["import subprocess", "subprocess.run(cmd + arg, shell=True)"])
        self.assertIn("AST-CMD001", [d.rule_id for d in diagnostics_for(text)[0]])

    def test_bare_except_and_mutable_default(self):
        text = single_file_diff(
            [
                "def f(items=[]):",
                "    try:",
                "        return items[0]",
                "    except:",
                "        return None",
            ]
        )
        ids = sorted(d.rule_id for d in diagnostics_for(text)[0])
        self.assertEqual(ids, ["AST-COR001", "AST-COR002"])

    def test_context_lines_never_produce_findings(self):
        # The vulnerable line is a context line (unchanged), so it must not be reported.
        text = (
            "--- a/app/r.py\n+++ b/app/r.py\n"
            "@@ -1,3 +1,4 @@\n"
            ' cur = conn.cursor()\n'
            ' cur.execute(f"SELECT * FROM t WHERE n = {name}")\n'
            "+x = 1\n"
            " return cur\n"
        )
        diags, _ = diagnostics_for(text)
        self.assertEqual(diags, [])


class PythonContextTests(unittest.TestCase):
    def test_deleted_binary_and_non_python_files_are_unsupported(self):
        text = (FIXTURES / "rename_delete/rename_delete_binary.diff").read_text()
        ctx = build_python_context(parse_diff(text))
        self.assertEqual(ctx.python_files, ["utils.py"])
        self.assertIn("legacy/report.py", ctx.unsupported_files)
        self.assertIn("assets/logo.png", ctx.unsupported_files)

    def test_non_python_extension_skipped(self):
        text = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-a\n+b\n"
        ctx = build_python_context(parse_diff(text))
        self.assertEqual(ctx.python_files, [])
        self.assertEqual(ctx.snippets, [])

    def test_unparseable_hunk_reported_as_insufficient_context(self):
        # A hunk that starts mid-block cannot parse on its own.
        text = (
            "--- a/app/p.py\n+++ b/app/p.py\n"
            "@@ -10,1 +10,2 @@\n"
            "        return value\n"
            "+    other = 1\n"
        )
        ctx = build_python_context(parse_diff(text))
        self.assertEqual(len(ctx.snippets), 1)
        snippet = ctx.snippets[0]
        self.assertFalse(snippet.parseable)
        self.assertIn("insufficient context", snippet.skip_reason)
        self.assertTrue(any("not parseable" in note for note in ctx.limitations))
        self.assertEqual(run_ast_checks(snippet), [])

    def test_line_map_matches_new_file_numbers(self):
        text = (FIXTURES / "security/sql_injection.diff").read_text()
        ctx = build_python_context(parse_diff(text))
        snippet = ctx.snippets[0]
        self.assertEqual(snippet.added_new_lines, {6})
        # Snippet line 5 (the execute call in the snippet) maps back to new-file line 6.
        self.assertEqual(snippet.line_map[snippet.text.splitlines().index(
            next(l for l in snippet.text.splitlines() if "execute" in l)) + 1], 6)


if __name__ == "__main__":
    unittest.main()
