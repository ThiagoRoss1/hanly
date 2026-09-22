"""Which reader each platform gets, and what a platform must not drag in.

Two adapters now answer the same provider seam. The rules that keep them apart
are that a host only ever loads its own one, that the engine loads neither, and
that adding the second did not quietly change what the first is given.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from hanly_app import text_acquisition
from hanly_app.text_acquisition import DirectTextService, default_text_acquisition
from hanly_app.text_acquisition_ax import AccessibilityTextProvider
from hanly_app.text_acquisition_uia import UIAutomationTextProvider

_ROOT = Path(__file__).parents[1]
_ENGINE = _ROOT / "packages" / "hanly" / "src" / "hanly"
_ADAPTER = _ROOT / "packages" / "hanly-app" / "src" / "hanly_app" / "text_acquisition_uia.py"

#: Modules that only exist to talk to one operating system.
_PLATFORM_MODULES = ("ctypes", "winreg", "msvcrt", "PyQt6", "pynput", "mss")


def _service_for(platform: str, monkeypatch: pytest.MonkeyPatch) -> DirectTextService | None:
    monkeypatch.setattr(sys, "platform", platform)
    return default_text_acquisition()


@pytest.mark.parametrize("platform", ["linux", "freebsd", "emscripten"])
def test_a_platform_without_a_reader_captures_and_runs_ocr_as_before(
    platform: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _service_for(platform, monkeypatch) is None


def test_windows_reads_through_ui_automation_without_a_grant_to_ask_for() -> None:
    """UI Automation is readable by any process; integrity level bounds it instead."""

    coordinator = text_acquisition._windows_coordinator()

    assert coordinator is not None
    assert isinstance(coordinator._provider, UIAutomationTextProvider)
    assert coordinator._permitted is None


def test_macos_still_reads_through_accessibility_behind_its_grant() -> None:
    """The reviewed macOS selection is what a second platform must not disturb."""

    from hanly_app.permissions_darwin import accessibility_trusted

    coordinator = text_acquisition._darwin_coordinator()

    assert coordinator is not None
    assert isinstance(coordinator._provider, AccessibilityTextProvider)
    assert coordinator._permitted is accessibility_trusted


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("win32", UIAutomationTextProvider), ("darwin", AccessibilityTextProvider)],
)
def test_each_host_is_given_its_own_reader(
    platform: str, expected: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service_for(platform, monkeypatch)

    assert service is not None
    try:
        assert isinstance(service._coordinator._provider, expected)
    finally:
        service.close()


def test_selecting_a_reader_imports_only_that_host_s_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A macOS build must never load COM, and a Windows build never pyobjc."""

    loaded: list[str] = []
    real_import = __import__

    def record(name: str, *rest: object, **kwargs: object) -> object:
        loaded.append(name)
        return real_import(name, *rest, **kwargs)  # type: ignore[arg-type]

    for module in ("hanly_app.text_acquisition_uia", "hanly_app.text_acquisition_ax"):
        sys.modules.pop(module, None)
    monkeypatch.setattr("builtins.__import__", record)

    service = _service_for("darwin", monkeypatch)
    if service is not None:
        service.close()

    assert not any("uia" in name for name in loaded)


def test_the_adapter_enters_no_apartment_while_being_imported() -> None:
    """Importing it must be free; a first hover is what pays for the apartment."""

    tree = ast.parse(_ADAPTER.read_text(encoding="utf-8"))
    native = {"_load_library", "CoInitializeEx", "CoCreateInstance", "_create_bridge"}
    called = {
        _callee(node)
        for statement in tree.body
        if not isinstance(statement, (ast.FunctionDef, ast.ClassDef))
        for node in ast.walk(statement)
        if isinstance(node, ast.Call)
    }

    assert called.isdisjoint(native)


def _callee(call: ast.Call) -> str:
    target = call.func
    if isinstance(target, ast.Attribute):
        return target.attr
    return target.id if isinstance(target, ast.Name) else ""


def test_the_engine_reaches_for_no_operating_system_at_all() -> None:
    """``hanly`` is distributable on its own, so neither adapter may leak into it."""

    violations: list[str] = []
    for source_file in _ENGINE.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(
                name == root or name.startswith(f"{root}.")
                for name in names
                for root in _PLATFORM_MODULES
            ):
                violations.append(f"{source_file.name}: {names}")

    assert violations == []
