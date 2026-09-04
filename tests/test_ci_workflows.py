"""Structural validation for the GitHub Actions build and release workflows.

These parse the workflow YAML rather than matching its text, so a formatting
change does not fail and a semantic regression does not pass unnoticed.
"""

from __future__ import annotations

import re
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


def _step(
    workflow: dict[str, Any],
    job: str,
    *,
    step_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    matches = [
        step
        for step in _steps(workflow, job)
        if (step_id is None or step.get("id") == step_id)
        and (name is None or step.get("name") == name)
    ]
    assert len(matches) == 1, (step_id, name, matches)
    return matches[0]


def _assert_step_order(steps: list[dict[str, Any]], *step_ids: str) -> None:
    positions = [
        next(index for index, step in enumerate(steps) if step.get("id") == step_id)
        for step_id in step_ids
    ]
    assert positions == sorted(positions), (step_ids, positions)


def _uses_shell_variable(command: str, name: str) -> bool:
    """Recognize either ``$NAME`` or ``${NAME}`` in a shell command."""

    return bool(re.search(rf"\$\{{?{re.escape(name)}\}}?", command))


def _uses_quoted_shell_variable(command: str, name: str) -> bool:
    return bool(re.search(rf'"\$\{{?{re.escape(name)}\}}?"', command))


def _shell_code(command: str) -> str:
    """Drop shell comments before checking executable workflow behavior."""

    return "\n".join(
        line for line in command.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )


def _has_count_guard(command: str, count: int) -> bool:
    return bool(
        re.search(
            rf"(?:len\([^)]*\)\s*(?:==|!=)\s*{count}|"
            rf"\$\{{#\w+(?:\[@\])?\}}\s*(?:==|!=|-eq|-ne)\s*{count}|"
            rf"wc\s+-l[^\n]*\b{count}\b)",
            command,
        )
    )


def _assert_numeric_404_handling(command: str, status_variable: str) -> None:
    lower = command.lower()
    assert "curl" in command and "--write-out '%{http_code}'" in command
    assert all(marker in lower for marker in (f'case "${status_variable}" in', "404)", "*)"))
    assert "exit 1" in lower
    assert not re.search(r"\bgrep\b[^\n]*(?:404|status)", lower)


def _redirected_names(command: str, sink: str) -> set[str]:
    pattern = (
        rf"(?:printf|echo)\s+['\"](?P<name>[A-Za-z_][A-Za-z0-9_]*)=.*?>>\s*"
        rf"['\"]?\${re.escape(sink)}\b"
    )
    return {match.group("name") for match in re.finditer(pattern, _shell_code(command))}


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


def test_desktop_build_runs_only_manually_or_for_release_tags() -> None:
    """Every job installs the desktop runtime and freezes a multi-GB package, so
    a release tag and a deliberate dispatch are the only things worth that."""

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
    assert "python -m ruff check packages packaging tests tools benchmarks" in joined
    assert "python -m mypy packages packaging tests tools benchmarks" in joined

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
    assert isinstance(workflow.get("run-name"), str)
    assert "${{ inputs.resource_version }}" in workflow["run-name"]
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
    commands = [_shell_code(step.get("run", "")) for step in steps]
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
    assert upload["with"]["retention-days"] == 30
    rendered = "\n".join(str(step) for step in steps)
    assert "krdict-source.zip" not in upload["with"]["path"]
    assert "$RUNNER_TEMP" not in upload["with"]["path"]
    assert "actions/download-artifact" not in rendered
    assert "gh release" not in rendered
    assert "action-gh-release" not in rendered


def test_release_has_automatic_and_manual_recovery_triggers() -> None:
    workflow = _workflow("release.yml")
    triggers = _triggers(workflow)
    workflow_run = triggers["workflow_run"]
    dispatch = triggers["workflow_dispatch"]
    inputs = dispatch["inputs"]

    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    assert workflow_run["workflows"] == ["Build Desktop Artifacts"]
    assert workflow_run["types"] == ["completed"]
    assert set(inputs) == {
        "tag",
        "resource_run_id",
        "reuse_previous_release_resource",
    }
    assert inputs["tag"]["required"] is True
    assert inputs["tag"]["type"] == "string"
    assert inputs["resource_run_id"]["required"] is False
    assert inputs["resource_run_id"]["type"] == "string"
    reuse = inputs["reuse_previous_release_resource"]
    assert reuse["required"] is False
    assert reuse["type"] == "boolean"
    assert reuse.get("default") is False

    release_job = workflow["jobs"]["release"]
    assert workflow["permissions"] == {"actions": "read", "contents": "write"}
    condition = str(release_job.get("if", ""))
    required_condition = (
        "github.event_name",
        "github.event.workflow_run.event",
        "github.event.workflow_run.conclusion",
        "github.event.workflow_run.head_repository.full_name",
        "github.repository",
        "success",
    )
    assert all(fragment in condition for fragment in required_condition)
    assert "push" in condition and "workflow_dispatch" in condition

    release_env = str(release_job.get("env", {}))
    release_env += str([step.get("env", {}) for step in _steps(workflow, "release")])
    assert "reuse_previous_release_resource" in release_env

    concurrency = workflow["concurrency"]
    assert isinstance(concurrency, dict)
    group = str(concurrency["group"])
    assert group != "release-publish"
    assert "inputs.tag" in group
    assert "workflow_run.head_branch" in group
    assert concurrency["cancel-in-progress"] is False


def test_release_uses_step_outputs_for_resolved_state() -> None:
    workflow = _workflow("release.yml")
    steps = _steps(workflow, "release")
    application = _step(workflow, "release", step_id="application")
    preflight = _step(workflow, "release", step_id="preflight")
    resources = _step(workflow, "release", step_id="resources")

    assert {"run_id", "head_sha"} <= _redirected_names(application["run"], "GITHUB_OUTPUT")
    assert _step(workflow, "release", name="Download per-platform application artifacts")["with"][
        "run-id"
    ] == "${{ steps.application.outputs.run_id }}"
    tagged = next(step for step in steps if "release_version.py" in step.get("run", ""))
    assert "steps.application.outputs.head_sha" in str(tagged)

    assert "noop" in _redirected_names(preflight["run"], "GITHUB_OUTPUT")
    preflight_index = steps.index(preflight)
    for step in steps[preflight_index + 1 :]:
        if step.get("id") in {"resources", "assets", "manifest", "publish"}:
            assert "steps.preflight.outputs.noop" in str(step.get("if", ""))

    assert "resource_run_id" in _redirected_names(resources["run"], "GITHUB_OUTPUT")
    assert _step(workflow, "release", name="Download resource artifacts")["with"]["run-id"] == (
        "${{ steps.resources.outputs.resource_run_id }}"
    )
    override_keys = [
        key
        for key, value in (workflow["jobs"]["release"].get("env") or {}).items()
        if value == "${{ inputs.resource_run_id }}"
    ]
    assert len(override_keys) == 1
    assert override_keys[0].lower() != "resource_run_id"


def test_workflow_env_writes_do_not_shadow_job_environment() -> None:
    for workflow_name in ("ci.yml", "build.yml", "build-krdict-resource.yml", "release.yml"):
        workflow = _workflow(workflow_name)
        for job_name, job in workflow["jobs"].items():
            job_env = set((job.get("env") or {}).keys())
            written = set().union(
                *(
                    _redirected_names(step.get("run", ""), "GITHUB_ENV")
                    for step in _steps(workflow, job_name)
                )
            )
            assert not written.intersection(job_env), (workflow_name, job_name, written & job_env)


def test_release_lookup_distinguishes_confirmed_404_from_fatal_errors() -> None:
    workflow = _workflow("release.yml")
    collision = _step(workflow, "release", name="Check release collision")
    code = _shell_code(collision["run"])
    lower = code.lower()

    assert "releases/tags/$release_tag" in lower
    _assert_numeric_404_handling(code, "response_status")
    # Public duplicates are an automatic no-op only; manual, draft, and
    # prerelease collisions are fatal.
    assert "automatic" in lower and "manual" in lower
    assert "draft" in lower and "prerelease" in lower
    assert "exit 0" in lower or "no-op" in lower or "noop" in lower
    assert "exit 1" in code

    latest = _step(workflow, "release", step_id="resources")
    latest_code = _shell_code(latest["run"])
    assert "/releases/latest" in latest_code
    _assert_numeric_404_handling(latest_code, "latest_status")


def test_release_uses_the_exact_triggering_application_run_and_proves_the_tag() -> None:
    workflow = _workflow("release.yml")
    steps = _steps(workflow, "release")
    app_download = _step(workflow, "release", name="Download per-platform application artifacts")
    assert app_download["with"]["run-id"] == "${{ steps.application.outputs.run_id }}"

    setup = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/setup-python@")
    )
    assert str(setup["with"]["python-version"]) == "3.13"

    resolve = _step(workflow, "release", step_id="application")
    resolve_code = _shell_code(resolve["run"])
    assert all(marker in resolve_code for marker in ("RELEASE_TAG", "build.yml", "head_sha"))
    lookup = "gh run list --workflow build.yml"
    api_lookup = "actions/workflows/build.yml/runs"
    assert lookup in resolve_code or api_lookup in resolve_code
    if lookup in resolve_code:
        assert "--commit" in resolve_code
        assert "--json databaseId,headSha,event,conclusion,headBranch" in resolve_code
        assert "headSha == env.APPLICATION_HEAD_SHA" in resolve_code
    else:
        assert "head_sha == env.TAG_SHA" in resolve_code
        assert "head_branch == env.RELEASE_TAG" in resolve_code
    assert "git/ref/tags" in resolve_code or "refs/tags" in resolve_code
    assert re.search(r"\^v\[0-9\].*\\\.", resolve_code)
    assert all(
        re.search(pattern, resolve_code, re.S)
        for pattern in (
            r"while\s+\[\[.*(?:tag|object).*==\s*\"tag\"",
            r"\[\[.*(?:tag|object).*==\s*\"commit\"",
        )
    )
    assert "git/refs/tags" in resolve_code or "refs/tags?" in resolve_code
    assert "exactly one" in resolve_code.lower() or re.search(
        r"(?:len|count)\([^\n]+\).*1", resolve_code.lower()
    )
    assert re.search(r"run_path\s*=\s*\"\$\{run_path%@\*\}\"", resolve_code)
    assert all(marker in resolve_code for marker in (".github/workflows/build.yml", "success"))
    assert re.search(
        r"\[\[\s*\"\$WORKFLOW_RUN_HEAD_SHA\"\s*==\s*\"\$tag_sha\"", resolve_code
    )
    assert not re.search(r"--branch\s+['\"]?\$RELEASE_TAG", resolve_code)

    checkout = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    checkout_ref = str(checkout.get("with", {}).get("ref", ""))
    assert checkout_ref == "${{ github.event.repository.default_branch }}"
    assert checkout["with"]["persist-credentials"] is False
    assert steps.index(checkout) < steps.index(resolve)

    run_resolvers = [
        step
        for step in steps
        if any(
            marker in _shell_code(step.get("run", ""))
            for marker in (lookup, api_lookup)
        )
    ]
    assert [step.get("id") for step in run_resolvers] == ["application"]

    # The build.yml provenance of this exact run is proven once, by
    # verify_application_run against the API, and is not restated here.
    assert resolve_code.count(".github/workflows/build.yml") >= 1
    tagged = next(step for step in steps if "release_version.py" in step.get("run", ""))
    tagged_code = _shell_code(tagged["run"])
    assert ".github/workflows/build.yml" not in tagged_code
    assert all(
        marker in tagged_code
        for marker in (
            "tomllib",
            "packages/hanly-app/pyproject.toml",
            "packages/hanly/pyproject.toml",
            "tools/release_version.py",
        )
    )
    invocation = tagged_code.split("python tools/release_version.py", 1)[1]
    assert all(
        flag in invocation
        for flag in (
            "--tag",
            "--engine-version",
            "--app-version",
            "--app-hanly-pin",
            "--app-hanly-concrete-pin",
        )
    )
    assert "product_version" not in tagged_code.lower()
    assert "verify_tag" not in tagged_code.lower()
    assert not re.search(r"pip\s+install[^\n]+packages/(?:hanly|hanly-app)", tagged_code)
    assert not re.search(r"git\s+(?:checkout|switch)\s+[^\n]*\$", tagged_code)

    release_job = workflow["jobs"]["release"]
    assert "GH_TOKEN" not in release_job.get("env", {})
    for step in steps:
        if re.search(r"\bgh\s+(?:api|run|release)\b", _shell_code(step.get("run", ""))):
            assert "GH_TOKEN" in step.get("env", {}), step.get("name", step.get("id"))


def test_build_refuses_a_tag_that_disagrees_with_the_product_version() -> None:
    build = _steps(_workflow("build.yml"), "build")

    tag_push_check = next(
        step for step in build if "release_version.py" in step.get("run", "")
    )
    assert tag_push_check["if"] == "startsWith(github.ref, 'refs/tags/')"
    assert tag_push_check["env"]["RELEASE_TAG"] == "${{ github.ref_name }}"
    assert _uses_shell_variable(tag_push_check["run"], "RELEASE_TAG")
    assert "${{ github.ref_name }}" not in tag_push_check["run"]

    # The check must precede anything that produces or publishes an artifact.
    assert build.index(tag_push_check) < next(
        index for index, step in enumerate(build) if "build_package.py" in step.get("run", "")
    )
def test_release_consumes_the_artifact_names_the_build_publishes() -> None:
    upload = next(
        step
        for step in _steps(_workflow("build.yml"), "build")
        if "upload-artifact" in step.get("uses", "")
    )
    assert upload["with"]["name"] == "hanly-desktop-${{ matrix.platform }}"
    download = _step(
        _workflow("release.yml"),
        "release",
        name="Download per-platform application artifacts",
    )
    assert download["with"]["pattern"] == "hanly-desktop-*"

    code = _shell_code(_step(_workflow("release.yml"), "release", step_id="assets")["run"])
    assert all(
        archive in code
        for archive in (
            "hanly-desktop-windows.zip",
            "hanly-desktop-macos.tar.gz",
            "hanly-desktop-linux.tar.gz",
        )
    )
    assert _has_count_guard(code, 3)
    assert all(marker in code.lower() for marker in ("duplicate", "unexpected", "symlink"))


def test_release_selects_resources_by_provenance_and_fails_closed() -> None:
    workflow = _workflow("release.yml")
    steps = _steps(workflow, "release")
    resource = _step(workflow, "release", step_id="resources")
    code = _shell_code(resource["run"])
    lower = code.lower()
    download = _step(workflow, "release", name="Download resource artifacts")
    assert download["with"]["name"] == "hanly-krdict-resource"
    assert "build-krdict-resource.yml" in code
    assert all(marker in lower for marker in ("head_branch", "success", "completed", "artifacts"))
    assert "head_repository.full_name" in lower or "headrepository.full_name" in lower
    assert "actions/runs/$run_id" in lower
    rest_path = ".github/workflows/build-krdict-resource.yml@main"
    assert rest_path.rsplit("@", 1)[0] in code
    assert re.search(r"\$\{[A-Za-z_][A-Za-z0-9_]*%@\*\}", code) or re.search(
        r"\.path[^\n]*sub\(\"@\[\^@\]\*\";\s*\"\"\)", code
    )
    assert ".repository.full_name // empty" in code or ".repository.full_name" in code
    assert all(marker in lower for marker in ("/releases/latest", "published_at", "created_at"))
    assert not re.search(r"(?:previous|release)[^\n]{0,80}created_at", code, re.I)
    assert all(
        marker in lower
        for marker in ("previous", "candidate", "hanly-resources.json", "asset_name", "exit 1")
    )
    assert "cp " in lower or "copy" in lower
    assert all(
        marker in code
        for marker in (
            "verify_producer_run",
            'gh release download "$PREVIOUS_TAG"',
            '--pattern "$previous_asset_name"',
            "cp release-inputs/previous/hanly-resources.json",
        )
    )

    # The manual override and explicit previous-resource escape are local
    # branches; neither is allowed to fall through silently.
    assert re.search(
        r"resource_run_id.{0,240}reuse_previous_release_resource|"
        r"reuse_previous_release_resource.{0,240}resource_run_id",
        code,
        re.S | re.I,
    )
    assert all(
        marker in lower for marker in ("github_step_summary", "reuse_previous_release_resource")
    )
    assert "--notes" in lower or "notes_file" in lower
    assert "newer" in lower or "created_at" in lower
    assert re.search(
        r'python\s+-\s+"\$[A-Za-z_][A-Za-z0-9_]*created_at"\s+"\$[A-Za-z_][A-Za-z0-9_]*published_at"'
        r'.{0,700}parse\(sys\.argv\[1\]\)\s*>\s*parse\(sys\.argv\[2\]\)',
        code,
        re.S | re.I,
    )
    assert "first release" in lower or "bootstrap" in lower
    assert "gh run list" in lower or "actions/workflows" in lower
    assert "default_branch" in lower or "defaultbranch" in lower
    assert re.search(r"verify_producer_run\s+\"\$[A-Za-z_][A-Za-z0-9_]*\"", code)
    assert re.search(r"created_at.{0,900}verify_producer_run", code, re.S)
    assert "exit 1" in code
    _assert_step_order(steps, "preflight", "resources", "manifest", "publish")


def test_release_uses_draft_first_exact_six_asset_publication() -> None:
    workflow = _workflow("release.yml")
    steps = _steps(workflow, "release")
    publish = _step(workflow, "release", step_id="publish")
    publish_code = _shell_code(publish["run"])

    assert all(
        marker in publish_code
        for marker in (
            "--draft",
            "--verify-tag",
            "gh release create",
            "gh api",
            "assets",
            "--draft=false",
        )
    )
    tag_recheck = "git/ref/tags/$RELEASE_TAG"
    assert tag_recheck in publish_code
    assert publish_code.index(tag_recheck) < publish_code.index("gh release create")
    assert re.search(
        r'\[\[\s*"\$[^"\n]*tag[^"\n]*"\s*==\s*"\$APPLICATION_HEAD_SHA"',
        publish_code,
        re.I,
    )
    asset_api = publish_code.index(".assets[].name")
    assert publish_code.index("gh release create") < asset_api
    assert asset_api < publish_code.index("gh release edit")
    assert _has_count_guard(publish_code, 6)
    assert all(
        marker in publish_code
        for marker in ("actual_assets", ".assets[].name", "sorted_expected")
    )
    assert all(
        name in publish_code
        for name in (
            "hanly-desktop-windows.zip",
            "hanly-desktop-macos.tar.gz",
            "hanly-desktop-linux.tar.gz",
            "hanly-resources.json",
            "SHA256SUMS",
        )
    )
    assert all(
        marker in publish_code
        for marker in (
            "krdict-*.sqlite3.zst",
            '--title "Hanly Desktop $RELEASE_TAG"',
            "--generate-notes",
        )
    )
    assert _uses_shell_variable(publish_code, "RELEASE_TAG")
    assert "${{ inputs.tag }}" not in publish_code
    for step in steps:
        code = _shell_code(step.get("run", ""))
        assert not re.search(r"\bgit\s+(?:tag|push|update-ref)\b", code)
        assert not any(
            tool in code
            for tool in (
                "tools/krdict/build_seed.py",
                "tools/krdict/validate_seed.py",
                "tools/krdict/package_resource.py",
            )
        )
    _assert_step_order(steps, "assets", "manifest", "publish")


@pytest.mark.parametrize(
    "name, job",
    [
        ("release.yml", "release"),
        ("build-krdict-resource.yml", "build-resource"),
    ],
)
def test_release_and_producer_shells_do_not_interpolate_external_context(
    name: str, job: str
) -> None:
    workflow = _workflow(name)
    direct_context = re.compile(r"\$\{\{\s*(?:github|matrix|inputs)\b")

    for step in _steps(workflow, job):
        command = _shell_code(step.get("run", ""))
        assert not direct_context.search(command), (name, step.get("name"), command)


def test_build_context_values_are_env_backed_in_shell_commands() -> None:
    steps = _steps(_workflow("build.yml"), "build")
    version_check = next(step for step in steps if "release_version.py" in step.get("run", ""))
    assert version_check.get("env", {}).get("RELEASE_TAG") == "${{ github.ref_name }}"
    assert _uses_quoted_shell_variable(version_check["run"], "RELEASE_TAG")
    # The build job runs one step list on three platforms. GitHub's default
    # Windows shell is pwsh, where ``$RELEASE_TAG`` is not a variable at all and
    # expands to nothing, which would hand the check an empty tag.
    assert version_check.get("shell") == "bash"
    direct_github = re.compile(r"\$\{\{\s*(?:github|inputs)\b")
    for step in steps:
        assert not direct_github.search(_shell_code(step.get("run", ""))), step


def test_release_manifest_validation_is_executable_and_checks_staged_bytes() -> None:
    workflow = _workflow("release.yml")
    steps = _steps(workflow, "release")
    manifest_code = _shell_code(_step(workflow, "release", step_id="manifest")["run"])
    resource_code = _shell_code(_step(workflow, "release", step_id="resources")["run"])
    require_lines = "\n".join(
        line for line in manifest_code.splitlines() if re.search(r"\brequire\(", line)
    )

    assert re.search(r"def require\(condition:\s*bool", manifest_code)
    assert re.search(r"raise (?:ValueError|RuntimeError)", manifest_code)
    for guard in (
        "isinstance(payload, dict)",
        'payload["manifest_version"] == 1',
        'set(resources) == {"krdict"}',
        '"url" not in resource',
    ):
        assert guard in require_lines
    assert re.search(
        r'require\([^\n]*resource\["asset_name"\]\s*==\s*f"krdict-\{[^\n]+\}\.sqlite3\.zst"',
        require_lines,
    )
    assert re.search(
        r'require\([^\n]*re\.fullmatch\(r"sha256:\[0-9a-f\]\{64\}"',
        require_lines,
    )

    staged_manifest = 'cp "$producer_manifest" release-output/hanly-resources.json'
    staged_validation = 'python - "$resource_asset_name" release-output/hanly-resources.json'
    assert staged_manifest in manifest_code
    assert staged_validation in manifest_code
    assert manifest_code.index(staged_manifest) < manifest_code.index(staged_validation)
    assert "hashlib.sha256(artifact.read_bytes())" in manifest_code
    assert "artifact.stat().st_size" in manifest_code
    compare_code = resource_code + "\n" + manifest_code
    assert re.search(r"if\s+\w*version\s*==\s*\w*version", compare_code)
    assert re.search(
        r"require\([^\n]*(?:resource|candidate)[^\n]*checksum[^\n]*(?:previous|prior)",
        compare_code,
        re.I,
    )
    assert "checksum changed" in compare_code.lower()
    _assert_step_order(steps, "assets", "manifest", "publish")


@pytest.mark.parametrize(
    "name", ["release.yml", "build.yml", "build-krdict-resource.yml"]
)
def test_release_lane_actions_are_pinned_to_immutable_commits(name: str) -> None:
    """A floating major tag is mutable and its owner can move it. These three
    workflows build and publish what users download, so each action they run is
    pinned to a commit, with the release it belongs to named beside it."""

    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    references = re.findall(r"uses:\s*(\S+)(.*)", text)

    assert references
    for reference, trailer in references:
        _action, _, revision = reference.partition("@")
        assert re.fullmatch(r"[0-9a-f]{40}", revision), (name, reference)
        assert re.search(r"#\s*v\d+\.\d+\.\d+", trailer), (name, reference)


def test_the_release_lane_installs_only_the_packages_it_imports() -> None:
    """The publisher needs hanly-app's manifest parser and nothing else: hanly
    declares no dependencies, hanly-app base adds only zstandard, and the GUI
    extras stay out of a job that holds contents: write."""

    install = next(
        step
        for step in _steps(_workflow("release.yml"), "release")
        if "pip install" in step.get("run", "")
    )
    code = _shell_code(install["run"])

    assert "packages/hanly" in code and "packages/hanly-app" in code
    assert "[runtime]" not in code
    assert "pip install --upgrade pip" not in code


def test_every_push_is_checked_on_windows_without_renaming_the_linux_gates() -> None:
    """A POSIX-only assumption in a test is invisible on a Linux-only matrix
    until a tag build runs it. The Linux job keeps its name because required
    status checks are pinned to it, so Windows arrives as its own job."""

    workflow = _workflow("ci.yml")
    quality = workflow["jobs"]["quality"]
    windows = workflow["jobs"]["windows-tests"]

    assert quality["name"] == "quality (py${{ matrix.python-version }})"
    assert quality["runs-on"] == "ubuntu-latest"
    assert windows["runs-on"] == "windows-latest"
    assert "push" in _triggers(workflow)

    commands = "\n".join(step.get("run", "") for step in _steps(workflow, "windows-tests"))
    assert "python -m pip install --group dev" in commands
    assert "python -m pip install --editable packages/hanly-app" in commands
    assert "python -m pytest" in commands


def test_the_release_lane_never_authenticates_git_by_hand() -> None:
    """The checkout runs with `persist-credentials: false`, so this job holds no
    git credential at all. A hand-rolled one is either a header GitHub's git
    endpoint rejects -- a bearer `http.extraheader` already failed a release
    this way -- or a token written somewhere it can be read back. Reads of
    another commit go through `gh`, which already has the token."""

    workflow = _workflow("release.yml")
    steps = _steps(workflow, "release")
    checkout = next(step for step in steps if "checkout" in step.get("uses", ""))
    credential_in_url = re.compile(r"https://[^\s/]*\$[^\s/]*@")

    assert checkout["with"]["persist-credentials"] is False

    for step in steps:
        code = _shell_code(step.get("run", ""))
        assert "extraheader" not in code, step.get("name")
        assert not credential_in_url.search(code), step.get("name")
        assert not re.search(r"\bgit\s+(?:fetch|clone|pull|ls-remote)\b", code), step.get("name")


def test_the_tagged_version_check_reads_the_tag_commit_through_the_api() -> None:
    """The tag commit is untrusted content being read by the job that publishes,
    so its two files arrive as data rather than as a tree checked out beside the
    default-branch tooling that runs here."""

    tagged = next(
        step
        for step in _steps(_workflow("release.yml"), "release")
        if "release_version.py" in step.get("run", "")
    )
    code = _shell_code(tagged["run"])

    assert "contents/$path?ref=$APPLICATION_HEAD_SHA" in code
    assert "application/vnd.github.raw" in code
    assert tagged["env"]["APPLICATION_HEAD_SHA"] == "${{ steps.application.outputs.head_sha }}"
