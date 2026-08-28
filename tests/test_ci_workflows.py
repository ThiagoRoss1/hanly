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


@pytest.mark.parametrize(
    "name", ["ci.yml", "build.yml", "build-krdict-resource.yml", "release.yml"]
)
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


def test_krdict_producer_is_manual_read_only_and_verifies_an_https_source() -> None:
    workflow = _workflow("build-krdict-resource.yml")
    inputs = _triggers(workflow)["workflow_dispatch"]["inputs"]

    assert set(_triggers(workflow)) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert {"source_url", "source_sha256"} <= set(inputs)
    assert not {"source_run_id", "source_artifact", "source_zip_name"} & set(inputs)
    assert all(inputs[name]["required"] for name in inputs)

    steps = _steps(workflow, "build-resource")
    validation = next(step for step in steps if step.get("name") == "Validate producer inputs")
    validation_command = validation["run"]
    assert '[[ "$SOURCE_URL" == https://* ]]' in validation_command
    assert '[[ "$RESOURCE_VERSION" =~ ^[A-Za-z0-9._-]+$ ]]' in validation_command
    assert '[[ "$SOURCE_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]' in validation_command
    assert '[[ "$BUILD_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]' in validation_command
    assert '[[ "$SOURCE_SHA256" =~ ^[0-9a-f]{64}$ ]]' in validation_command
    download = next(
        step
        for step in steps
        if step.get("name") == "Download and verify approved official source"
    )
    command = download["run"]
    assert "curl --fail --location --proto '=https' --proto-redir '=https'" in command
    assert 'source_path="$RUNNER_TEMP/krdict-source.zip"' in command
    assert "sha256sum --check --status -" in command
    assert steps.index(validation) < steps.index(download)
    assert steps.index(download) < next(
        index for index, step in enumerate(steps) if "build_seed.py" in step.get("run", "")
    )


def test_krdict_producer_builds_validates_packages_and_uploads_only_review_artifacts() -> None:
    workflow = _workflow("build-krdict-resource.yml")
    steps = _steps(workflow, "build-resource")
    commands = [step.get("run", "") for step in steps]
    joined = "\n".join(commands)

    assert "tools/krdict/build_seed.py" in joined
    assert "tools/krdict/validate_seed.py" in joined
    assert "tools/krdict/package_resource.py" in joined
    assert joined.index("build_seed.py") < joined.index("validate_seed.py") < joined.index(
        "package_resource.py"
    )
    assert all("${{ inputs." not in command for command in commands)

    upload = next(step for step in steps if "upload-artifact" in step.get("uses", ""))
    assert upload["with"]["path"] == "producer-output/"
    assert upload["with"]["name"] == "hanly-krdict-resource"
    assert upload["with"]["if-no-files-found"] == "error"
    rendered = "\n".join(str(step) for step in steps)
    assert "krdict-source.zip" not in upload["with"]["path"]
    assert "$RUNNER_TEMP" not in upload["with"]["path"]
    assert "actions/download-artifact" not in rendered
    assert "gh release" not in rendered
    assert "action-gh-release" not in rendered


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
    assert set(inputs) == {"tag", "resource_run_id"}
    assert workflow["permissions"]["contents"] == "write"
    assert workflow["permissions"]["actions"] == "read"

    downloads = [
        step["with"]["run-id"]
        for step in _steps(workflow, "release")
        if "download-artifact" in step.get("uses", "")
    ]
    assert downloads == [
        "${{ steps.build.outputs.run_id }}",
        "${{ env.RESOURCE_RUN_ID }}",
    ]
    assert workflow["jobs"]["release"]["env"] == {
        "RELEASE_TAG": "${{ inputs.tag }}",
        "RESOURCE_RUN_ID": "${{ inputs.resource_run_id }}",
    }
    resource_download = _steps(workflow, "release")[
        next(
            index
            for index, step in enumerate(_steps(workflow, "release"))
            if step.get("name") == "Download resource artifacts"
        )
    ]
    assert resource_download["with"]["name"] == "hanly-krdict-resource"


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
    assert '[[ "$RELEASE_TAG" =~ ^v[0-9]+\\.[0-9]+\\.[0-9]+$ ]]' in dispatch_check["run"]
    assert _workflow("release.yml")["jobs"]["release"]["env"]["RELEASE_TAG"] == (
        "${{ inputs.tag }}"
    )
    assert '"${{ inputs.tag }}"' not in dispatch_check["run"]

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


def test_release_consumes_the_single_krdict_zstd_and_producer_manifest() -> None:
    manifest = next(
        step for step in _steps(_workflow("release.yml"), "release") if step.get("id") == "manifest"
    )

    assert "krdict-*.sqlite3.zst" in manifest["run"]
    assert "*.resource.json" in manifest["run"]
    assert "hanly-resources.json" in manifest["run"]
    assert "paddle_detection_model" not in manifest["run"]
    assert "paddle_recognition_model" not in manifest["run"]


def test_release_rejects_a_noncanonical_producer_manifest() -> None:
    manifest = next(
        step for step in _steps(_workflow("release.yml"), "release") if step.get("id") == "manifest"
    )
    command = manifest["run"]

    assert 'assert isinstance(payload, dict)' in command
    assert 'assert payload["manifest_version"] == 1' in command
    assert 'assert isinstance(resources, dict) and set(resources) == {"krdict"}' in command
    assert 'assert isinstance(resource, dict)' in command
    assert 'assert set(resource) == expected_fields' in command
    assert 'assert "url" not in resource' in command
    assert 'assert isinstance(resource["asset_name"], str)' in command
    assert (
        'assert resource["asset_name"] == f"krdict-{resource[\'version\']}.sqlite3.zst"'
        in command
    )
    assert 'assert isinstance(resource["checksum"], str)' in command
    assert 're.fullmatch(r"sha256:[0-9a-f]{64}", resource["checksum"])' in command
    assert 'assert isinstance(resource["kind"], str)' in command
    assert 'assert isinstance(resource["version"], str)' in command
