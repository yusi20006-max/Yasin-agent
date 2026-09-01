"""
Regression: agent runtime source must not import forbidden Yasin-Core internals.

Allowed: yasin_core.sdk (and nested modules under that package).
Forbidden: bare yasin_core and any other yasin_core.* prefix.
Uses AST only (ignores strings/comments).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_RUNTIME_DIRS = (
    REPO_ROOT / "agent_platform",
    REPO_ROOT / "yasin_agent",
)

ALLOWED_PREFIXES = ("yasin_core.sdk",)


def _is_allowed(module: str) -> bool:
    if not module:
        return True
    for allowed in ALLOWED_PREFIXES:
        if module == allowed or module.startswith(allowed + "."):
            return True
    if module == "yasin_core" or module.startswith("yasin_core."):
        return False
    return True


def _iter_imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    as_part = f" as {alias.asname}" if alias.asname else ""
                    yield alias.name, node.lineno, f"import {alias.name}{as_part}"
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue
            if not node.module:
                continue
            names = ", ".join(
                a.name + (f" as {a.asname}" if a.asname else "") for a in node.names
            )
            yield node.module, node.lineno, f"from {node.module} import {names}"


def _scan_file(path: Path):
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    violations = []
    for module, lineno, stmt in _iter_imports(tree):
        if not _is_allowed(module):
            violations.append((str(path.relative_to(REPO_ROOT)), lineno, module, stmt))
    return violations


def _python_files():
    files = []
    for root in AGENT_RUNTIME_DIRS:
        if not root.is_dir():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            files.append(p)
    return files


def test_agent_runtime_has_no_forbidden_core_imports():
    all_violations = []
    for path in _python_files():
        all_violations.extend(_scan_file(path))
    assert all_violations == [], (
        "Forbidden Yasin-Core internal imports in Agent runtime source:\n"
        + "\n".join(f"  {f}:{ln}: {mod}  ({stmt})" for f, ln, mod, stmt in all_violations)
    )


def test_sdk_import_is_allowed_by_policy():
    assert _is_allowed("yasin_core.sdk")
    assert _is_allowed("yasin_core.sdk.client")
    assert not _is_allowed("yasin_core")
    assert not _is_allowed("yasin_core.context")
    assert not _is_allowed("yasin_core.plugins")
    assert not _is_allowed("yasin_core.agents.runtime")


def test_string_and_comment_do_not_count_as_imports():
    src = """
# import yasin_core.context
msg = "from yasin_core.plugins import YasinPlugin"
import yasin_core.sdk
"""
    tree = ast.parse(src)
    mods = [m for m, _, _ in _iter_imports(tree)]
    assert mods == ["yasin_core.sdk"]
