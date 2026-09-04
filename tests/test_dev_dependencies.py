"""The test suite must run in the environment CI actually builds.

CI installs the root ``dev`` dependency group and the two packages without
extras, while a developer machine carries the whole desktop runtime. A test
that reaches a library present only locally passes here and fails there, so
every third-party module the suite touches is either declared in that group
or acquired through a ``pytest.importorskip`` that precedes it.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
TEST_ROOTS = (ROOT / "tests", ROOT / "benchmarks" / "dev" / "tests")

#: Distributions whose importable name differs from the name pip installs.
_IMPORT_NAMES = {"pillow": "PIL", "pyyaml": "yaml"}

#: Reached through the repository root on pytest's ``pythonpath``, not pip.
_FIRST_PARTY = frozenset({"benchmarks", "hanly", "hanly_app", "tests", "tools"})

#: Locates ``dev = [...]`` for the runtimes without ``tomllib``, currently 3.10.
_DEV_GROUP = re.compile(r"^dev\s*=\s*(\[.*?^\])", re.DOTALL | re.MULTILINE)

#: Top-level standard-library modules newer than the supported floor. This guard
#: runs on whichever interpreter is at hand, so a module that is stdlib there but
#: not on 3.10 would pass locally and fail the oldest CI lane -- which is how
#: ``tomllib`` earned its place here.
_NEWER_THAN_THE_SUPPORTED_FLOOR = frozenset({"tomllib"})


def _standard_library() -> set[str]:
    """Module names a static import may rely on across every supported runtime."""

    return set(sys.stdlib_module_names) - _NEWER_THAN_THE_SUPPORTED_FLOOR


def _dev_requirements() -> list[str]:
    """Read the root dev dependency group as data, not as matched text.

    A TOML array of strings is also a Python list literal, so every supported
    runtime parses the values structurally, including 3.10, which has no
    ``tomllib``. A real parser checks this one where it exists, in its own test.
    """

    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = _DEV_GROUP.search(text)
    assert block is not None, "pyproject.toml declares no dev dependency group"
    requirements = ast.literal_eval(block.group(1))

    assert requirements, "the dev dependency group is empty"
    return list(requirements)


def _declared_modules() -> set[str]:
    """Import names the root dev dependency group makes available."""

    names = (re.split(r"[<>=!~\[;\s]", line, maxsplit=1)[0] for line in _dev_requirements())
    return {_IMPORT_NAMES.get(name.lower(), name) for name in names if name}


#: Nodes that open a lexical scope. A function's own body runs on its own terms.
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _lexical_scopes(tree: ast.Module) -> list[list[ast.AST]]:
    """Return each lexical scope's own nodes, without those of nested scopes.

    A guard and the import it covers have to sit in one scope for the guard to
    run first: statements in a function body run when that function is called,
    which says nothing about any other function's body.
    """

    scopes: list[list[ast.AST]] = []
    pending: list[ast.AST] = [tree]
    while pending:
        own: list[ast.AST] = []
        children = list(ast.iter_child_nodes(pending.pop()))
        while children:
            node = children.pop()
            if isinstance(node, _SCOPE_NODES):
                pending.append(node)
                continue
            own.append(node)
            children.extend(ast.iter_child_nodes(node))
        scopes.append(own)
    return scopes


def _static_imports(nodes: list[ast.AST]) -> list[tuple[str, int]]:
    """Top-level module names an ``import`` statement in ``nodes`` reaches."""

    reached: list[tuple[str, int]] = []
    for node in nodes:
        if isinstance(node, ast.Import):
            reached += [(alias.name.split(".")[0], node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            reached.append((node.module.split(".")[0], node.lineno))
    return reached


def _literal_call_arguments(nodes: list[ast.AST], *functions: str) -> list[tuple[str, int]]:
    """Top-level module names passed as a literal to one of ``functions``."""

    named: list[tuple[str, int]] = []
    for node in nodes:
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if isinstance(node.func, ast.Name):
            called = node.func.id
        elif isinstance(node.func, ast.Attribute):
            called = node.func.attr
        else:
            continue
        argument = node.args[0]
        if called in functions and isinstance(argument, ast.Constant):
            if isinstance(argument.value, str):
                named.append((argument.value.split(".")[0], node.lineno))
    return named


def _undeclared_modules(source: str, declared: set[str]) -> set[str]:
    """Report third-party modules the source reaches without cover.

    ``importorskip`` covers only an acquisition that follows it in the same
    scope. A guard below the import runs too late to stop the failure it appears
    to prevent, and a guard in a neighbouring function never runs for it at all.
    """

    standard_library = _standard_library()

    undeclared = set()
    for nodes in _lexical_scopes(ast.parse(source)):
        guards = _literal_call_arguments(nodes, "importorskip")
        reached = _static_imports(nodes) + _literal_call_arguments(
            nodes, "__import__", "import_module"
        )

        for name, line in reached:
            if name in declared or name in _FIRST_PARTY or name in standard_library:
                continue
            if not any(guard == name and guarded_from < line for guard, guarded_from in guards):
                undeclared.add(name)
    return undeclared


def _test_modules() -> list[Path]:
    paths = [path for root in TEST_ROOTS for path in sorted(root.rglob("*.py"))]
    assert paths, "no test modules were found"
    return paths


def test_every_library_the_suite_reaches_is_declared_or_skippable() -> None:
    declared = _declared_modules()

    for path in _test_modules():
        undeclared = _undeclared_modules(path.read_text(encoding="utf-8"), declared)
        assert not undeclared, (
            f"{path.relative_to(ROOT)} reaches {sorted(undeclared)}, which CI does "
            "not install; add it to the root dev dependency group or acquire it "
            "with pytest.importorskip"
        )


def test_an_importorskip_below_an_import_does_not_excuse_it() -> None:
    """The import runs first and fails collection, so the guard never sees it."""

    assert _undeclared_modules("import polars\npytest.importorskip('polars')\n", set()) == {
        "polars"
    }
    assert _undeclared_modules("pytest.importorskip('polars')\nimport polars\n", set()) == set()


def test_an_importorskip_in_another_function_does_not_reach_across_scopes() -> None:
    """Guarding one function's acquisition says nothing about another's import,
    which runs whenever its own function is called."""

    neighbour = (
        "def guarded() -> None:\n"
        "    pytest.importorskip('polars')\n"
        "\n"
        "\n"
        "def unguarded() -> None:\n"
        "    import polars\n"
    )
    same_scope = (
        "def guarded() -> None:\n"
        "    pytest.importorskip('polars')\n"
        "    import polars\n"
    )

    assert _undeclared_modules(neighbour, set()) == {"polars"}
    assert _undeclared_modules(same_scope, set()) == set()


def test_a_declared_dependency_needs_no_guard_and_an_undeclared_one_does() -> None:
    assert _undeclared_modules("import polars\n", {"polars"}) == set()
    assert _undeclared_modules("from polars import DataFrame\n", set()) == {"polars"}
    assert _undeclared_modules("__import__('polars.io')\n", set()) == {"polars"}


def test_the_literal_parse_agrees_with_a_real_toml_parser() -> None:
    """``tomllib`` arrived in 3.11 and this repository still targets 3.10, so
    the group is read as a Python literal everywhere and checked here wherever a
    real parser exists -- acquired the way this guard tells everyone else to."""

    tomllib = pytest.importorskip("tomllib")
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert _dev_requirements() == tomllib.loads(text)["dependency-groups"]["dev"]


def test_the_guard_models_the_oldest_supported_runtime_not_this_one() -> None:
    """``tomllib`` is stdlib from 3.11 and this repository still targets 3.10, so
    a static import of it passes on a developer runtime and fails four CI lanes.
    When the floor moves, this fails and points at the set to trim."""

    engine = (ROOT / "packages" / "hanly" / "pyproject.toml").read_text(encoding="utf-8")

    assert 'requires-python = ">=3.10"' in engine
    assert "tomllib" not in _standard_library()
    assert _undeclared_modules("import tomllib\n", set()) == {"tomllib"}


def test_the_declared_group_is_read_as_data_and_covers_the_suites_libraries() -> None:
    declared = _declared_modules()

    assert {"pytest", "PIL", "yaml", "numpy", "zstandard"} <= declared
    # The renaming table has to survive, or a distribution silently stops
    # covering the module it installs.
    assert "pillow" not in declared and "pyyaml" not in declared


def test_the_quality_matrix_installs_the_group_the_suite_relies_on() -> None:
    """The guarantee above is only worth as much as the workflow that honours it."""

    for name in ("ci.yml", "build.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "pip install --group dev" in text, name
