"""Check the packaged Tauri root's Dock identity and owned service family."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import psutil
import pytest

from tests.hanly_fixtures.capabilities import require_display, unavailable
from tests.packaged.shared.test_packaged_desktop import _require_bundle
from tools.build_smoke_krdict import build_smoke_krdict
from tools.smoke_packaged_runtime import isolated_environment

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS app identity")

_INTERVAL = 0.1
_CHILD_GRACE = 15
_BLOCK = re.compile(r'executable path="([^"]+)"\s+pid = (\d+) type="([^"]+)"')


def _registrations() -> dict[int, tuple[str, str]]:
    """Return registered app paths and activation roles from LaunchServices."""

    listing = subprocess.run(
        ["/usr/bin/lsappinfo", "list"], capture_output=True, text=True, timeout=5
    )
    return {int(pid): (path, role) for path, pid, role in _BLOCK.findall(listing.stdout)}


class _Observer:
    """Samples the one native app root, service, and WebKit descendants."""

    def __init__(self, bundle: Path) -> None:
        self.executable = (bundle / "Contents" / "MacOS" / "hanly-desktop").resolve()
        self.service = (
            bundle / "Contents" / "Resources" / "hanly-service" / "hanly-service"
        ).resolve()
        self.root: psutil.Process | None = None
        self.roles: dict[int, str] = {}
        self.activation: dict[int, list[str]] = {}
        self.webkit: set[int] = set()
        self.legacy: set[int] = set()
        self.timeline: list[tuple[float, int, str, str]] = []
        self.started = time.monotonic()

    def find_root(self, timeout: float) -> psutil.Process:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for pid, (path, _role) in _registrations().items():
                if Path(path).resolve() != self.executable:
                    continue
                try:
                    self.root = psutil.Process(pid)
                    return self.root
                except psutil.Error:
                    continue
            time.sleep(_INTERVAL)
        unavailable("the Tauri executable never registered as a macOS application")
        raise AssertionError("unreachable")

    def tree(self) -> list[psutil.Process]:
        assert self.root is not None
        try:
            return [self.root, *self.root.children(recursive=True)]
        except psutil.Error:
            return []

    def sample(self) -> None:
        registrations = _registrations()
        for process in self.tree():
            try:
                executable = Path(process.exe()).resolve()
                name = process.name()
            except (OSError, psutil.Error):
                continue
            if executable == self.executable:
                role = "tauri-root"
            elif executable == self.service:
                role = "python-service"
            elif "webkit" in name.lower() or "webcontent" in name.lower():
                role = "webkit"
                self.webkit.add(process.pid)
            else:
                role = f"child:{name}"
            if "qt" in name.lower() or "qtwebengine" in name.lower():
                self.legacy.add(process.pid)

            self.roles[process.pid] = role
            activation = registrations.get(process.pid, ("", "unregistered"))[1]
            seen = self.activation.setdefault(process.pid, [])
            if not seen or seen[-1] != activation:
                seen.append(activation)
                elapsed = round(time.monotonic() - self.started, 2)
                self.timeline.append((elapsed, process.pid, role, activation))

    def service_process(self) -> psutil.Process | None:
        for process in self.tree()[1:]:
            try:
                if Path(process.exe()).resolve() == self.service:
                    return process
            except (OSError, psutil.Error):
                continue
        return None

    def watch(self, seconds: float, until: Callable[[], bool] | None = None) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.sample()
            if until is not None and until():
                return True
            time.sleep(_INTERVAL)
        return until is None


def test_the_tauri_root_is_the_only_foreground_app_and_owns_the_service(
    tmp_path: Path,
) -> None:
    require_display()
    bundle = _require_bundle()
    settings, home, models = tmp_path / "settings", tmp_path / "home", tmp_path / "models"
    for directory in (settings, home, models):
        directory.mkdir()
    profile = settings / "hanly"
    profile.mkdir()
    (profile / "config.json").write_text(
        json.dumps({"update_checks_enabled": False}), encoding="utf-8"
    )
    environment = isolated_environment(
        os.environ,
        settings,
        home,
        models,
        krdict=build_smoke_krdict(tmp_path / "seed" / "krdict.sqlite3"),
    )
    forwarded_environment = [
        argument
        for name in ("LOCALAPPDATA", "XDG_CONFIG_HOME", "HOME", "HANLY_KRDICT_DB")
        if name in environment
        for argument in ("--env", f"{name}={environment[name]}")
    ]
    observer = _Observer(bundle)
    subprocess.run(
        ["/usr/bin/open", "-n", str(bundle), *forwarded_environment],
        check=True,
        timeout=30,
    )
    root = observer.find_root(60)
    service: psutil.Process | None = None
    survivors: list[psutil.Process] = []
    try:
        assert observer.watch(180, lambda: observer.service_process() is not None), (
            "the Tauri root did not launch its private Python service"
        )
        observer.watch(5)
        service = observer.service_process()
        assert service is not None
        assert service.ppid() == root.pid
        assert observer.roles.get(root.pid) == "tauri-root"
        assert observer.activation.get(root.pid) and "Foreground" in observer.activation[root.pid]

        foreground_descendants = {
            pid: observer.activation[pid]
            for pid in observer.roles
            if pid != root.pid
            and "Foreground" in observer.activation.get(pid, [])
        }
        assert not foreground_descendants, foreground_descendants
        assert not observer.legacy, (
            f"Qt processes remain in the packaged runtime: {observer.legacy}"
        )
    finally:
        owned = observer.tree()[1:]
        try:
            root.send_signal(signal.SIGINT)
            root.wait(30)
        except psutil.Error:
            pass
        _, survivors = psutil.wait_procs(owned, timeout=_CHILD_GRACE)
        for process in survivors:
            process.kill()
        (tmp_path / "identity.json").write_text(
            json.dumps(
                {
                    "root": root.pid,
                    "roles": observer.roles,
                    "activation": observer.activation,
                    "webkit_processes": sorted(observer.webkit),
                    "timeline": observer.timeline,
                    "service": None if service is None else service.pid,
                    "survivors_after_quit": [process.pid for process in survivors],
                },
                indent=1,
            ),
            encoding="utf-8",
        )

    assert not survivors, f"processes outlived the native root: {[item.pid for item in survivors]}"
