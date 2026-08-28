"""Enforce the dependency direction between the engine and desktop app."""

import ast
from importlib.metadata import requires
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).parents[1]
ENGINE_SOURCE = ROOT / "packages" / "hanly" / "src" / "hanly"


def test_engine_source_only_imports_distributable_packages() -> None:
    """``hanly`` ships independently, so it may not reach into its desktop
    client or into repository-only tooling that no wheel contains."""

    forbidden = ("hanly_app", "tools")
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

            if any(
                name == root or name.startswith(f"{root}.")
                for name in imported_names
                for root in forbidden
            ):
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
