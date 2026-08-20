"""Enforce the dependency direction between the engine and desktop app."""

import ast
from importlib.metadata import requires
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).parents[1]
ENGINE_SOURCE = ROOT / "packages" / "hanly" / "src" / "hanly"


def test_engine_source_does_not_import_hanly_app() -> None:
    violations: list[str] = []

    for source_file in ENGINE_SOURCE.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported_names = [node.module or ""]
            else:
                continue

            if any(name == "hanly_app" or name.startswith("hanly_app.") for name in imported_names):
                violations.append(str(source_file))

    assert violations == []


def test_distribution_dependency_direction() -> None:
    engine_dependencies = {
        canonicalize_name(Requirement(raw_requirement).name)
        for raw_requirement in requires("hanly") or []
    }
    app_dependencies = {
        canonicalize_name(Requirement(raw_requirement).name)
        for raw_requirement in requires("hanly-app") or []
    }

    assert canonicalize_name("hanly-app") not in engine_dependencies
    assert canonicalize_name("hanly") in app_dependencies
