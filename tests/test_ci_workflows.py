"""Structural validation for the GitHub Actions build and release workflows.

These parse the workflow YAML rather than matching its text, so a formatting
change does not fail and a semantic regression does not pass unnoticed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"


def _workflow(name: str) -> dict[str, Any]:
    """Parse one workflow, undoing YAML 1.1's resolution of ``on:`` to ``True``."""

    payload = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return {("on" if key is True else key): value for key, value in payload.items()}


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    triggers = workflow["on"]
    assert isinstance(triggers, dict)
    return triggers


def _steps(workflow: dict[str, Any], job: str) -> list[dict[str, Any]]:
    return list(workflow["jobs"][job]["steps"])


@pytest.mark.parametrize("name", ["ci.yml", "build.yml", "release.yml"])
def test_every_workflow_is_parseable_and_declares_jobs(name: str) -> None:
    workflow = _workflow(name)

    assert workflow["jobs"]
    assert _triggers(workflow)


def test_build_matrix_expands_to_one_job_per_desktop_platform() -> None:
    strategy = _workflow("build.yml")["jobs"]["build"]["strategy"]
    matrix = strategy["matrix"]

    assert strategy["fail-fast"] is False
    # A matrix vector declared beside `include` collapses these entries into a
    # single job, silently dropping two of the three platform builds.
    assert set(matrix) == {"include"}
    assert [entry["platform"] for entry in matrix["include"]] == ["windows", "macos", "linux"]
    assert [entry["runner"] for entry in matrix["include"]] == [
        "windows-latest",
        "macos-latest",
        "ubuntu-latest",
    ]
    assert all(entry["python-version"] for entry in matrix["include"])


def test_building_desktop_artifacts_is_never_automatic() -> None:
    """Every job installs the desktop runtime and freezes a multi-GB package."""

    triggers = _triggers(_workflow("build.yml"))

    assert "workflow_dispatch" in triggers
    assert "pull_request" not in triggers
    assert triggers.get("push", {}).get("tags")
    assert "branches" not in triggers.get("push", {})


def test_build_runs_repository_gates_before_producing_an_artifact() -> None:
    commands = [step.get("run", "") for step in _steps(_workflow("build.yml"), "build")]
    joined = "\n".join(commands)

    assert 'python -m pip install --editable "packages/hanly-app[runtime]"' in joined
    assert "python -m pytest" in joined
    assert "python -m ruff check packages packaging tests tools" in joined
    assert "python -m mypy packages packaging tests tools" in joined

    gates = [index for index, command in enumerate(commands) if "python -m pytest" in command]
    builds = [index for index, command in enumerate(commands) if "build_package.py" in command]
    assert gates and builds and max(gates) < min(builds)


def test_linux_build_installs_only_the_missing_egl_loader_dependency() -> None:
    steps = _steps(_workflow("build.yml"), "build")
    linux_dependencies = [
        step for step in steps if step.get("name") == "Install Linux packaging dependencies"
    ]

    assert len(linux_dependencies) == 1
    step = linux_dependencies[0]
    assert step["if"] == "matrix.platform == 'linux'"
    commands = [line.strip() for line in step["run"].splitlines() if line.strip()]
    assert commands == [
        "sudo apt-get update",
        "sudo apt-get install --yes --no-install-recommends libegl1",
    ]
    build = next(item for item in steps if item.get("name") == "Build application package")
    assert steps.index(step) < steps.index(build)


def test_build_retains_only_the_release_archive() -> None:
    upload = next(
        step
        for step in _steps(_workflow("build.yml"), "build")
        if "upload-artifact" in step.get("uses", "")
    )
    paths = [line for line in upload["with"]["path"].splitlines() if line.strip()]

    assert upload["with"]["name"] == "hanly-desktop-${{ matrix.platform }}"
    assert upload["with"]["if-no-files-found"] == "error"
    # The onedir tree beside the archive is the same payload a second time.
    assert all(path.strip().startswith("dist/hanly-desktop-") for path in paths)
    # `if: always()` would upload after a failed build and report a second,
    # misleading "no files found" error on top of the real failure.
    assert "if" not in upload


def test_build_workflow_does_not_publish_releases() -> None:
    steps = _steps(_workflow("build.yml"), "build")
    rendered = "\n".join(str(step) for step in steps)

    assert "gh release create" not in rendered
    assert "softprops/action-gh-release" not in rendered
    assert _workflow("build.yml")["permissions"] == {"contents": "read"}


def test_release_is_manual_only_and_never_asks_for_the_application_run_id() -> None:
    """Resource archives are produced outside this repository, so publication
    stays a dispatch; the application build is resolved from the tag instead."""

    workflow = _workflow("release.yml")
    triggers = _triggers(workflow)
    inputs = triggers["workflow_dispatch"]["inputs"]

    assert set(triggers) == {"workflow_dispatch"}
    assert {"tag", "resource_run_id"} <= set(inputs)
    assert "run_id" not in inputs
    assert all(inputs[name]["required"] for name in ("tag", "resource_run_id"))
    assert workflow["permissions"]["contents"] == "write"
    assert workflow["permissions"]["actions"] == "read"

    downloads = [
        step["with"]["run-id"]
        for step in _steps(workflow, "release")
        if "download-artifact" in step.get("uses", "")
    ]
    assert downloads == [
        "${{ steps.build.outputs.run_id }}",
        "${{ inputs.resource_run_id }}",
    ]


def test_release_resolves_its_application_build_from_the_tag() -> None:
    resolve = next(
        step for step in _steps(_workflow("release.yml"), "release") if step.get("id") == "build"
    )

    assert "gh run list" in resolve["run"]
    assert "--workflow build.yml" in resolve["run"]
    assert '--branch "$RELEASE_TAG"' in resolve["run"]
    assert "--status success" in resolve["run"]


def test_both_workflows_refuse_a_tag_that_disagrees_with_the_product_version() -> None:
    build = _steps(_workflow("build.yml"), "build")
    release = _steps(_workflow("release.yml"), "release")

    tag_push_check = next(
        step for step in build if "release_version.py" in step.get("run", "")
    )
    assert tag_push_check["if"] == "startsWith(github.ref, 'refs/tags/')"
    assert "${{ github.ref_name }}" in tag_push_check["run"]

    dispatch_check = next(
        step for step in release if "release_version.py" in step.get("run", "")
    )
    assert "${{ inputs.tag }}" in dispatch_check["run"]

    # The check must precede anything that produces or publishes an artifact.
    build_names = [step.get("name", "") for step in build]
    release_names = [step.get("name", "") for step in release]
    assert build_names.index(tag_push_check["name"]) < build_names.index(
        "Build application package"
    )
    assert release_names.index(dispatch_check["name"]) < release_names.index(
        "Create GitHub release and attach artifacts"
    )


def test_the_release_title_is_derived_from_the_tag() -> None:
    publish = next(
        step
        for step in _steps(_workflow("release.yml"), "release")
        if "gh release create" in step.get("run", "")
    )

    assert '--title "Hanly Desktop $RELEASE_TAG"' in publish["run"]
    assert "--generate-notes" in publish["run"]
    assert publish["env"]["RELEASE_TAG"] == "${{ inputs.tag }}"


def test_release_consumes_the_artifact_names_the_build_publishes() -> None:
    upload = next(
        step
        for step in _steps(_workflow("build.yml"), "build")
        if "upload-artifact" in step.get("uses", "")
    )
    download = next(
        step
        for step in _steps(_workflow("release.yml"), "release")
        if "download-artifact" in step.get("uses", "")
    )

    assert upload["with"]["name"] == "hanly-desktop-${{ matrix.platform }}"
    assert download["with"]["pattern"] == "hanly-desktop-*"


def test_release_refuses_to_publish_under_a_tag_that_does_not_exist() -> None:
    publish = next(
        step
        for step in _steps(_workflow("release.yml"), "release")
        if "gh release create" in step.get("run", "")
    )

    assert "git/ref/tags/$RELEASE_TAG" in publish["run"]
    assert publish["run"].index("git/ref/tags") < publish["run"].index("gh release create")


def test_release_checksums_reference_published_asset_names() -> None:
    manifest = next(
        step for step in _steps(_workflow("release.yml"), "release") if step.get("id") == "manifest"
    )

    assert "SHA256SUMS" in manifest["run"]
    # Hashing the staging path would emit checksum lines a downloader cannot
    # verify against the assets it actually receives.
    assert 'basename "$asset"' in manifest["run"]
