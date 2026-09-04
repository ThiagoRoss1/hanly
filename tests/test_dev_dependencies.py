"""The test suite must run in the environment CI actually builds.

CI installs the root ``dev`` dependency group and the two packages without
extras, while a developer machine carries the whole desktop runtime. A test
that reaches a library present only locally passes here and fails there, so
every third-party module the suite touches is either declared in that group
or acquired through ``pytest.importorskip``.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
TEST_ROOTS = (ROOT / "tests", ROOT / "benchmarks" / "dev" / "tests")

#: Distributions whose importable name differs from the name pip installs.
_IMPORT_NAMES = {"pillow": "PIL", "pyyaml": "yaml"}

#: Reached through the repository root on pytest's ``pythonpath``, not pip.
_FIRST_PARTY = frozenset({"benchmarks", "hanly", "hanly_app", "tests", "tools"})

#: The ``dev = [...]`` block without requiring a TOML parser on Python 3.10.
_DEV_GROUP = re.compile(r"^dev\s*=\s*\[(.*?)^\]", re.DOTALL | re.MULTILINE)
_REQUIREMENT = re.compile(r'"([A-Za-z0-9._-]+)')


def _declared_modules() -> set[str]:
    """Import names the root dev dependency group makes available."""

    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = _DEV_GROUP.search(text)
    assert block is not None, "pyproject.toml declares no dev dependency group"

    requirements = _REQUIREMENT.findall(block.group(1))
    assert requirements, "the dev dependency group is empty"
    return {_IMPORT_NAMES.get(name.lower(), name) for name in requirements}


def _imported_modules(tree: ast.Module) -> set[str]:
    """Top-level module names an ``import`` statement reaches, at any depth."""

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _named_in_calls(tree: ast.Module, *functions: str) -> set[str]:
    """Top-level module names passed as a literal to one of ``functions``."""

    modules: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        called = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if isinstance(node.func, ast.Name):
            called = node.func.id
        argument = node.args[0]
        if called in functions and isinstance(argument, ast.Constant):
            if isinstance(argument.value, str):
                modules.add(argument.value.split(".")[0])
    return modules


def _test_modules() -> list[Path]:
    paths = [path for root in TEST_ROOTS for path in sorted(root.rglob("*.py"))]
    assert paths, "no test modules were found"
    return paths


def test_every_library_the_suite_reaches_is_declared_or_skippable() -> None:
    declared = _declared_modules()
    standard_library = set(sys.stdlib_module_names)

    for path in _test_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        guarded = _named_in_calls(tree, "importorskip")
        reached = _imported_modules(tree) | _named_in_calls(
            tree, "__import__", "import_module"
        )

        undeclared = reached - standard_library - _FIRST_PARTY - guarded - declared
        assert not undeclared, (
            f"{path.relative_to(ROOT)} reaches {sorted(undeclared)}, which CI does "
            "not install; add it to the root dev dependency group or acquire it "
            "with pytest.importorskip"
        )


def test_the_quality_matrix_installs_the_group_the_suite_relies_on() -> None:
    """The guarantee above is only worth as much as the workflow that honours it."""

    for name in ("ci.yml", "build.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "pip install --group dev" in text, name
