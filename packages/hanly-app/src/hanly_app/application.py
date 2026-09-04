"""Production Hanly Desktop V1 composition and lifecycle root.

The module keeps native UI imports inside :func:`run_desktop` so
``preload_ocr_runtime`` can run before Qt.  It composes existing engine,
capture, lookup, popup, Control Center, update, tray, and shutdown seams; it
does not construct providers outside the worker-owned runtime factories.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import Event, RLock
from time import monotonic
from typing import Any, Protocol, cast

from hanly.resource_manager import ResourceManager

from .app_update import (
    ApplicationInstaller,
    ApplicationUpdate,
    ApplicationUpdateError,
    check_application_update,
    installation_root,
)
from .capture import DEFAULT_ROI_GRID, CaptureService, ScreenRect
from .config import CaptureMode, ConfigManager
from .control_center import (
    ControlCenterBridge,
    ControlCenterHost,
    ControlCenterUnavailable,
    prepare_control_center_qt,
)
from .desktop_controller import DesktopController, DesktopState
from .first_run import (
    persist_installed_resource,
    provision_runtime_config,
)
from .manual_lookup import ManualLookupRuntime, RuntimeComposition, create_qt_manual_lookup
from .ocr_preload import preload_ocr_runtime
from .runtime import (
    OCR_DISPLAY_NAME,
    load_runtime,
)
from .runtime_trace import RuntimeTraceSink
from .signal_bridge import QtSignalBridge
from .tray import TrayService
from .update_coordinator import ApplicationInstall, UpdateCoordinator
from .update_service import GitHubReleaseFetcher, ProgressCallback, UpdateService

#: File name a packaged installation uses for its runtime configuration.
RUNTIME_CONFIG_NAME = "runtime.json"

#: How often a worker waiting on the Qt thread rechecks for shutdown.
_DISPATCH_POLL_SECONDS = 0.05

#: Bounded wait for worker-owned providers and SQLite handles at process exit.
_SHUTDOWN_WAIT_SECONDS = 10.0


class DesktopApplicationError(RuntimeError):
    """Raised when the production desktop composition cannot be started."""


class _QtSignal(Protocol):
    def connect(self, callback: Callable[[], None]) -> None: ...


class QtApplication(Protocol):
    @property
    def aboutToQuit(self) -> _QtSignal: ...

    def exec(self) -> int: ...

    def quit(self) -> None: ...

    def exit(self, return_code: int = 0) -> None: ...


class _Lifecycle(Protocol):
    def start(self) -> None: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def shutdown(self) -> None: ...

    def begin_shutdown(self) -> None: ...

    def await_shutdown(self, timeout: float | None = None) -> bool: ...


class _Tray(Protocol):
    def start(self) -> None: ...

    def refresh(self) -> None: ...

    def shutdown(self) -> None: ...


class _ControlCenter(Protocol):
    def open(self) -> None: ...

    def close(self) -> None: ...


class DiagnosticLog:
    """Thread-safe basic diagnostics shared with the Control Center."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._messages: list[str] = []

    def add(self, message: str) -> None:
        normalized = str(message).strip()
        if not normalized:
            return
        with self._lock:
            self._messages.append(normalized)

    def report(self, stage: str, error: BaseException) -> None:
        self.add(f"{stage}: {error}")

    def snapshot(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._messages)


class DesktopApplication:
    """Coordinate the already-composed desktop services and clean shutdown."""

    def __init__(
        self,
        qt_application: QtApplication,
        controller: _Lifecycle,
        tray: _Tray,
        control_center: _ControlCenter,
        *,
        update_coordinator: UpdateCoordinator | None = None,
        diagnostics: DiagnosticLog | None = None,
    ) -> None:
        self._qt = qt_application
        self._controller = controller
        self._tray = tray
        self._control_center = control_center
        self._updates = update_coordinator
        self._diagnostics = diagnostics or DiagnosticLog()
        self._signals: QtSignalBridge | None = None
        self._started = False
        self._shutdown = False
        self._connected = False
        self._closing = Event()
        self._lock = RLock()

    @property
    def diagnostics(self) -> tuple[str, ...]:
        return self._diagnostics.snapshot()

    @property
    def closing(self) -> Event:
        """Set once the Qt loop can no longer run dispatched lifecycle work."""

        return self._closing

    def attach_signal_bridge(self, bridge: QtSignalBridge) -> None:
        with self._lock:
            if self._started:
                raise RuntimeError("signal bridge must be attached before startup")
            self._signals = bridge

    def run(self) -> int:
        """Start the desktop services and enter the shared Qt event loop."""

        with self._lock:
            if not self._connected:
                self._qt.aboutToQuit.connect(self.shutdown)
                self._connected = True
            signals = self._signals
        if signals is not None:
            signals.install()
        self.start_capture()
        try:
            return self._qt.exec()
        finally:
            self.shutdown()

    def start_capture(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            first_start = not self._started
        if first_start:
            self._controller.start()
            try:
                self._tray.start()
            except Exception:
                self._controller.shutdown()
                raise
            with self._lock:
                self._started = True
        else:
            self._controller.resume()
        self._tray.refresh()

    def pause_capture(self) -> None:
        self._controller.pause()
        self._tray.refresh()

    def resume_capture(self) -> None:
        self._controller.resume()
        self._tray.refresh()

    def open_control_center(self) -> None:
        try:
            self._control_center.open()
        except Exception as error:
            self._diagnostics.report("Control Center", error)

    def quit(self) -> None:
        self._qt.quit()

    def shutdown(self) -> None:
        """Stop new input, close providers/resources, and restore signals once."""

        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            signals = self._signals
        # Release any update worker parked on a Qt dispatch before this thread
        # starts waiting for that worker, otherwise the two wait on each other.
        self._closing.set()
        self._tray.shutdown()
        try:
            self._control_center.close()
        finally:
            try:
                self._controller.begin_shutdown()
                if self._updates is not None:
                    self._updates.shutdown(wait=True)
                # Bounded so process exit cannot hang on a stuck provider,
                # but long enough for SQLite handles to close normally.
                self._controller.await_shutdown(_SHUTDOWN_WAIT_SECONDS)
            finally:
                if signals is not None:
                    signals.close()


def run_desktop(
    runtime_config: str | Path,
    *,
    app_config: str | Path | None = None,
    initial_capture_mode: CaptureMode | None = None,
    initial_capture_region: ScreenRect | None = None,
    roi_size: tuple[int, int] | None = None,
    trace_sink: RuntimeTraceSink | None = None,
) -> int:
    """Compose and run the production desktop path from explicit configuration.

    ``trace_sink`` is the developer instrumentation seam: the benchmark harness
    passes a sink that draws events on screen. ``None`` is the shipped path and
    costs nothing -- the tracing wrappers are not constructed at all.
    """

    if initial_capture_mode is None:
        if initial_capture_region is not None:
            raise ValueError("an initial capture region requires region mode")
    elif not isinstance(initial_capture_mode, CaptureMode):
        raise TypeError("initial_capture_mode must be a CaptureMode or None")
    elif initial_capture_mode is CaptureMode.REGION:
        if not isinstance(initial_capture_region, ScreenRect):
            raise ValueError("initial region mode requires a capture region")
    elif initial_capture_region is not None:
        raise ValueError("whole-monitor mode cannot carry a capture region")

    diagnostics = DiagnosticLog()
    runtime_path = Path(runtime_config).expanduser().resolve()
    # EasyOCR must load before Qt so its native libraries see the process's
    # original DLL search path.
    preload_ocr_runtime(
        on_diagnostic=diagnostics.add,
    )

    try:
        prepare_control_center_qt()
        from PyQt6.QtWidgets import QApplication

        from .qt_popup import QtResultDispatcher
    except (ImportError, ControlCenterUnavailable) as error:
        raise DesktopApplicationError(
            "Hanly Desktop requires the hanly-app runtime extra with Qt6"
        ) from error

    application = cast(
        QtApplication,
        QApplication.instance() or QApplication(sys.argv),
    )
    runtime = load_runtime(runtime_path)
    settings = ConfigManager(
        Path(app_config).expanduser().resolve()
        if app_config is not None
        else default_app_config_path()
    )
    settings.load()

    def build_manual(current_runtime: RuntimeComposition) -> ManualLookupRuntime:
        capture = (
            CaptureService(roi_grid=DEFAULT_ROI_GRID, roi_size=roi_size)
            if roi_size is not None
            else CaptureService(roi_grid=DEFAULT_ROI_GRID)
        )
        try:
            manual_runtime = create_qt_manual_lookup(
                current_runtime,
                capture,
                hotkey=settings.config.hotkey,
                app_config=settings.config,
                hover_on_error=lambda stage, error: diagnostics.report(stage, error),
                trace_sink=trace_sink,
            )
            if initial_capture_mode is not None:
                manual_runtime.set_capture_preferences(
                    capture_mode=initial_capture_mode,
                    monitor=None,
                    region=initial_capture_region,
                )
            return manual_runtime
        except Exception:
            capture.close()
            raise

    manual = build_manual(runtime)

    controller = DesktopController(manual)
    dispatcher = QtResultDispatcher()
    previous_state = [DesktopState.NEW]
    bridge_ref: list[ControlCenterBridge] = []
    tray_ref: list[TrayService] = []
    desktop_ref: list[DesktopApplication] = []

    def closing() -> Event | None:
        return desktop_ref[0].closing if desktop_ref else None

    def before_install(_resource_id: str) -> None:
        def prepare() -> None:
            previous_state[0] = controller.state
            # UI-owned teardown only; the worker join happens off this thread.
            controller.begin_shutdown()

        _dispatch_sync(dispatcher, prepare, cancel=closing())
        if not controller.await_shutdown(_SHUTDOWN_WAIT_SECONDS):
            raise DesktopApplicationError(
                "lookup providers did not release their resources before activation"
            )

    def after_install(_resource_id: str) -> None:
        def restore() -> None:
            refreshed_runtime = load_runtime(runtime_path)
            refreshed_manual = build_manual(refreshed_runtime)
            controller.replace_runtime(refreshed_manual)
            bridge_ref[0].replace_capture_service(refreshed_manual.capture_service)
            bridge_ref[0].apply_live_state()
            if previous_state[0] in {DesktopState.RUNNING, DesktopState.PAUSED}:
                controller.start()
            if previous_state[0] is DesktopState.PAUSED:
                controller.pause()
            if tray_ref:
                tray_ref[0].refresh()

        try:
            _dispatch_sync(dispatcher, restore, cancel=closing())
        except DesktopShuttingDown:
            # The desktop is closing; the activated resource is already safe
            # and the rebuilt runtime would be torn down immediately anyway.
            diagnostics.add("Update completed while the desktop was closing.")

    update_coordinator = _update_coordinator(
        runtime_path,
        runtime.resource_manager,
        diagnostics,
        before_install=before_install,
        after_install=after_install,
        # A staged application build only lands when the process holding the
        # old one exits, so finishing the update is the ordinary quit path.
        on_restart_required=lambda: _dispatch_sync(
            dispatcher, desktop_ref[0].quit, cancel=closing()
        ),
        automatic_check=settings.config.update_checks_enabled,
    )
    bridge = ControlCenterBridge(
        config_manager=settings,
        desktop_controller=controller,
        capture_service=manual.capture_service,
        runtime=runtime,
        update_coordinator=update_coordinator,
        diagnostics=diagnostics.snapshot,
        on_lifecycle_changed=lambda: tray_ref[0].refresh() if tray_ref else None,
        ocr_provider=OCR_DISPLAY_NAME,
    )
    bridge_ref.append(bridge)
    control_center = ControlCenterHost(bridge)

    tray = TrayService(
        lambda: controller.state,
        dispatcher=dispatcher,
        on_start=lambda: desktop_ref[0].start_capture(),
        on_resume=lambda: desktop_ref[0].resume_capture(),
        on_pause=lambda: desktop_ref[0].pause_capture(),
        on_open_control_center=lambda: desktop_ref[0].open_control_center(),
        on_quit=lambda: desktop_ref[0].quit(),
    )
    tray_ref.append(tray)
    desktop = DesktopApplication(
        application,
        controller,
        tray,
        control_center,
        update_coordinator=update_coordinator,
        diagnostics=diagnostics,
    )
    desktop_ref.append(desktop)
    signal_bridge = QtSignalBridge(
        application,
        desktop.shutdown,
        on_error=lambda error: diagnostics.report("SIGINT shutdown", error),
    )
    desktop.attach_signal_bridge(signal_bridge)
    return desktop.run()


def default_app_config_path(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the per-user V1 settings path without adding a platform package."""

    env = os.environ if environment is None else environment
    local = env.get("LOCALAPPDATA")
    if local:
        return (Path(local).expanduser() / "Hanly" / "config.json").resolve()
    xdg = env.get("XDG_CONFIG_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return (root / "hanly" / "config.json").resolve()


def default_runtime_config_path(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the per-user runtime configuration path beside the settings file."""

    return default_app_config_path(environment).with_name(RUNTIME_CONFIG_NAME)


def discover_runtime_config(
    environment: Mapping[str, str] | None = None,
    executable: str | Path | None = None,
) -> Path | None:
    """Find a runtime configuration without requiring a command-line argument.

    A packaged installation ships or writes ``runtime.json`` beside the
    executable; a developer or an updated installation keeps it with the
    per-user settings. Explicit ``--runtime-config`` still wins over both.
    """

    beside_executable = (
        Path(sys.executable if executable is None else executable).resolve().parent
        / RUNTIME_CONFIG_NAME
    )
    for candidate in (beside_executable, default_runtime_config_path(environment)):
        if candidate.is_file():
            return candidate
    return None


def _update_coordinator(
    runtime_config: Path,
    resource_manager: ResourceManager,
    diagnostics: DiagnosticLog,
    *,
    before_install: Callable[[str], None] | None = None,
    after_install: Callable[[str], None] | None = None,
    on_restart_required: Callable[[], None] | None = None,
    automatic_check: bool = True,
) -> UpdateCoordinator | None:
    try:
        service = load_update_service(runtime_config, resource_manager)
    except DesktopApplicationError as error:
        diagnostics.report("Update configuration", error)
        return None
    if service is None:
        return None
    application_check, application_install = _application_updates(service)
    coordinator = UpdateCoordinator(
        service,
        resource_manager=resource_manager,
        before_install=before_install,
        after_install=after_install,
        record_install=lambda result: persist_installed_resource(
            runtime_config,
            result.resource.resource_id,
            result.resource.version,
            result.validation.integrity_identity,
        ),
        application_check=application_check,
        application_install=application_install,
        on_restart_required=on_restart_required,
    )
    # The coordinator is always built, so the Control Center's explicit "Check
    # for updates" keeps working; only the unattended startup check is a
    # setting, because it is the one that reaches the network on its own.
    if automatic_check:
        coordinator.check_for_updates()
    return coordinator


def _application_updates(
    service: UpdateService,
) -> tuple[Callable[[], ApplicationUpdate] | None, ApplicationInstall | None]:
    """Return how this installation checks for, and installs, a new Hanly build.

    The resource fetcher already reads the release payload and already knows how
    to download an asset from it, so both halves reuse it rather than opening a
    second channel. An installation that is not a packaged bundle can still be
    told a new build exists; it just has nothing for Hanly to replace.
    """

    fetcher = getattr(service, "fetcher", None)
    release_source = getattr(fetcher, "fetch_release", None)
    if fetcher is None or not callable(release_source):
        return None, None

    install_root = installation_root()

    def check() -> ApplicationUpdate:
        return check_application_update(release_source, install_root=install_root)

    if install_root is None:
        return check, None
    try:
        installer = ApplicationInstaller(fetcher, release_source, install_root=install_root)
    except ApplicationUpdateError:
        return check, None

    def install(update: ApplicationUpdate, on_progress: ProgressCallback | None) -> None:
        installer.apply(installer.stage(update, on_progress=on_progress))

    return check, install


class DesktopShuttingDown(DesktopApplicationError):
    """Raised when lifecycle work is abandoned because the desktop is closing."""


def _dispatch_sync(
    dispatcher: Callable[[Callable[[], None]], None],
    callback: Callable[[], None],
    *,
    cancel: Event | None = None,
    timeout: float = 60.0,
) -> None:
    """Run one lifecycle mutation on Qt's thread from the update worker.

    ``cancel`` is set once the Qt event loop can no longer run callbacks, so a
    worker waiting here stops waiting for a dispatch that can never arrive
    instead of blocking shutdown for the whole timeout.
    """

    completed = Event()
    errors: list[BaseException] = []

    def run() -> None:
        try:
            callback()
        except BaseException as error:
            errors.append(error)
        finally:
            completed.set()

    if cancel is not None and cancel.is_set():
        raise DesktopShuttingDown("desktop is shutting down")

    dispatcher(run)
    deadline = monotonic() + timeout
    while not completed.wait(_DISPATCH_POLL_SECONDS):
        if cancel is not None and cancel.is_set():
            raise DesktopShuttingDown("desktop is shutting down")
        if monotonic() >= deadline:
            raise DesktopApplicationError("timed out waiting for the Qt lifecycle thread")
    if errors:
        raise DesktopApplicationError(
            f"desktop lifecycle update failed: {errors[0]}"
        ) from errors[0]


def load_update_service(
    runtime_config: str | Path,
    resource_manager: ResourceManager,
) -> UpdateService | None:
    """Build the GitHub adapter from optional runtime metadata.

    Returns ``None`` when the runtime configuration declares no ``updates``
    block or disables it, which is how remote delivery stays switched off
    until a release channel is configured.
    """

    payload = _runtime_payload(runtime_config)

    updates = payload.get("updates")
    if updates is None:
        return None
    if not isinstance(updates, Mapping):
        raise DesktopApplicationError("updates must be a JSON object")
    if updates.get("enabled", True) is False:
        return None

    return UpdateService(resource_manager, _github_fetcher(updates))


def _runtime_payload(runtime_config: str | Path) -> Mapping[str, Any]:
    """Read the runtime configuration that may carry an update channel."""

    path = Path(runtime_config).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DesktopApplicationError(f"could not read update configuration: {error}") from error

    if not isinstance(payload, Mapping):
        raise DesktopApplicationError("runtime configuration must be a JSON object")
    return payload


def _github_fetcher(updates: Mapping[str, Any]) -> GitHubReleaseFetcher:
    """Build the release adapter from public, non-secret release coordinates."""

    github = updates.get("github", updates)
    if not isinstance(github, Mapping):
        raise DesktopApplicationError("updates.github must be a JSON object")

    owner = github.get("owner")
    repository = github.get("repository")
    if not isinstance(owner, str) or not isinstance(repository, str):
        raise DesktopApplicationError("updates.github requires owner and repository")

    tag = github.get("tag", "latest")
    manifest_asset = github.get("manifest_asset", "hanly-resources.json")
    if not isinstance(tag, str) or not isinstance(manifest_asset, str):
        raise DesktopApplicationError("update tag and manifest_asset must be strings")

    return GitHubReleaseFetcher(
        owner,
        repository,
        tag=tag,
        manifest_asset=manifest_asset,
    )


def resolve_runtime_config(explicit: Path | None) -> Path:
    """Return the configuration to start from, provisioning a normal launch.

    An explicit path is an operator choice: it neither creates files nor
    reaches the release channel behind the caller's back.
    """

    if explicit is not None:
        return explicit
    discovered = discover_runtime_config() or default_runtime_config_path()
    return provision_runtime_config(
        discovered,
        on_status=_report_startup_status,
    )


def _report_startup_status(message: str) -> None:
    """Expose first-run resource phases to terminal-based launches."""

    print(f"Hanly: {message}", file=sys.stderr, flush=True)


def report_startup_error(error: BaseException) -> None:
    """Report startup failure even when the packaged app has no console."""

    message = f"Hanly Desktop: {error}"
    print(message, file=sys.stderr, flush=True)
    if not getattr(sys, "frozen", False):
        return

    _show_native_startup_error(message)


def _show_native_startup_error(message: str) -> None:
    """Show a minimal native error dialog for a windowed packaged launch."""

    # Keep the established OCR-before-Qt ordering even on the failure
    # path.  A minimal native dialog gives a windowed PyInstaller build an
    # actionable error when stderr is not attached to a terminal.
    preload_ocr_runtime()
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox

        # Bound to a local so a QApplication created here outlives the modal
        # call; `instance()` is typed as the base class, which has no windows.
        application = QApplication.instance() or QApplication(sys.argv)
        parent = application.activeWindow() if isinstance(application, QApplication) else None
        QMessageBox.critical(parent, "Hanly Desktop", message)
    except Exception:
        # stderr remains the fallback for systems without the optional Qt
        # runtime or without a usable display server.
        return


__all__ = [
    "DesktopApplication",
    "DesktopApplicationError",
    "DiagnosticLog",
    "QtApplication",
    "default_app_config_path",
    "default_runtime_config_path",
    "discover_runtime_config",
    "load_update_service",
    "report_startup_error",
    "resolve_runtime_config",
    "run_desktop",
]
