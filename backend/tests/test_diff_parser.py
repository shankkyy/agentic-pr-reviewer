"""Diff parsing, line mapping, and path validation tests (stdlib unittest; also collected by pytest)."""

import unittest
from pathlib import Path

from app.services.diff_parser import DiffParseError, parse_diff
from app.services.input_validation import InputValidationError, sanitize_display_name, validate_diff_text

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def read(rel: str) -> str:
    return (FIXTURES / rel).read_text(encoding="utf-8")


class DiffParserTests(unittest.TestCase):
    def test_clean_fixture_maps_added_lines(self):
        parsed = parse_diff(read("clean/clean_change.diff"))
        self.assertEqual(len(parsed.files), 1)
        f = parsed.files[0]
        self.assertEqual(f.path, "app/utils/totals.py")
        self.assertEqual(f.status, "modified")
        # Added lines are reported with new-file numbering.
        self.assertTrue(parsed.map_line("app/utils/totals.py", 4).mapped)
        self.assertTrue(f.added_line_numbers)
        for n in f.added_line_numbers:
            self.assertTrue(parsed.map_line(f.path, n).mapped)

    def test_context_and_unknown_lines_are_not_mapped(self):
        parsed = parse_diff(read("buggy/off_by_one_pagination.diff"))
        path = "app/services/pagination.py"
        # Line 1 is an unchanged context line.
        result = parsed.map_line(path, 1)
        self.assertFalse(result.mapped)
        self.assertIn("not an added line", result.reason)
        # Line 999 is outside the hunk entirely.
        self.assertFalse(parsed.map_line(path, 999).mapped)
        # Unknown file.
        self.assertFalse(parsed.map_line("other.py", 3).mapped)

    def test_added_line_in_buggy_fixture(self):
        parsed = parse_diff(read("buggy/off_by_one_pagination.diff"))
        self.assertEqual(parsed.files[0].added_text(), {3: "    end = start + size + 1"})
        self.assertTrue(parsed.map_line("app/services/pagination.py", 3).mapped)

    def test_rename_delete_and_binary_statuses(self):
        parsed = parse_diff(read("rename_delete/rename_delete_binary.diff"))
        by_path = {f.path: f for f in parsed.files}
        self.assertEqual(by_path["utils.py"].status, "renamed")
        self.assertEqual(by_path["utils.py"].old_path, "old_utils.py")
        self.assertEqual(by_path["legacy/report.py"].status, "deleted")
        self.assertIsNone(by_path["legacy/report.py"].new_path)
        self.assertFalse(parsed.map_line("legacy/report.py", 1).mapped)
        self.assertTrue(by_path["assets/logo.png"].is_binary)
        self.assertEqual(by_path["assets/logo.png"].status, "binary")
        self.assertFalse(parsed.map_line("assets/logo.png", 1).mapped)

    def test_truncated_hunk_is_rejected(self):
        with self.assertRaises(DiffParseError) as ctx:
            parse_diff(read("malformed/bad_hunk_counts.diff"))
        self.assertIn("truncated", str(ctx.exception))

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(DiffParseError) as ctx:
            parse_diff(read("malformed/path_traversal.diff"))
        self.assertIn("traversal", str(ctx.exception))

    def test_absolute_backslash_and_git_paths_rejected(self):
        bad_headers = [
            "--- a/etc/passwd\n+++ b//etc/passwd\n@@ -1 +1 @@\n-a\n+b\n",
            "--- a/C:/x.py\n+++ b/C:/x.py\n@@ -1 +1 @@\n-a\n+b\n",
            "--- a/app\\x.py\n+++ b/app\\x.py\n@@ -1 +1 @@\n-a\n+b\n",
            "--- a/.git/config\n+++ b/.git/config\n@@ -1 +1 @@\n-a\n+b\n",
            "--- a/app/x.py\n+++ b/app/x.py\n@@ -1 +1 @@\n-a\n+b\n--- a/x/../../y.py\n+++ b/x/../../y.py\n@@ -1 +1 @@\n-a\n+b\n",
        ]
        for text in bad_headers:
            with self.subTest(text=text[:30]):
                with self.assertRaises(DiffParseError):
                    parse_diff(text)

    def test_plain_text_is_not_a_diff(self):
        with self.assertRaises(DiffParseError) as ctx:
            parse_diff("hello world\nthis is not a diff\n")
        self.assertIn("no file headers", str(ctx.exception))

    def test_hunk_without_file_header_rejected(self):
        with self.assertRaises(DiffParseError):
            parse_diff("@@ -1 +1 @@\n-a\n+b\n")

    def test_too_many_files_and_hunks(self):
        one = read("buggy/off_by_one_pagination.diff")
        with self.assertRaises(DiffParseError) as ctx:
            parse_diff(one * 3, max_files=2)
        self.assertIn("more than 2 files", str(ctx.exception))
        with self.assertRaises(DiffParseError) as ctx:
            parse_diff(one * 3, max_hunks=2)
        self.assertIn("more than 2 hunks", str(ctx.exception))

    def test_empty_context_line_tolerated_and_no_newline_marker_ignored(self):
        text = (
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -1,3 +1,3 @@\n"
            " one\n"
            "\n"
            "-two\n"
            "\\ No newline at end of file\n"
            "+TWO\n"
        )
        parsed = parse_diff(text)
        f = parsed.files[0]
        self.assertEqual(f.added_text(), {3: "TWO"})
        self.assertEqual(len(f.hunks[0].lines), 4)


class InputValidationTests(unittest.TestCase):
    limits = dict(max_bytes=1024 * 1024, max_files=50, max_hunks=500)

    def test_empty_and_whitespace_rejected(self):
        for text in ("", "   \n\t"):
            with self.subTest(text=repr(text)):
                with self.assertRaises(InputValidationError) as ctx:
                    validate_diff_text(text, **self.limits)
                self.assertEqual(ctx.exception.code, "empty_diff")

    def test_oversize_rejected_with_413(self):
        big = read("clean/clean_change.diff") + ("#" * 2_000_000)
        with self.assertRaises(InputValidationError) as ctx:
            validate_diff_text(big, **self.limits)
        self.assertEqual(ctx.exception.status_code, 413)

    def test_nul_bytes_rejected(self):
        with self.assertRaises(InputValidationError) as ctx:
            validate_diff_text("--- a/x.py\x00\n", **self.limits)
        self.assertEqual(ctx.exception.code, "binary_content")

    def test_malformed_maps_to_code(self):
        with self.assertRaises(InputValidationError) as ctx:
            validate_diff_text(read("malformed/bad_hunk_counts.diff"), **self.limits)
        self.assertEqual(ctx.exception.code, "malformed_diff")
        self.assertIn("truncated", ctx.exception.message)

    def test_valid_diff_returns_hash_and_sanitized_name(self):
        result = validate_diff_text(
            read("clean/clean_change.diff"), display_name="../../evil\x07name.diff", **self.limits
        )
        self.assertEqual(len(result.sha256), 64)
        self.assertEqual(result.display_name, "evilname.diff")
        self.assertEqual(result.parsed.files[0].path, "app/utils/totals.py")

    def test_display_name_sanitization(self):
        self.assertEqual(sanitize_display_name(None), "pasted-diff")
        self.assertEqual(sanitize_display_name("C:\\dir\\x.patch"), "x.patch")
        self.assertEqual(sanitize_display_name("\x00\x01"), "uploaded-diff")
        self.assertLessEqual(len(sanitize_display_name("a" * 500)), 120)


if __name__ == "__main__":
    unittest.main()
