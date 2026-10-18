"""Regenerates the deterministic diff fixtures in this directory.

Before/after file pairs are diffed with difflib so hunk header counts are exact.
Malformed, path-traversal, rename/delete, and binary fixtures are written by hand.
Run from the repository root:  python3 fixtures/build_fixtures.py
"""

from __future__ import annotations

import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PAIRS: dict[str, tuple[str, str, str, str]] = {
    # name: (directory, repo path, before, after)
    "clean/clean_change": (
        "clean",
        "app/utils/totals.py",
        "from __future__ import annotations\n\n\ndef total(items):\n    return sum(items)\n",
        (
            "from __future__ import annotations\n\n\n"
            "def total(items: list[float]) -> float:\n"
            '    """Return the sum of item prices, ignoring None values."""\n'
            "    return sum(item for item in items if item is not None)\n\n\n"
            "def average(items: list[float]) -> float:\n"
            "    values = [item for item in items if item is not None]\n"
            "    if not values:\n"
            '        raise ValueError("no values to average")\n'
            "    return sum(values) / len(values)\n"
        ),
    ),
    "buggy/off_by_one_pagination": (
        "buggy",
        "app/services/pagination.py",
        "def paginate(items, page, size):\n    start = page * size\n    end = start + size\n    return items[start:end]\n",
        "def paginate(items, page, size):\n    start = page * size\n    end = start + size + 1\n    return items[start:end]\n",
    ),
    "security/sql_injection": (
        "security",
        "app/repositories/users.py",
        (
            "import sqlite3\n\n\n"
            "def find_user(conn: sqlite3.Connection, username: str):\n"
            "    cur = conn.cursor()\n"
            '    cur.execute("SELECT id, email FROM users WHERE name = ?", (username,))\n'
            "    return cur.fetchone()\n"
        ),
        (
            "import sqlite3\n\n\n"
            "def find_user(conn: sqlite3.Connection, username: str):\n"
            "    cur = conn.cursor()\n"
            "    cur.execute(f\"SELECT id, email FROM users WHERE name = '{username}'\")\n"
            "    return cur.fetchone()\n"
        ),
    ),
    "security/unsafe_pickle": (
        "security",
        "app/auth/session.py",
        "import json\n\n\ndef load_session(raw: bytes) -> dict:\n    return json.loads(raw)\n",
        "import pickle\n\n\ndef load_session(raw: bytes) -> dict:\n    return pickle.loads(raw)\n",
    ),
}


def unified(path: str, before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    body = "".join(lines)
    return f"diff --git a/{path} b/{path}\n" + body


HAND_WRITTEN: dict[str, str] = {
    "malformed/bad_hunk_counts": (
        "diff --git a/app/x.py b/app/x.py\n"
        "--- a/app/x.py\n"
        "+++ b/app/x.py\n"
        "@@ -1,3 +1,4 @@\n"
        " import os\n"
        "-x = 1\n"
        "+x = 2\n"
    ),
    "malformed/path_traversal": (
        "--- a/../../etc/passwd\n"
        "+++ b/../../etc/passwd\n"
        "@@ -1 +1 @@\n"
        "-root\n"
        "+toor\n"
    ),
    "rename_delete/rename_delete_binary": (
        "diff --git a/old_utils.py b/utils.py\n"
        "similarity index 100%\n"
        "rename from old_utils.py\n"
        "rename to utils.py\n"
        "diff --git a/legacy/report.py b/legacy/report.py\n"
        "deleted file mode 100644\n"
        "index 3b18e51..0000000\n"
        "--- a/legacy/report.py\n"
        "+++ /dev/null\n"
        "@@ -1,3 +0,0 @@\n"
        "-def build():\n"
        "-    return 1\n"
        "-\n"
        "diff --git a/assets/logo.png b/assets/logo.png\n"
        "index 1111111..2222222 100644\n"
        "Binary files a/assets/logo.png and b/assets/logo.png differ\n"
    ),
}


# ---------------------------------------------------------------------------
# Labeled benchmark. Expected lines are computed from the `marker` text in the
# after-file, so labels cannot drift from the fixture contents.
# ---------------------------------------------------------------------------

BENCH_PAIRS: dict[str, tuple[str, str, str, str]] = {
    "benchmark/clean_parameterized_query": (
        "benchmark", "app/repositories/orders.py",
        'def get_order(conn, order_id):\n    cur = conn.cursor()\n    cur.execute("SELECT id, total FROM orders WHERE id = ?", (order_id,))\n    return cur.fetchone()\n',
        'def get_order(conn, order_id):\n    cur = conn.cursor()\n    cur.execute("SELECT id, total FROM orders WHERE id = ?", (order_id,))\n    return cur.fetchone()\n\n\ndef count_orders(conn):\n    cur = conn.cursor()\n    cur.execute("SELECT COUNT(*) FROM orders")\n    return cur.fetchone()[0]\n',
    ),
    "benchmark/clean_safe_yaml": (
        "benchmark", "app/config/loader.py",
        'import json\n\n\ndef load_config(raw: str) -> dict:\n    return json.loads(raw)\n',
        'import yaml\n\n\ndef load_config(raw: str) -> dict:\n    return yaml.safe_load(raw)\n',
    ),
    "benchmark/clean_none_handling": (
        "benchmark", "app/users/names.py",
        'def name_of(user):\n    return user["name"]\n',
        'def name_of(user: dict | None) -> str:\n    if user is None:\n        return ""\n    return str(user.get("name", ""))\n',
    ),
    "benchmark/clean_fstring_logging": (
        "benchmark", "app/util/greeting.py",
        'def greet(name):\n    return "hi " + name\n',
        'def greet(name: str) -> str:\n    return f"hi {name}"\n',
    ),
    "benchmark/range_skip": (
        "benchmark", "app/services/totals.py",
        "def sum_prices(prices):\n    total = 0\n    for i in range(len(prices)):\n        total += prices[i]\n    return total\n",
        "def sum_prices(prices):\n    total = 0\n    for i in range(len(prices) - 1):\n        total += prices[i]\n    return total\n",
    ),
    "benchmark/command_injection": (
        "benchmark", "app/tools/runner.py",
        'import subprocess\n\n\ndef run_ls(path: str) -> bytes:\n    return subprocess.run(["ls", path], capture_output=True).stdout\n',
        'import subprocess\n\n\ndef run_ls(path: str) -> bytes:\n    return subprocess.run(f"ls {path}", shell=True, capture_output=True).stdout\n',
    ),
    "benchmark/tls_verify_disabled": (
        "benchmark", "app/clients/http.py",
        'import requests\n\n\ndef fetch(url: str) -> str:\n    return requests.get(url, timeout=5).text\n',
        'import requests\n\n\ndef fetch(url: str) -> str:\n    return requests.get(url, timeout=5, verify=False).text\n',
    ),
}

# id -> (fixture path, list of expected issues as (file, marker, category)); clean cases have no issues.
BENCH_CASES: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    ("clean_change", "clean/clean_change", []),
    ("clean_parameterized_query", "benchmark/clean_parameterized_query", []),
    ("clean_safe_yaml", "benchmark/clean_safe_yaml", []),
    ("clean_none_handling", "benchmark/clean_none_handling", []),
    ("clean_fstring_logging", "benchmark/clean_fstring_logging", []),
    ("off_by_one_pagination", "buggy/off_by_one_pagination", [("app/services/pagination.py", "end = start + size + 1", "correctness")]),
    ("range_skip", "benchmark/range_skip", [("app/services/totals.py", "range(len(prices) - 1)", "correctness")]),
    ("sql_injection", "security/sql_injection", [("app/repositories/users.py", "cur.execute(f", "security")]),
    ("unsafe_pickle", "security/unsafe_pickle", [("app/auth/session.py", "pickle.loads(raw)", "security")]),
    ("command_injection", "benchmark/command_injection", [("app/tools/runner.py", "shell=True", "security")]),
    ("tls_verify_disabled", "benchmark/tls_verify_disabled", [("app/clients/http.py", "verify=False", "security")]),
]


def write_benchmark() -> Path:
    import json

    for name, (_, path, before, after) in BENCH_PAIRS.items():
        target = ROOT / f"{name}.diff"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(unified(path, before, after), encoding="utf-8")

    # Map each fixture name to its after-text so expected lines come from the file itself.
    after_by_path: dict[str, str] = {}
    for _, path, _before, after in list(PAIRS.values()) + list(BENCH_PAIRS.values()):
        after_by_path[path] = after

    cases = []
    for case_id, diff_rel, expected in BENCH_CASES:
        entries = []
        for file_path, marker, category in expected:
            after = after_by_path[file_path]
            matches = [i + 1 for i, line in enumerate(after.splitlines()) if marker in line]
            if len(matches) != 1:
                raise SystemExit(f"{case_id}: marker {marker!r} must match exactly one line, got {matches}")
            entries.append({"file": file_path, "line": matches[0], "category": category, "marker": marker})
        cases.append(
            {
                "id": case_id,
                "diff": f"fixtures/{diff_rel}.diff",
                "label": "clean" if not expected else "issue",
                "expected": entries,
            }
        )
    out = ROOT / "benchmark" / "benchmark.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "version": 1,
                "description": "Labeled diffs: clean changes and single-issue changes. Line numbers are new-file lines.",
                "cases": cases,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out


def main() -> None:
    written = [write_benchmark()]
    for name, (_, path, before, after) in PAIRS.items():
        target = ROOT / f"{name}.diff"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(unified(path, before, after), encoding="utf-8")
        written.append(target)
    for name, text in HAND_WRITTEN.items():
        target = ROOT / f"{name}.diff"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(target)
    # Demo: a multi-file review combining the buggy and security changes (labeled DEMO in the UI).
    demo_parts = [
        unified(PAIRS[k][1], PAIRS[k][2], PAIRS[k][3])
        for k in ("buggy/off_by_one_pagination", "security/sql_injection", "security/unsafe_pickle")
    ]
    demo = ROOT / "demo" / "demo_review.diff"
    demo.parent.mkdir(parents=True, exist_ok=True)
    demo.write_text("".join(demo_parts), encoding="utf-8")
    written.append(demo)
    for p in written:
        print(p.relative_to(ROOT.parent))


if __name__ == "__main__":
    main()
