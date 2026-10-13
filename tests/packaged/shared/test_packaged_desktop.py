"""Exercise the real frozen executable without repo, venv, or model-cache fallback.

Missing bundles skip ordinarily; ``HANLY_REQUIRE_PACKAGED=1`` makes absence fail.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

import psutil
import pytest
from hanly_app.paths import default_app_config_path
from hanly_app.updates.build_identity import BuildStamp, InstalledReceipt, receipt_store
from hanly_app.updates.handoff import LAUNCH_EXEC, NativeTransaction, write_descriptor
from hanly_app.updates.journal import (
    acknowledgement_path,
    new_challenge,
    write_challenge,
)

from tests.hanly_fixtures import FIXTURE_ASSETS, REPO_ROOT
from tests.hanly_fixtures.capabilities import REQUIRE_PACKAGED, require_display, unavailable
from tools.build_package import PackageLayout, host_platform
from tools.build_smoke_krdict import build_smoke_krdict
from tools.release_version import product_version
from tools.smoke_packaged_runtime import (
    EXPECTED_SOURCE_VARIABLE,
    UI_TIMEOUT_SECONDS,
    _executable_in,
    _ProfileContext,
    copy_packaged_application,
    inspect_bundle,
    run_packaged_native_application,
    run_packaged_self_check,
    verify_frozen_identity,
    verify_source_identity,
)
from tools.update_artifacts import host_architecture

#: Points the gate at a bundle outside ``dist/``, such as an extracted release.
BUNDLE_VARIABLE = "HANLY_PACKAGED_APP"

#: The Korean fixture the frozen OCR stack must actually read.
FIXTURE_IMAGE = FIXTURE_ASSETS / "korean_reading_roi.png"

#: The same bound the harness uses, rather than a second, smaller number: a
#: cold or memory-pressured machine can take minutes to start Chromium, and a
#: slow start is not a broken window.
_WINDOW_TIMEOUT_SECONDS = UI_TIMEOUT_SECONDS
_NATIVE_SELF_CHECK_MODES = ("inventory", "ocr", "worker", "ui")


def _bundle() -> Path:
    configured = os.environ.get(BUNDLE_VARIABLE)
    if configured:
        return Path(configured).expanduser().resolve()
    return PackageLayout.for_platform(REPO_ROOT, host_platform()).application_directory


def _require_bundle() -> Path:
    bundle = _bundle()
    if not bundle.is_dir():
        unavailable(
            f"no frozen bundle at {bundle}; build one with tools/build_package.py "
            f"or set {BUNDLE_VARIABLE}",
            required_by=REQUIRE_PACKAGED,
        )
    return bundle


def _service_root(application: Path) -> Path:
    """Locate the service resources in an installed product."""

    if application.suffix == ".app":
        return application / "Contents" / "Resources" / "hanly-service"
    return application / "resources" / "hanly-service"


def test_the_frozen_bundle_carries_every_runtime_dependency() -> None:
    inventory = inspect_bundle(_require_bundle())

    assert inventory.ok, f"missing from the bundle: {', '.join(inventory.missing)}"


def test_the_frozen_bundle_was_built_from_the_expected_commit() -> None:
    """A stale bundle of the same version passes every other check it ever passed.

    The expected commit is named by whoever runs the gate -- CI passes the
    commit it built -- rather than taken from the checkout running the tests,
    which need not be the source of the artifact under test.
    """

    bundle = _require_bundle()
    expected = os.environ.get(EXPECTED_SOURCE_VARIABLE, "").strip()
    if not expected:
        unavailable(
            f"set {EXPECTED_SOURCE_VARIABLE} to the commit this bundle must be built from",
            required_by=REQUIRE_PACKAGED,
        )

    identity = verify_source_identity(
        bundle,
        expected_commit=expected,
        expected_version=product_version(),
        expected_platform=host_platform(),
        expected_architecture=host_architecture(),
    )

    assert identity["ok"], identity["problems"]


def _predates_the_window_check(report: Mapping[str, object]) -> bool:
    """Whether an old artifact rejected the native self-check arguments."""

    stderr = report.get("stderr")
    return report.get("exit_code") == 2 and isinstance(stderr, str) and (
        "invalid Hanly launch argument" in stderr
    )


def _executable() -> Path:
    """Find the program, wherever this platform's build keeps it."""

    bundle = _require_bundle()
    try:
        return _executable_in(bundle)
    except FileNotFoundError:
        unavailable(f"no Hanly executable in {bundle}", required_by=REQUIRE_PACKAGED)


def _failures(report: Mapping[str, object]) -> tuple[list[Mapping[str, object]], str]:
    stages = report.get("stages")
    recorded = [stage for stage in stages if isinstance(stage, Mapping)] if isinstance(
        stages, list
    ) else []
    failed = "; ".join(
        f"{stage.get('name')}: {stage.get('detail')}"
        for stage in recorded
        if not stage.get("ok")
    )
    return recorded, failed


def test_the_frozen_ocr_self_check_runs_on_an_isolated_profile(tmp_path: Path) -> None:
    """Inventory is not evidence: the executable has to construct providers."""

    executable = _executable()
    dictionary = build_smoke_krdict(tmp_path / "seed" / "krdict.sqlite3")
    runtime_config = tmp_path / "runtime.json"
    runtime_config.write_text(
        json.dumps(
            {
                "resources": {"krdict": {"path": str(dictionary), "kind": "krdict"}},
                "ocr_backend": "easyocr",
            }
        ),
        encoding="utf-8",
    )

    # The dictionary is licensed and is in neither the bundle nor the
    # repository, so a run given none provisions itself over the network. This
    # gate refuses every other developer fallback; that one is no different.
    report = run_packaged_self_check(
        executable,
        mode="ocr",
        runtime_config=runtime_config,
        image=FIXTURE_IMAGE,
        profile=tmp_path,
        krdict=dictionary,
    )

    recorded, failures = _failures(report)

    assert report.get("ok") is True, failures or str(report)
    assert report.get("exit_code") == 0
    assert report.get("frozen") is True
    assert {stage.get("name") for stage in recorded} >= {
        "inventory",
        "runtime configuration",
        "runtime",
        "lookup worker",
        "morphology",
        "dictionary",
        "ocr",
        "worker close",
    }

    # A stale bundle can pass functional checks; require its build identity
    # to match the source tree under test.
    identity = verify_frozen_identity(report, product_version())
    assert identity["ok"], identity["problems"]


def test_the_native_window_waits_for_react_and_answers_its_state_bridge(
    tmp_path: Path,
) -> None:
    """The product is ready only after the actual React page answers its bridge."""

    # A removed mode must fail here rather than quietly become a stale bundle.
    assert "ui" in _NATIVE_SELF_CHECK_MODES
    require_display(required_by=REQUIRE_PACKAGED)

    report = run_packaged_self_check(
        _executable(),
        mode="ui",
        profile=tmp_path,
        timeout=_WINDOW_TIMEOUT_SECONDS,
    )
    if _predates_the_window_check(report):
        unavailable(
            f"the bundle at {_bundle()} was built before --self-check ui; "
            "rebuild it with tools/build_package.py",
            required_by=REQUIRE_PACKAGED,
        )

    assert report.get("ok") is True, str(report)
    assert report.get("mode") == "ui"
    assert report.get("frontend_ready") is True
    assert report.get("service") is True
    assert isinstance(report.get("state"), Mapping)
    identity = verify_frozen_identity(report, product_version())
    assert identity["ok"], identity["problems"]
    assert not report.get("exit_timeout"), (
        "the native window answered its page, but the product did not exit cleanly"
    )
    assert report.get("exit_code") == 0


def test_the_packaged_native_root_acknowledges_only_after_its_real_ui_is_ready(
    tmp_path: Path,
) -> None:
    """A normal update launch proves the root and React page before commit."""

    require_display(required_by=REQUIRE_PACKAGED)
    source_bundle = _require_bundle()
    install_root = tmp_path / "owned-install" / source_bundle.name
    install_root.parent.mkdir(parents=True)
    copy_packaged_application(source_bundle, install_root)
    executable = _executable_in(install_root)
    service_root = _service_root(install_root)
    stamp_path = service_root / "_internal" / "hanly_app" / "assets" / "hanly-build.json"
    stamp = BuildStamp.from_json(stamp_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(stamp_path.read_bytes()).hexdigest()
    dictionary = build_smoke_krdict(tmp_path / "seed" / "krdict.sqlite3")
    runtime_config = tmp_path / "runtime.json"
    runtime_config.write_text(
        json.dumps(
            {
                "resources": {"krdict": {"path": str(dictionary), "kind": "krdict"}},
                "ocr_backend": "easyocr",
            }
        ),
        encoding="utf-8",
    )

    with _ProfileContext(tmp_path / "profile", krdict=dictionary) as (
        environment,
        working_directory,
    ):
        store = receipt_store(install_root, environment)
        store.stage_receipt(
            InstalledReceipt(
                identity=stamp.identity,
                manifest_sha256=digest,
                release_tag=stamp.release_tag,
                source_commit=stamp.source_commit,
                install_root=str(install_root),
            )
        )
        challenge = new_challenge(
            f"native-ui-{uuid4().hex[:16]}", stamp.identity, digest, install_root
        )
        challenge_path = write_challenge(
            store.directory / f"challenge-{uuid4().hex}.json", challenge
        )
        report = run_packaged_native_application(
            executable,
            [
                "--update-ready-v2",
                str(challenge_path),
                "--runtime-config",
                str(runtime_config),
                "--app-config",
                str(default_app_config_path(environment)),
            ],
            environment=environment,
            working_directory=working_directory,
            acknowledgement=acknowledgement_path(challenge_path),
        )

    assert report["acknowledged"] is True, report
    assert report["ack"] == challenge.expected()
    assert report["exit_code"] == 0, report
    assert report["exit_timeout"] is False
    assert report["shutdown_requested"] is True
    adopted = store.read_receipt()
    assert adopted is not None and adopted.describes(stamp)
    assert not store.pending_path.exists()
    assert challenge_path.is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="the native helper is POSIX-only")
def test_the_packaged_native_helper_restores_after_the_root_rejects_startup(
    tmp_path: Path,
) -> None:
    """A real root parse failure must restore the old app and reap its family."""

    source = _require_bundle()
    source_executable = _executable_in(source)
    relative_executable = source_executable.relative_to(source)
    install_parent = tmp_path / "install"
    install_parent.mkdir()
    install_root = install_parent / source.name
    copy_packaged_application(source, install_root)

    staging = install_parent / f".hanly-update-{uuid4().hex}"
    staging.mkdir()
    candidate = staging / source.name
    copy_packaged_application(source, candidate)

    service_root = _service_root(install_root)
    stamp_path = service_root / "_internal" / "hanly_app" / "assets" / "hanly-build.json"
    stamp_bytes = stamp_path.read_bytes()
    stamp = BuildStamp.from_json(stamp_bytes.decode("utf-8"))
    manifest_digest = hashlib.sha256(stamp_bytes).hexdigest()
    transaction_id = f"native-rollback-{uuid4().hex}"
    challenge = new_challenge(transaction_id, stamp.identity, manifest_digest, install_root)
    challenge_path = write_challenge(staging / "challenge.json", challenge)
    ack_path = acknowledgement_path(challenge_path)

    launcher_directory = install_parent / "test-launcher"
    launcher_directory.mkdir()
    launcher = launcher_directory / "hanly-desktop"
    candidate_root = install_root / relative_executable
    launch_log = tmp_path / "launches.txt"
    process_ids = tmp_path / "launched-pids.txt"
    root_pids = tmp_path / "candidate-pids.txt"
    launcher.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                f"printf '%s\\n' \"$$\" >> {shlex.quote(str(process_ids))}",
                f"printf '%s\\n' \"$#\" >> {shlex.quote(str(launch_log))}",
                'if [ "$#" -gt 0 ]; then',
                f"  {shlex.quote(str(candidate_root))} --unsupported-native-update-test &",
                "  candidate_pid=$!",
                f"  printf '%s\\n' \"$candidate_pid\" >> {shlex.quote(str(root_pids))}",
                "  wait \"$candidate_pid\"",
                "  exit $?",
                "fi",
                "exit 0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    launcher.chmod(0o700)

    if install_root.suffix == ".app":
        helper_source = source / "Contents" / "Resources" / "hanly-update-posix"
    else:
        helper_source = source / "resources" / "hanly-update-posix"
    helper = tmp_path / "helper" / "hanly-update-posix"
    helper.parent.mkdir()
    shutil.copy2(helper_source, helper)
    helper.chmod(0o700)

    installed_stat = install_root.stat()
    candidate_stat = candidate.stat()
    transaction = NativeTransaction(
        transaction_id=transaction_id,
        lock_path=staging / "native.lock",
        install_path=install_root,
        staging_path=staging,
        candidate_path=candidate,
        backup_path=staging / "previous",
        rejected_path=staging / "rejected",
        result_path=staging / "result",
        ack_path=ack_path,
        challenge_path=challenge_path,
        expected=challenge.expected(),
        executable="../test-launcher/hanly-desktop",
        launch=LAUNCH_EXEC,
        parent_pid=0,
        exit_timeout=5,
        ready_timeout=2,
        install_device=installed_stat.st_dev,
        install_inode=installed_stat.st_ino,
        candidate_device=candidate_stat.st_dev,
        candidate_inode=candidate_stat.st_ino,
    )
    descriptor = write_descriptor(staging / "descriptor", transaction)
    original_executable_digest = hashlib.sha256(source_executable.read_bytes()).hexdigest()

    outcome = subprocess.run(
        [str(helper), str(descriptor)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert outcome.returncode == 1, outcome.stderr
    assert (staging / "result").read_text(encoding="utf-8").splitlines()[0] == "restored"
    assert not ack_path.exists()
    assert hashlib.sha256((install_root / relative_executable).read_bytes()).hexdigest() == (
        original_executable_digest
    )
    assert launch_log.read_text(encoding="utf-8").splitlines() == ["2", "0"]

    launched_pids = [int(value) for value in process_ids.read_text(encoding="utf-8").splitlines()]
    launched_pids.extend(int(value) for value in root_pids.read_text(encoding="utf-8").splitlines())
    deadline = time.monotonic() + 5
    survivors = launched_pids
    while time.monotonic() < deadline:
        survivors = [pid for pid in launched_pids if _process_is_live(pid)]
        if not survivors:
            break
        time.sleep(0.1)
    assert not survivors, f"update launcher processes survived rollback: {survivors}"


def _process_is_live(process_id: int) -> bool:
    """Treat a reaped process or a transient zombie as stopped."""

    try:
        process = psutil.Process(process_id)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
