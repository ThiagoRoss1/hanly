"""A complete Windows application update on an owned, isolated installation.

The installation is a published release unpacked under the run directory, with
its own profile and TEMP, so nothing here touches the everyday app. The update
itself is the production path: ``TreeUpdateRunner`` and ``UpdateCoordinator``
from this checkout, composed exactly as ``application._tree_runner`` composes
them, against the real public release source (read only), then the real
PowerShell helper, the real relaunch and the new build's own acknowledgement.

What differs from a person clicking Install update is the process hosting the
coordinator: here it is the lab, not the frozen shell, so this proves the
updater code in this checkout against real releases, not the updater shipped
inside the source release. Every observation is labelled with that.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from .. import devtools

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO_ROOT / "artifacts" / "lab" / "runs"
_OWNER, _REPOSITORY = "ThiagoRoss1", "hanly"
_ARCHIVE = "hanly-desktop-windows.zip"
_EXECUTABLE = "hanly-desktop.exe"
#: The helper's own ceiling for a new build to answer, plus room to restore.
_HELPER_DEADLINE = 600 + 120
MODES = ("install", "cancel", "rollback")
#: Words the update panel shows once a check has answered.
_SETTLED_PAGE = ("Install update", "are current", "is current", "up to date")
_MAIN_TEXT = "(() => { const m = document.querySelector('main'); return m ? m.innerText : ''; })()"


@dataclass
class _Run:
    root: Path
    install: Path
    profile: Path
    temp: Path
    port: int
    events: list[dict[str, Any]]
    started: float

    def note(self, stage: str, **fields: Any) -> None:
        event = {"t": round(time.monotonic() - self.started, 2), "stage": stage, **fields}
        self.events.append(event)
        print(f"windows-update: {stage} {json.dumps(fields, ensure_ascii=False)}", flush=True)


def run_windows_update(source_tag: str, mode: str) -> int:
    """Run one isolated update and return 0 only when every expectation held."""

    if os.name != "nt":
        raise SystemExit("lab: windows-update needs Windows")
    if mode not in MODES:
        raise SystemExit(f"lab: --mode is one of {', '.join(MODES)}")

    root = RUNS_ROOT / f"{datetime.now():%Y%m%d-%H%M%S}-windows-update"
    run = _Run(
        root=root,
        install=root / "install",
        profile=root / "profile",
        temp=root / "temp",
        port=_free_port(),
        events=[],
        started=time.monotonic(),
    )
    for directory in (run.install, run.profile, run.temp):
        directory.mkdir(parents=True)
    _isolate(run)

    outcome: dict[str, Any] = {"mode": mode, "source_tag": source_tag}
    try:
        application = _download_release(run, source_tag)
        outcome["source"] = _stamp(application)
        if mode == "cancel":
            outcome.update(_cancel(run, application))
        else:
            outcome.update(_install(run, application, rollback=mode == "rollback"))
    finally:
        _stop_owned(run)
        outcome["remnants"] = _remnants(run)
        outcome["events"] = run.events
        (root / "summary.json").write_text(
            json.dumps(outcome, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    passed = bool(outcome.get("passed"))
    print(f"windows-update: {'passed' if passed else 'FAILED'}; {_display(root / 'summary.json')}")
    return 0 if passed else 1


# -- the installation -----------------------------------------------------------


def _isolate(run: _Run) -> None:
    """Every per-user path this process and its helpers resolve, inside the run."""

    os.environ["LOCALAPPDATA"] = str(run.profile)
    os.environ["TEMP"] = os.environ["TMP"] = str(run.temp)
    tempfile.tempdir = None
    # The relaunched build inherits this through the helper, so the lab can quit it.
    os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = f"127.0.0.1:{run.port}"
    krdict = REPO_ROOT / "data" / "generated" / "krdict.sqlite3"
    if krdict.is_file() and "HANLY_KRDICT_DB" not in os.environ:
        os.environ["HANLY_KRDICT_DB"] = str(krdict)


def _download_release(run: _Run, tag: str) -> Path:
    """Unpack one published Windows build after checking it against SHA256SUMS."""

    from hanly_app.updates.resource_service import GitHubReleaseFetcher

    release = GitHubReleaseFetcher(_OWNER, _REPOSITORY).fetch_release_by_tag(tag)
    assets = {item["name"]: item["browser_download_url"] for item in release.get("assets", [])}
    downloads = run.root / "release"
    downloads.mkdir()
    archive = downloads / _ARCHIVE
    sums = downloads / "SHA256SUMS"
    urllib.request.urlretrieve(assets[_ARCHIVE], archive)
    urllib.request.urlretrieve(assets["SHA256SUMS"], sums)
    published = {
        line.split()[1]: line.split()[0]
        for line in sums.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if published.get(_ARCHIVE) != digest:
        raise SystemExit(f"lab: {tag}'s Windows archive does not match its SHA256SUMS")
    with zipfile.ZipFile(archive) as payload:
        payload.extractall(run.install)
    run.note("installed", tag=tag, sha256=digest)
    return run.install / "hanly-desktop"


def _stamp(application: Path) -> dict[str, Any]:
    path = application / "_internal" / "hanly_app" / "assets" / "hanly-build.json"
    stamp = json.loads(path.read_text(encoding="utf-8"))
    return {key: stamp.get(key) for key in ("version", "build_id", "source_commit")}


# -- the update ---------------------------------------------------------------------


@dataclass
class _Updater:
    coordinator: Any
    runner: Any
    store: Any
    prepared: list[Any]


def _updater(application: Path) -> _Updater:
    from hanly_app.application import _staging_strategy
    from hanly_app.paths import default_recovery_directory
    from hanly_app.updates.build_identity import BuildStamp, receipt_store
    from hanly_app.updates.coordinator import UpdateCoordinator
    from hanly_app.updates.desktop_update import check_application_update
    from hanly_app.updates.installer import TreeUpdateInstaller
    from hanly_app.updates.resource_service import GitHubReleaseFetcher
    from hanly_app.updates.runner import TreeUpdateRunner

    stamp_path = application / "_internal" / "hanly_app" / "assets" / "hanly-build.json"
    stamp = BuildStamp.from_json(stamp_path.read_text(encoding="utf-8"))
    fetcher = GitHubReleaseFetcher(_OWNER, _REPOSITORY)
    store = receipt_store(application)
    installer = TreeUpdateInstaller(
        fetcher,
        fetcher.fetch_release,
        stamp=stamp,
        install_root=application,
        store=store,
        strategy=_staging_strategy(stamp, application, store),
        tagged_release_source=fetcher.fetch_release_by_tag,
    )
    runner = TreeUpdateRunner(installer, store=store, recovery_root=default_recovery_directory())
    prepared: list[Any] = []
    prepare = runner.prepare

    def recording_prepare(*args: Any, **kwargs: Any) -> Any:
        result = prepare(*args, **kwargs)
        prepared.append(result)
        return result

    runner.prepare = recording_prepare  # type: ignore[method-assign]

    class _NoResources:
        """The resource half is not under test; it reports nothing to install."""

        def check_for_updates(self) -> tuple[()]:
            return ()

        def install(self, resource_id: str, *, on_progress: Any = None) -> Any:
            raise RuntimeError("resources are not part of this check")

    coordinator = UpdateCoordinator(
        _NoResources(),
        application_check=lambda: check_application_update(
            fetcher.fetch_release, current_version=stamp.version, install_root=application
        ),
        application_installer=runner,
    )
    return _Updater(coordinator, runner, store, prepared)


def _settle(run: _Run, updater: _Updater, seconds: float) -> dict[str, Any]:
    """Follow the coordinator until it owns nothing or has handed off."""

    coordinator = updater.coordinator
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        snapshot = coordinator.snapshot()
        if snapshot["status"] != last:
            last = snapshot["status"]
            run.note("coordinator", status=last)
        with coordinator._lock:
            active = coordinator._future is not None
        if not active or snapshot["status"] == "restart":
            return dict(snapshot)
        time.sleep(0.2)
    return dict(coordinator.snapshot())


def _offer(run: _Run, updater: _Updater) -> dict[str, Any] | None:
    updater.coordinator.check_for_updates()
    snapshot = _settle(run, updater, 120)
    application = snapshot.get("application")
    installable = bool(application and application.get("installable"))
    run.note("checked", available=installable, latest=(application or {}).get("latest_version"))
    return application if installable else None


def _cancel(run: _Run, application: Path) -> dict[str, Any]:
    updater = _updater(application)
    if not _offer(run, updater):
        return {"passed": False, "reason": "no update was offered"}
    updater.coordinator.install_application_update(False)
    while updater.coordinator.snapshot()["status"] == "preparing":
        time.sleep(0.05)
    run.note("cancel_requested", during=updater.coordinator.snapshot()["status"])
    updater.coordinator.cancel_update()
    final = _settle(run, updater, 300)
    unchanged = _stamp(application)
    passed = final["status"] == "cancelled" and not (application / ".hanly-update").exists()
    return {"passed": passed, "final_status": final["status"], "after": unchanged}


def _install(run: _Run, application: Path, *, rollback: bool) -> dict[str, Any]:
    source = _launch(run, application) if rollback else None
    updater = _updater(application)
    offered = _offer(run, updater)
    if not offered:
        return {"passed": False, "reason": "no update was offered"}
    updater.coordinator.install_application_update(False)
    staged = _settle(run, updater, 1800)
    if staged["status"] != "restart":
        return {
            "passed": False,
            "reason": f"staging ended {staged['status']}",
            "message": public_message(staged.get("message")),
        }

    transaction = _transaction(application)
    if rollback:
        _sabotage_new_executable(run, transaction)
        _quit_through_page(run, application)
        assert source is not None
        source.wait(30)
    result = _await_result(run, transaction)
    phases = _phases(transaction)
    prepared = updater.prepared[-1]

    after = _stamp(application)
    outcome: dict[str, Any] = {
        "target": {"version": offered.get("latest_version")},
        "helper_result": result,
        "helper_phases": phases,
        "after": after,
    }
    # Committed, the new build relaunched; restored, the previous one did.
    outcome["relaunched_page"] = _await_page(run, 300)
    # The relaunched build checks for updates on its own, a moment after it opens.
    _await(lambda: any(word in _page_text(run) for word in _SETTLED_PAGE), 120)
    outcome["relaunched_page_offers_update"] = "Install update" in _page_text(run)
    _quit_through_page(run, application)
    _relaunch_to_settle(run, application)

    expected = prepared.base if rollback else prepared.target
    matches = _matches(application, expected)
    outcome["manifest_matches"] = matches
    if rollback:
        outcome["reoffered"] = bool(_offer(run, _updater(application)))
        outcome["passed"] = (
            result.get("outcome") == "restored"
            and after["build_id"] == prepared.base.identity.build_id
            and matches
            and outcome["reoffered"]
        )
        return outcome

    reoffered = bool(_offer(run, _updater(application)))
    outcome["reoffered"] = reoffered
    outcome["passed"] = (
        result.get("outcome") == "committed"
        and after["build_id"] == prepared.target.identity.build_id
        and matches
        and not reoffered
        and not outcome["relaunched_page_offers_update"]
    )
    return outcome


# A path runs to whitespace or a quote; sentence punctuation after it stays text.
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)(?:[^\s'\";,]*[^\s'\";,.])?")


def public_message(message: object) -> str | None:
    """The coordinator's failure text with every absolute path removed.

    The updater's own wording names the failing step; the paths it may quote are
    the run's or the user's, and neither belongs in a summary.
    """

    if not isinstance(message, str):
        return None
    return _ABSOLUTE_PATH.sub("<path>", message)


def _transaction(application: Path) -> Path:
    working = application / ".hanly-update"
    return next(path for path in working.iterdir() if path.is_dir())


def _sabotage_new_executable(run: _Run, transaction: Path) -> None:
    """Replace the staged new executable with bytes that cannot start.

    Only the staged copy inside this run's own transaction changes, before the
    helper applies anything; it is how a new build that never answers is made.
    """

    plan = json.loads((transaction / "plan.json").read_text(encoding="utf-8"))
    operation = next(item for item in plan["operations"] if item["path"] == _EXECUTABLE)
    (transaction / operation["payload"]).write_bytes(b"not a program: lab rollback check")
    run.note("staged_executable_replaced", operation=operation["index"])


def _await_result(run: _Run, transaction: Path) -> dict[str, Any]:
    deadline = time.monotonic() + _HELPER_DEADLINE
    result_path = transaction / "result.json"
    while time.monotonic() < deadline:
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                time.sleep(0.5)
                continue
            run.note("helper_result", outcome=result.get("outcome"))
            return {"outcome": result.get("outcome"), "detail": result.get("detail")}
        if not transaction.exists():
            # A relaunched build settles and removes a finished transaction.
            run.note("helper_result", outcome="settled_before_read")
            return {"outcome": "settled_before_read"}
        time.sleep(0.5)
    return {"outcome": "no_result"}


def _phases(transaction: Path) -> list[str]:
    try:
        lines = (transaction / "progress.jsonl").read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    phases: list[str] = []
    for line in lines:
        phase = json.loads(line).get("phase")
        if phase != "operation" and phase != "applied" and (not phases or phases[-1] != phase):
            phases.append(phase)
    return phases


def _matches(application: Path, target: Any) -> bool:
    from hanly_app.updates.inventory import compare_tree, read_tree

    return bool(compare_tree(read_tree(application, "windows"), target).matches)


# -- the running application ----------------------------------------------------------


def _owned(run: _Run) -> list[psutil.Process]:
    """Processes running an executable inside this run's installation, and no others."""

    prefix = str(run.install.resolve()).lower() + os.sep
    found = []
    for process in psutil.process_iter(["exe"]):
        exe = (process.info.get("exe") or "").lower()
        if exe.startswith(prefix):
            found.append(process)
    return found


def _launch(run: _Run, application: Path) -> subprocess.Popen[bytes]:
    started = subprocess.Popen([str(application / _EXECUTABLE)], cwd=application)
    run.note("launched", version=_stamp(application)["version"])
    _await_page(run, 180)
    return started


def _await_page(run: _Run, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if devtools.page_targets(run.port) and _page_text(run):
            return True
        time.sleep(0.5)
    return False


def _page_text(run: _Run) -> str:
    try:
        value = devtools.evaluate(run.port, _MAIN_TEXT)
    except (OSError, ValueError):
        return ""
    return value if isinstance(value, str) else ""


def _click(run: _Run, label: str) -> bool:
    script = (
        "(() => { const b = [...document.querySelectorAll('button')]"
        f".find(e => e.innerText.trim() === {json.dumps(label)});"
        " if (!b) return false; b.click(); return true; })()"
    )
    try:
        return bool(devtools.evaluate(run.port, script))
    except (OSError, ValueError):
        return False


def _quit_through_page(run: _Run, application: Path) -> None:
    """Quit the way a person does, then wait for every owned process to leave."""

    if _click(run, "Quit Hanly"):
        time.sleep(0.5)
        _click(run, "Quit")
    _await(lambda: not _owned(run), 60)
    run.note("quit", remaining=len(_owned(run)))


def _relaunch_to_settle(run: _Run, application: Path) -> None:
    """One ordinary launch, which is what settles whatever the helper left."""

    _launch(run, application)
    _await(lambda: not (application / ".hanly-update").exists(), 60)
    run.note("settled", working_area=(application / ".hanly-update").exists())
    _quit_through_page(run, application)


def _stop_owned(run: _Run) -> None:
    for process in _owned(run):
        try:
            process.kill()
        except psutil.Error:
            continue


def _await(condition: Callable[[], bool], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.5)
    return condition()


def _remnants(run: _Run) -> dict[str, Any]:
    """What the run's own installation, profile and TEMP still hold."""

    application = run.install / "hanly-desktop"
    updates = run.profile / "Hanly" / "updates"
    recovery = run.profile / "Hanly" / "recovery"
    return {
        "working_area": (application / ".hanly-update").exists(),
        "temp_entries": sorted(path.name for path in run.temp.iterdir()),
        "recovery": sorted(path.name for path in recovery.iterdir()) if recovery.is_dir() else [],
        "update_state": sorted(
            path.name for path in updates.glob("*/*") if path.is_file()
        )
        if updates.is_dir()
        else [],
    }


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return path.name


__all__ = ["MODES", "run_windows_update"]
