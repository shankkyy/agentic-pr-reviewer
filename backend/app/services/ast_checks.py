"""Focused AST checks over parseable diff snippets (stdlib only).

These checks are deliberately narrow. Each emits a RawDiagnostic only when the
offending node sits on an added line. Snippets are parsed with ast.parse, which
never executes code.
"""

from __future__ import annotations

import ast
import re

from app.services.diagnostics import RawDiagnostic
from app.services.python_context import Snippet

SQL_KEYWORDS = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM|VALUES)\b", re.IGNORECASE)
SQL_METHODS = {"execute", "executemany", "executescript", "raw", "mogrify"}
UNSAFE_LOADERS = {("pickle", "loads"), ("pickle", "load"), ("marshal", "loads"), ("marshal", "load")}


def _call_name(func: ast.expr) -> tuple[str | None, str | None]:
    """Return (owner, attr) for `owner.attr(...)` calls, or (None, name) for plain names."""
    if isinstance(func, ast.Attribute):
        owner = func.value.id if isinstance(func.value, ast.Name) else None
        return owner, func.attr
    if isinstance(func, ast.Name):
        return None, func.id
    return None, None


def _literal_text(node: ast.expr) -> str:
    """Concatenate the constant parts of a string-building expression."""
    parts: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            parts.append(sub.value)
    return " ".join(parts)


def _is_dynamic_sql(arg: ast.expr) -> bool:
    if isinstance(arg, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in arg.values)
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Mod, ast.Add)):
        return not _is_constant_string(arg)
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "format":
        return isinstance(arg.func.value, ast.Constant) and isinstance(arg.func.value.value, str)
    return False


def _is_constant_string(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_constant_string(node.left) and _is_constant_string(node.right)
    return False


def run_ast_checks(snippet: Snippet) -> list[RawDiagnostic]:
    if not snippet.parseable or not snippet.has_added_lines:
        return []
    try:
        tree = ast.parse(snippet.text)
    except (SyntaxError, ValueError):
        return []
    results: list[RawDiagnostic] = []

    def emit(node: ast.AST, rule_id: str, title: str, message: str, category: str, severity: str, confidence: float) -> None:
        snippet_line = getattr(node, "lineno", None)
        if snippet_line is None or snippet_line not in snippet.line_map:
            return
        new_line = snippet.line_map[snippet_line]
        if new_line not in snippet.added_new_lines:
            return
        results.append(
            RawDiagnostic(
                tool="ast",
                rule_id=rule_id,
                title=title,
                message=message,
                category=category,
                severity=severity,
                confidence=confidence,
                file_path=snippet.file_path,
                line=new_line,
                excerpt=snippet.excerpts.get(new_line, "")[:300],
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            owner, attr = _call_name(node.func)
            # SQL built from dynamic strings passed to a database execution method.
            if attr in SQL_METHODS and node.args and _is_dynamic_sql(node.args[0]):
                literal = _literal_text(node.args[0])
                if SQL_KEYWORDS.search(literal):
                    emit(
                        node,
                        "AST-SQL001",
                        "SQL statement built with string interpolation",
                        f"`{attr}()` receives a SQL string built dynamically. Use bound parameters.",
                        "security",
                        "high",
                        0.85,
                    )
            # Unsafe deserialization.
            if owner is not None and attr is not None and (owner, attr) in UNSAFE_LOADERS:
                emit(
                    node,
                    "AST-DESER001",
                    "Unsafe deserialization of untrusted data",
                    f"`{owner}.{attr}()` can execute arbitrary code when given untrusted input.",
                    "security",
                    "high",
                    0.8,
                )
            if owner == "yaml" and attr == "load" and not any(kw.arg == "Loader" for kw in node.keywords):
                emit(
                    node,
                    "AST-DESER002",
                    "yaml.load without a safe loader",
                    "`yaml.load()` without `Loader=SafeLoader` can construct arbitrary Python objects.",
                    "security",
                    "high",
                    0.8,
                )
            # subprocess with shell=True and a non-literal command.
            if owner == "subprocess" and any(
                kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                for kw in node.keywords
            ) and node.args and not isinstance(node.args[0], ast.Constant):
                emit(
                    node,
                    "AST-CMD001",
                    "Shell command built from non-constant input",
                    "`subprocess` is called with `shell=True` and a computed command string.",
                    "security",
                    "high",
                    0.75,
                )
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            emit(
                node,
                "AST-COR001",
                "Bare except clause",
                "A bare `except:` also catches KeyboardInterrupt and SystemExit and can hide failures.",
                "correctness",
                "low",
                0.9,
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
            for default in defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    emit(
                        default,
                        "AST-COR002",
                        "Mutable default argument",
                        f"Function `{node.name}` uses a mutable default value shared across calls.",
                        "correctness",
                        "medium",
                        0.9,
                    )
    return results
