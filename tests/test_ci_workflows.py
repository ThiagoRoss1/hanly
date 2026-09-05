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


def _redirected_names(command: str, sink: str) -> set[str]:
    """Return the names a shell command appends to ``$SINK``."""

    pattern = (
        rf"(?:printf|echo)\s+['\"](?P<name>[A-Za-z_][A-Za-z0-9_]*)=.*?>>\s*"
        rf"['\"]?\${re.escape(sink)}\b"
    )
    return {match.group("name") for match in re.finditer(pattern, _shell_code(command))}


def _all_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"] for step in _steps(workflow, job)]


def _gh_api_commands(command: str) -> list[str]:
    """Return each ``gh api`` invocation, with its line continuations joined.

    A pipe ends the invocation: what follows is a separate program, and its own
    ``jq`` is exactly how a paged query is meant to be filtered.
    """

    joined = re.sub(r"\\\s*\n\s*", " ", command)
    invocations = []
    for line in joined.splitlines():
        start = line.find("gh api")
        if start >= 0:
            invocations.append(line[start:].split("|", 1)[0].strip())
    return invocations


@pytest.mark.parametrize(
    "name", ["ci.yml", "build.yml", "release.yml"]
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


def test_linux_build_uses_the_cpu_only_ocr_runtime() -> None:
    steps = _steps(_workflow("build.yml"), "build")
    cpu_runtime = _step(
        _workflow("build.yml"), "build", name="Install CPU-only OCR runtime on Linux"
    )
    packages = _step(_workflow("build.yml"), "build", name="Install packages")

    assert cpu_runtime["if"] == "matrix.platform == 'linux'"
    assert cpu_runtime["run"] == (
        "python -m pip install torch torchvision "
        "--index-url https://download.pytorch.org/whl/cpu"
    )
    assert steps.index(cpu_runtime) < steps.index(packages)


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


def test_build_rejects_an_archive_too_large_for_github_releases() -> None:
    verify = _step(
        _workflow("build.yml"), "build", name="Verify the release archive exists"
    )
    code = _shell_code(verify["run"])

    assert "max_release_asset_bytes=2147483648" in code
    assert '"$archive_size" -lt "$max_release_asset_bytes"' in code


def test_build_workflow_does_not_publish_releases() -> None:
    steps = _steps(_workflow("build.yml"), "build")
    rendered = "\n".join(str(step) for step in steps)

    assert "gh release create" not in rendered
    assert "softprops/action-gh-release" not in rendered
    assert _workflow("build.yml")["permissions"] == {"contents": "read"}


def test_workflow_env_writes_do_not_shadow_job_environment() -> None:
    for workflow_name in ("ci.yml", "build.yml", "release.yml"):
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


@pytest.mark.parametrize(
    "name", ["release.yml", "build.yml"]
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


@pytest.mark.parametrize(
    "name", ["release.yml", "build.yml", "ci.yml"]
)
def test_no_gh_api_call_combines_slurp_with_its_own_jq(name: str) -> None:
    """``gh api`` refuses ``--slurp`` together with ``--jq`` or ``--template``
    and prints its usage instead, which a release already failed on. Paged
    output is filtered by piping into a real ``jq``."""

    for step in _all_steps(_workflow(name)):
        for command in _gh_api_commands(_shell_code(step.get("run", ""))):
            if "--slurp" in command:
                assert "--jq" not in command, (name, command)
                assert "-q " not in command and "--template" not in command, (name, command)


@pytest.mark.parametrize(
    "name", ["release.yml", "build.yml", "ci.yml"]
)
def test_every_parameterised_gh_api_query_states_its_method(name: str) -> None:
    """``gh api`` switches to POST as soon as a ``-f``/``-F`` field appears, so a
    list query that filters with fields has to say ``--method GET`` or it stops
    being a query at all."""

    for step in _all_steps(_workflow(name)):
        for command in _gh_api_commands(_shell_code(step.get("run", ""))):
            if re.search(r"(?<!-)-[fF]\s+\S+=", command):
                assert "--method GET" in command or "-X GET" in command, (name, command)


# --- The two-job release lane -------------------------------------------------
#
# KRDICT is built locally from the manually acquired official ZIP, so the
# workflow never fetches a source archive and never produces the resource. It
# stages a draft, waits for a human to attach the two local files and approve,
# and only then publishes.


def _release() -> dict[str, Any]:
    return _workflow("release.yml")


def _release_code(job: str) -> str:
    return "\n".join(_shell_code(step.get("run", "")) for step in _steps(_release(), job))


def test_the_release_lane_is_a_staged_draft_then_an_approved_publish() -> None:
    workflow = _release()
    stage = workflow["jobs"]["stage"]
    finalize = workflow["jobs"]["finalize"]

    assert set(workflow["jobs"]) == {"stage", "finalize"}
    assert finalize["needs"] == "stage"
    assert finalize["environment"] == "hanly-release"
    # One per-tag concurrency group prevents two runs from mutating the same
    # draft concurrently while one waits for approval.
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert "environment" not in stage
    assert workflow["permissions"] == {"actions": "read", "contents": "write"}


def test_staging_creates_the_draft_and_cannot_publish_it() -> None:
    """The draft exists before anyone has attached a dictionary to it, and no
    step in the staging half can make a release public."""

    code = _release_code("stage")

    assert "gh release create" in code
    assert "--draft" in code
    assert "--draft=false" not in code
    assert "SHA256SUMS" not in code
    for forbidden in ("gh release delete", "git tag", "git push"):
        assert forbidden not in code


def test_release_rejects_oversized_application_assets_before_mutating_the_draft() -> None:
    for job in ("stage", "finalize"):
        validation = _step(_release(), job, name="Validate application assets")
        code = _shell_code(validation["run"])

        assert "max_release_asset_bytes=2147483648" in code
        assert '"$archive_size" -lt "$max_release_asset_bytes"' in code

    stage_steps = _steps(_release(), "stage")
    validation = _step(_release(), "stage", name="Validate application assets")
    draft = _step(_release(), "stage", name="Create or repair the draft release")
    assert stage_steps.index(validation) < stage_steps.index(draft)


def test_staging_needs_no_dictionary_and_no_resource_producer() -> None:
    """A first release stages three application archives and nothing else, so a
    missing KRDICT pair cannot stop the draft from being created."""

    workflow = _release()
    code = _release_code("stage")
    rendered = str(workflow)

    assert "refusing to stage a draft without the three application archives" in code
    # No source archive, no producer run, and no way to ask for either.
    for obsolete in (
        "source_url",
        "resource_run_id",
        "reuse_previous_release_resource",
        "build-krdict-resource",
        "hanly-krdict-resource",
    ):
        assert obsolete not in rendered, obsolete
    assert set(_triggers(workflow)["workflow_dispatch"]["inputs"]) == {"tag", "validate_only"}
    assert not (WORKFLOWS / "build-krdict-resource.yml").exists()


def test_staging_carries_the_previous_resource_so_an_app_release_needs_no_upload() -> None:
    """A new application tag never implies the dictionary changed: the previous
    release's exact bytes are staged again, and the operator replaces them in
    the draft only when KRDICT actually moved."""

    carried = _step(_release(), "stage", step_id="carried")
    code = _shell_code(carried["run"])

    assert "gh release list" in code
    assert "--exclude-drafts" in code
    assert "--exclude-pre-releases" in code
    assert "--limit 1" in code
    assert "releases/latest" not in _release_code("stage") + _release_code("finalize")
    assert "gh release download" in code
    assert "hanly-resources.json" in code
    assert "resources.krdict.asset_name" in code
    # No previous release is a normal first release, not a failure.
    assert "carried=false" in code


def test_finalizing_reresolves_the_tag_and_accepts_only_its_own_draft() -> None:
    """Approval can sit for days, so nothing staged earlier is trusted."""

    steps = _steps(_release(), "finalize")
    names = [step.get("name") for step in steps]
    code = "\n".join(_shell_code(step.get("run", "")) for step in steps)

    assert "Re-resolve the tag and its application build" in names
    assert "release_build.py" in code
    assert "classify" in code
    assert 'action" == "reuse"' in code
    assert "no draft staged for" in code


def test_finalizing_takes_the_application_archives_from_the_exact_build() -> None:
    """The draft's own copies are not authoritative; the build's artifacts are."""

    download = next(
        step
        for step in _steps(_release(), "finalize")
        if "download-artifact" in step.get("uses", "")
    )

    assert download["with"]["run-id"] == "${{ steps.application.outputs.run_id }}"
    assert download["with"]["pattern"] == "hanly-desktop-*"
    assert download["with"]["merge-multiple"] is False


def test_finalizing_refuses_a_draft_without_exactly_one_resource_pair() -> None:
    resources = _step(_release(), "finalize", step_id="resources")
    code = _shell_code(resources["run"])

    assert "exactly one krdict-" in code
    assert "no hanly-resources.json" in code
    assert "unexpected asset" in code
    assert "gh release download" in code


def test_finalizing_validates_every_resource_field_before_writing_checksums() -> None:
    workflow = _release()
    steps = _steps(workflow, "finalize")
    validation = next(step for step in steps if "RemoteManifest" in step.get("run", ""))
    code = _shell_code(validation["run"])

    for requirement in (
        "manifest_version must be 1",
        "asset_name is not canonical",
        "checksum is not canonical",
        "schema_version must be 1",
        "expected_entry_count must be positive",
        "size must be positive",
        "artifact checksum does not match manifest",
        "artifact size does not match manifest",
        "candidate resource_version matches previous but checksum changed",
    ):
        assert requirement in code, requirement

    # The checksum manifest attests to nothing unless every payload asset has
    # already been validated, so it is written last, in this same step.
    assert code.index("RemoteManifest") < code.index("SHA256SUMS")
    publish = _step(workflow, "finalize", step_id="publish")
    assert steps.index(validation) < steps.index(publish)


def test_publication_is_the_last_act_and_only_over_exactly_six_assets() -> None:
    publish = _step(_release(), "finalize", step_id="publish")
    code = _shell_code(publish["run"])

    assert "gh release upload" in code
    assert "--clobber" in code
    for asset in (
        "hanly-desktop-windows.zip",
        "hanly-desktop-macos.tar.gz",
        "hanly-desktop-linux.tar.gz",
        "hanly-resources.json",
        "SHA256SUMS",
    ):
        assert asset in code, asset
    assert "RESOURCE_ASSET_NAME" in code
    assert "expected exactly six release assets" in code
    assert code.index("expected exactly six release assets") < code.index("--draft=false")
    assert code.count("--draft=false") == 1
    # A failed check leaves the draft; nothing here removes one.
    assert "gh release delete" not in code


def test_a_dry_run_validates_the_draft_and_writes_nothing() -> None:
    workflow = _release()
    steps = _steps(workflow, "finalize")
    publish = _step(workflow, "finalize", step_id="publish")
    dry_run = next(step for step in steps if step.get("name") == "Report a validated dry run")

    assert publish["if"] == "${{ inputs.validate_only != true }}"
    assert dry_run["if"] == "${{ inputs.validate_only == true }}"
    assert steps.index(dry_run) < steps.index(publish)
    # Only the publishing step writes to the release, so a dry run cannot.
    writers = [step for step in steps if "gh release upload" in step.get("run", "")]
    assert writers == [publish]


def test_an_already_published_tag_is_a_no_op_rather_than_a_second_release() -> None:
    workflow = _release()
    stage = workflow["jobs"]["stage"]

    assert stage["outputs"]["noop"] == "${{ steps.preflight.outputs.action == 'noop' }}"
    assert workflow["jobs"]["finalize"]["if"] == "needs.stage.outputs.noop != 'true'"


def test_the_release_lane_installs_only_the_packages_it_imports() -> None:
    """Both halves need hanly-app's manifest parser and nothing else: the GUI
    extras stay out of jobs that hold contents: write."""

    for job in ("stage", "finalize"):
        install = next(
            step for step in _steps(_release(), job) if "pip install" in step.get("run", "")
        )
        code = _shell_code(install["run"])

        assert "packages/hanly" in code and "packages/hanly-app" in code
        assert "[runtime]" not in code


def test_the_release_lane_never_authenticates_git_by_hand() -> None:
    """Both checkouts run with `persist-credentials: false`, so neither job holds
    a git credential. Reads of another commit go through the API."""

    workflow = _release()
    credential_in_url = re.compile(r"https://[^\s/]*\$[^\s/]*@")

    for job in ("stage", "finalize"):
        steps = _steps(workflow, job)
        checkout = next(step for step in steps if "checkout" in step.get("uses", ""))
        assert checkout["with"]["persist-credentials"] is False

        for step in steps:
            code = _shell_code(step.get("run", ""))
            assert "extraheader" not in code, (job, step.get("name"))
            assert not credential_in_url.search(code), (job, step.get("name"))
            assert not re.search(r"\bgit\s+(?:fetch|clone|pull|ls-remote)\b", code)


@pytest.mark.parametrize("job", ["stage", "finalize"])
def test_the_tagged_version_check_reads_the_tag_commit_through_the_api(job: str) -> None:
    tagged = _step(_release(), job, name="Verify tagged product version")
    code = _shell_code(tagged["run"])

    assert "contents/$path?ref=$APPLICATION_HEAD_SHA" in code
    assert "application/vnd.github.raw" in code
    assert tagged["env"]["APPLICATION_HEAD_SHA"] == "${{ steps.application.outputs.head_sha }}"


@pytest.mark.parametrize("job", ["stage", "finalize"])
def test_release_shells_do_not_interpolate_external_context(job: str) -> None:
    direct_context = re.compile(r"\$\{\{\s*(?:github|matrix|inputs)\b")

    for step in _steps(_release(), job):
        command = _shell_code(step.get("run", ""))
        assert not direct_context.search(command), (job, step.get("name"), command)


def test_a_previous_resource_is_carried_only_into_a_brand_new_draft() -> None:
    """An existing draft may already hold the pair the operator uploaded, and
    replacing it would silently swap out the dictionary they chose."""

    workflow = _release()
    carried = _step(workflow, "stage", step_id="carried")
    repair = _step(workflow, "stage", name="Create or repair the draft release")
    code = _shell_code(repair["run"])

    assert "steps.preflight.outputs.action == 'create'" in carried["if"]
    # The repair uploads the three archives unconditionally, and the carried
    # pair only on the branch that just created the draft.
    assert 'PREFLIGHT_ACTION" == "create" && "$CARRIED" == "true"' in code
    upload = code.split("upload=(", 1)[1].split("gh release upload", 1)[0]
    assert "hanly-resources.json" in upload.split('== "create"', 1)[1]
    assert "hanly-resources.json" not in upload.split('== "create"', 1)[0]


def test_finalizing_repeats_the_tagged_version_check_rather_than_trusting_stage() -> None:
    """Staging read the tag commit's metadata before the approval; the job that
    makes a version public reads it again."""

    for job in ("stage", "finalize"):
        step = _step(_release(), job, name="Verify tagged product version")
        code = _shell_code(step["run"])

        assert "tools/tagged_metadata.py" in code
        assert "tools/release_version.py" in code
        assert "--app-hanly-concrete-pin" in code
        assert step["env"]["APPLICATION_HEAD_SHA"] == "${{ steps.application.outputs.head_sha }}"


def test_a_dry_run_makes_the_staging_half_read_only() -> None:
    """`validate_only` writes nothing anywhere, so staging may not create a
    draft, upload to one, or even fetch the artifacts it would upload."""

    workflow = _release()
    steps = _steps(workflow, "stage")
    preflight = _step(workflow, "stage", step_id="preflight")

    mutating = [
        step
        for step in steps
        if "gh release create" in step.get("run", "")
        or "gh release upload" in step.get("run", "")
        or "download-artifact" in step.get("uses", "")
        or step.get("id") == "carried"
    ]
    assert mutating
    for step in mutating:
        assert "inputs.validate_only != true" in step["if"], step.get("name")

    # With nothing created, a dry run needs the draft to exist already.
    assert "validate_only needs an existing draft" in _shell_code(preflight["run"])


def test_a_dry_run_is_refused_where_it_could_not_be_honoured() -> None:
    """An automatic release has no operator asking for a dry run, so the flag is
    manual-only in both halves rather than silently ignored."""

    for job in ("stage", "finalize"):
        code = _release_code(job)

        assert "validate_only must be boolean" in code
        assert "validate_only is manual-only" in code


def test_the_published_checksums_are_proven_to_be_the_generated_ones() -> None:
    """A draft may carry a SHA256SUMS an earlier finalize left behind, so the
    asset-name check cannot tell a fresh one from a stale one. The bytes are
    compared before anything becomes public."""

    workflow = _release()
    resources = _step(workflow, "finalize", step_id="resources")
    publish = _step(workflow, "finalize", step_id="publish")
    allowed = _shell_code(resources["run"])
    code = _shell_code(publish["run"])

    # Tolerated on the draft, because a rerun has to be able to repair its own
    # partially finished work rather than refuse it.
    assert "SHA256SUMS" in allowed.split("allowed=(", 1)[1].split(")", 1)[0]

    assert "cmp --silent" in code
    assert "release-output/SHA256SUMS" in code
    assert "is not the one generated for these assets" in code
    assert code.index("cmp --silent") < code.index("--draft=false")
