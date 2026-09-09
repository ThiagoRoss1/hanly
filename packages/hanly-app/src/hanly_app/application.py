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
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
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
from .capture_selector import CaptureSelection, select_capture_area
from .config import AppConfig, CaptureMode, ConfigError, ConfigManager
from .control_center import (
    RUNTIME_NOT_READY,
    ControlCenterBridge,
    ControlCenterUnavailable,
)
from .control_center_host import ControlCenterHost
from .desktop_controller import DesktopController, DesktopState
from .diagnostics import DiagnosticLog, StartupTimeline
from .first_run import (
    persist_installed_resource,
    provision_runtime_config,
)
from .lookup_controller import ResultDispatcher
from .manual_lookup import ManualLookupRuntime, RuntimeComposition, create_qt_manual_lookup
from .ocr_preload import record_preload_timing
from .paths import (
    RUNTIME_CONFIG_NAME,
    default_app_config_path,
    default_log_directory,
    default_runtime_config_path,
    discover_runtime_config,
)
from .permissions import (
    START_CAPTURE_PERMISSIONS,
    PermissionService,
    create_permission_service,
    missing_permission_refusal,
)
from .qt_bootstrap import ensure_qt_application
from .runtime import (
    OCR_DISPLAY_NAME,
    HanlyRuntime,
    load_runtime,
)
from .runtime_status import RuntimeStatus, RuntimeStatusPublisher, watch_worker_readiness
from .runtime_trace import RuntimeTraceSink
from .signal_bridge import QtSignalBridge
from .startup import StartupCoordinator
from .tray import TrayService
from .update_coordinator import ApplicationInstall, UpdateCoordinator
from .update_service import GitHubReleaseFetcher, ProgressCallback, UpdateService

#: How long a bridge-initiated capture selection may wait for the user.
_SELECTION_TIMEOUT_SECONDS = 600.0

#: How often a worker waiting on the Qt thread rechecks for shutdown.
_DISPATCH_POLL_SECONDS = 0.05

#: How long an ordinary lifecycle action may wait for the Qt thread.
_DISPATCH_TIMEOUT_SECONDS = 60.0

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
    @property
    def can_restore_window(self) -> bool: ...

    def start(self) -> None: ...

    def refresh(self) -> None: ...

    def shutdown(self) -> None: ...


class _Startup(Protocol):
    def begin_shutdown(self) -> None: ...

    def await_shutdown(self, timeout: float = ...) -> bool: ...


class _ControlCenter(Protocol):
    """The main window and, in production, the process's only event loop."""

    def run(self) -> int: ...

    def show(self) -> None: ...

    def close(self) -> None: ...

    def set_restorable(self, restorable: bool) -> None: ...


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
        self._startup: _Startup | None = None
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
        """Show the interface and run the one GUI event loop.

        The loop belongs to the Control Center host: pywebview's Qt backend
        calls ``QApplication.exec`` itself, so a second ``exec`` here would be
        the nested loop the release warned about. Capture is deliberately not
        started: the window opens, the runtime prepares behind it, and the user
        decides when Hanly starts watching the screen.
        """

        with self._lock:
            if not self._connected:
                self._qt.aboutToQuit.connect(self.shutdown)
                self._connected = True
            signals = self._signals
        if signals is not None:
            signals.install()
        self._start_tray()
        try:
            return self._control_center.run()
        finally:
            self.shutdown()

    def start_capture(self) -> None:
        """Begin, or resume, watching the screen. The user's Start action."""

        with self._lock:
            if self._shutdown:
                return
            first_start = not self._started
        if first_start:
            self._controller.start()
            with self._lock:
                self._started = True
        else:
            self._controller.resume()
        self._tray.refresh()

    def attach_updates(self, coordinator: UpdateCoordinator | None) -> None:
        """Adopt the update coordinator built once the runtime was prepared."""

        with self._lock:
            self._updates = coordinator

    def attach_startup(self, startup: _Startup) -> None:
        """Adopt the preparation to stop before waiting on worker shutdown."""

        with self._lock:
            self._startup = startup

    def pause_capture(self) -> None:
        self._controller.pause()
        self._tray.refresh()

    def resume_capture(self) -> None:
        self._controller.resume()
        self._tray.refresh()

    def request_capture(self) -> None:
        """Start capture from the tray, reporting a not-yet-ready runtime.

        The tray runs this inside a Qt slot, where an exception would be lost;
        the Control Center calls the lifecycle directly and shows the error.
        """

        try:
            self.start_capture()
        except ControlCenterUnavailable as refusal:
            self._diagnostics.add(str(refusal))
        except Exception as error:
            self._diagnostics.report("Start capture", error)

    def open_control_center(self) -> None:
        try:
            self._control_center.show()
        except Exception as error:
            self._diagnostics.report("Control Center", error)

    def _start_tray(self) -> None:
        """Start the tray, and hide on close only if it can undo that.

        Starting is not the same as being usable: a backend with neither a
        menu nor a default action is no way back to a hidden window, so the
        main window stays closable-to-quit rather than leaving a running
        process the user cannot reach.
        """

        try:
            self._tray.start()
        except Exception as error:
            self._diagnostics.report("System tray", error)
            return
        if not self._tray.can_restore_window:
            self._diagnostics.add(
                "The system tray cannot restore a hidden window; "
                "closing the Control Center will quit Hanly."
            )
            return
        self._control_center.set_restorable(True)

    def quit(self) -> None:
        self._qt.quit()

    def shutdown(self) -> None:
        """Stop new input, close providers/resources, and restore signals once."""

        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            signals = self._signals
            startup = self._startup
            updates = self._updates
        # Release any update worker parked on a Qt dispatch before this thread
        # starts waiting for that worker, otherwise the two wait on each other.
        self._closing.set()
        if startup is not None:
            startup.begin_shutdown()
        self._tray.shutdown()
        try:
            self._control_center.close()
        finally:
            try:
                self._controller.begin_shutdown()
                if updates is not None:
                    updates.shutdown(wait=True)
                if startup is not None:
                    startup.await_shutdown(_SHUTDOWN_WAIT_SECONDS)
                # Bounded so process exit cannot hang on a stuck provider,
                # but long enough for SQLite handles to close normally.
                self._controller.await_shutdown(_SHUTDOWN_WAIT_SECONDS)
            finally:
                if signals is not None:
                    signals.close()


class _DesktopSession:
    """The desktop shell, plus the services that need a prepared runtime.

    The shell, window, tray, settings, diagnostics, status, exists before
    any resource work, so the interface is on screen while Hanly is still
    downloading and validating. Everything that needs a validated runtime is
    built in :meth:`activate`, on the Qt thread.

    It is also the lifecycle the Control Center, tray, and application talk to:
    before activation each control fails with a message that says Hanly is
    still preparing, rather than with a missing attribute.
    """

    def __init__(
        self,
        settings: ConfigManager,
        *,
        diagnostics: DiagnosticLog,
        status: RuntimeStatusPublisher,
        dispatcher: ResultDispatcher,
        roi_size: tuple[int, int] | None = None,
        trace_sink: RuntimeTraceSink | None = None,
        timeline: StartupTimeline | None = None,
        permission_service: PermissionService | None = None,
    ) -> None:
        self._settings = settings
        self._diagnostics = diagnostics
        self._status = status
        self._dispatcher = dispatcher
        self._roi_size = roi_size
        self._trace_sink = trace_sink
        self._timeline = timeline or StartupTimeline()
        self._permissions = (
            permission_service
            if permission_service is not None
            else create_permission_service()
        )

        self._controller: DesktopController | None = None
        self._manual: ManualLookupRuntime | None = None
        self._updates: UpdateCoordinator | None = None
        self._runtime_path: Path | None = None
        self._previous_state = DesktopState.NEW
        self._closing: Event | None = None
        # Identifies the runtime composed here; only the Qt thread changes it.
        self._generation = 0
        self._pending_release: list[DesktopController] = []

        self.bridge = ControlCenterBridge(
            config_manager=settings,
            desktop_controller=self,
            diagnostics=diagnostics.snapshot,
            runtime_status=lambda: status.status,
            capture_ready=lambda: self.can_start_capture,
            on_select_capture_area=self._select_capture_area,
            on_quit=self.quit,
            log_path=diagnostics.path,
            on_lifecycle_changed=self.refresh_tray,
            permission_service=self._permissions,
            ocr_provider=OCR_DISPLAY_NAME,
        )
        self.host = ControlCenterHost(
            self.bridge, diagnostics=diagnostics, timeline=self._timeline
        )
        self.tray = TrayService(
            lambda: self.state,
            dispatcher=dispatcher,
            detail_provider=lambda: status.status.message or None,
            ready_provider=lambda: status.status.ready,
            on_start=lambda: self.desktop.request_capture(),
            on_resume=lambda: self.desktop.request_capture(),
            on_pause=lambda: self.desktop.pause_capture(),
            on_open_control_center=lambda: self.desktop.open_control_center(),
            on_quit=lambda: self.desktop.quit(),
        )

    @property
    def updates(self) -> UpdateCoordinator | None:
        return self._updates

    def attach(self, desktop: DesktopApplication) -> None:
        """Give the session the application whose loop and closing flag it uses."""

        self.desktop = desktop
        self._closing = desktop.closing
        self._status.subscribe(lambda _snapshot: self.refresh_tray())

    def refresh_tray(self) -> None:
        self.tray.refresh()

    def activate(self, runtime: HanlyRuntime) -> None:
        """Compose everything that needs a validated runtime, on the Qt thread."""

        manual = self._build_manual(runtime)
        self._manual = manual
        self._controller = DesktopController(manual)
        self._runtime_path = runtime.config_path
        self._updates = self._build_update_coordinator(runtime)
        self.bridge.attach_runtime(runtime, manual.capture_service, self._updates)
        self.desktop.attach_updates(self._updates)

        # Providers warm now so the interface can report READY, but nothing
        # observes the screen until the user asks Hanly to start.
        manual.prepare()
        self._watch_readiness(manual)
        self.refresh_tray()

    def _watch_readiness(self, manual: ManualLookupRuntime) -> None:
        """Report this runtime's readiness, and only while it is still ours."""

        self._generation += 1
        generation = self._generation
        watch_worker_readiness(
            manual.controller,
            self._status,
            is_current=lambda: self._generation == generation,
        )

    def release(self) -> None:
        """Drop a failed attempt's services so a retry starts from nothing.

        A JobExecutor is single-use, so retrying means a new worker rather than
        restarting the old one. The startup thread calls this, so only the
        UI-owned half runs on Qt: waiting for worker-owned providers and
        SQLite handles would otherwise freeze the window for the whole
        shutdown timeout. Ownership is held until that wait returns, so a
        replacement is never activated over a resource the old attempt still
        has open, and the update worker is retired rather than orphaned.

        Runtime status is left to the coordinator that asked for the release:
        waiting out the previous providers takes seconds, and reporting a
        settled phase for that long tells the interface no further news is
        coming while the retry is still under way.
        """

        released: list[DesktopController] = []
        retired: list[UpdateCoordinator] = []

        def detach() -> None:
            manual = self._manual
            controller = self._controller
            updates = self._updates
            self._manual = None
            self._controller = None
            self._updates = None
            # A watcher still waiting on the runtime being dropped no longer
            # speaks for what this session shows.
            self._generation += 1
            self.desktop.attach_updates(None)
            if controller is not None:
                controller.begin_shutdown()
                released.append(controller)
            elif manual is not None:
                manual.begin_shutdown()
            if updates is not None:
                retired.append(updates)
            self.refresh_tray()

        self._on_qt(detach)
        for coordinator in retired:
            coordinator.shutdown(wait=True)
        self._await_released(released)

    def _await_released(self, released: list[DesktopController]) -> None:
        """Wait out every runtime this session has stopped using.

        A runtime that has not let go of its models and database handles keeps
        ownership of them: it is carried into the next release rather than
        forgotten, and preparation stops instead of composing a replacement
        over resources that are still open.
        """

        pending = self._pending_release + released
        self._pending_release = []
        for index, controller in enumerate(pending):
            if not controller.await_shutdown(_SHUTDOWN_WAIT_SECONDS):
                self._pending_release = pending[index:]
                self._diagnostics.add(
                    "The previous lookup runtime did not release its resources in time."
                )
                raise DesktopApplicationError(
                    "the previous lookup runtime did not release its resources in time"
                )

    @property
    def state(self) -> DesktopState:
        controller = self._controller
        return DesktopState.NEW if controller is None else controller.state

    @property
    def can_start_capture(self) -> bool:
        """Whether a prepared runtime exists for a capture action to reach."""

        return self._controller is not None

    def start(self) -> None:
        self._start_or_resume()

    def pause(self) -> None:
        self._on_qt(lambda: self._with_controller(DesktopController.pause))

    def resume(self) -> None:
        self._start_or_resume()

    def apply_config(self, config: AppConfig) -> None:
        def apply(controller: DesktopController) -> None:
            controller.apply_config(config)

        self._on_qt(lambda: self._with_controller(apply))

    def set_capture_preferences(
        self,
        *,
        capture_mode: CaptureMode,
        monitor: int | None,
        region: ScreenRect | None,
    ) -> None:
        def apply(controller: DesktopController) -> None:
            controller.set_capture_preferences(
                capture_mode=capture_mode,
                monitor=monitor,
                region=region,
            )

        self._on_qt(lambda: self._with_controller(apply))

    def quit(self) -> None:
        """End the session from the main window, the way Quit has to work.

        ``QApplication.quit`` blocks when it is called from anywhere but the
        thread running the loop, and Control Center actions all arrive off it.
        """

        self._on_qt(self.desktop.quit)

    def shutdown(self) -> None:
        self._on_qt(lambda: self._with_controller(DesktopController.shutdown))

    def begin_shutdown(self) -> None:
        self._on_qt(lambda: self._with_controller(DesktopController.begin_shutdown))

    def await_shutdown(self, timeout: float | None = None) -> bool:
        controller = self._controller
        return True if controller is None else controller.await_shutdown(timeout)

    def _select_capture_area(self) -> CaptureSelection | None:
        """Suspend observation, show the overlay, and restore, all on Qt.

        pywebview delivers bridge calls off the UI thread, and the overlay is a
        Qt widget covering the virtual desktop; reading Hanly's own overlay is
        not a useful answer, so observation is suspended for the whole choice.
        Suspend, choose, and restore travel as one dispatched action, so a
        cancelled selection cannot leave observation switched off.
        """

        chosen: list[CaptureSelection | None] = []

        def choose() -> None:
            controller = self._controller
            observing = controller is not None and controller.state is DesktopState.RUNNING
            if observing and controller is not None:
                controller.pause()
            try:
                chosen.append(select_capture_area())
            finally:
                if observing and controller is not None:
                    controller.resume()

        self._on_qt(choose, timeout=_SELECTION_TIMEOUT_SECONDS)
        return chosen[0] if chosen else None

    def _on_qt(
        self,
        callback: Callable[[], None],
        *,
        timeout: float = _DISPATCH_TIMEOUT_SECONDS,
    ) -> None:
        """Run one lifecycle mutation on the thread that owns the Qt loop.

        Capture, hotkeys, the popup, and the overlay are Qt-owned, while the
        Control Center delivers its actions on a pywebview thread and startup
        preparation on its own. Every mutation therefore crosses here, and
        failure and shutdown cancellation travel back to whoever asked.
        """

        if threading.current_thread() is threading.main_thread():
            callback()
            return
        _dispatch_sync(
            self._dispatcher,
            callback,
            cancel=self._closing,
            timeout=timeout,
        )

    def _start_or_resume(self) -> None:
        """Begin observing, whether this attempt has ever run or was paused.

        Start and Resume are one action here because only the Qt thread may
        read the controller's state, and a retry replaces a paused runtime
        with a new one that has never started.
        """

        missing = self._permissions.missing(START_CAPTURE_PERMISSIONS)
        if missing:
            raise ControlCenterUnavailable(missing_permission_refusal(missing))

        rejected: list[str] = []

        def begin() -> None:
            controller = self._controller
            if controller is None:
                # Preparation can finish, or fail, between the caller's check
                # and this dispatch; the reply is still an ordinary refusal.
                rejected.append(RUNTIME_NOT_READY)
                return
            if controller.state is DesktopState.PAUSED:
                controller.resume()
            else:
                controller.start()

        self._on_qt(begin)
        if rejected:
            raise ControlCenterUnavailable(rejected[0])

    def _with_controller(self, action: Callable[[DesktopController], None]) -> None:
        """Apply one action to the controller, if a prepared runtime has one."""

        controller = self._controller
        if controller is not None:
            action(controller)

    def _require_controller(self) -> DesktopController:
        controller = self._controller
        if controller is None:
            raise ControlCenterUnavailable(RUNTIME_NOT_READY)
        return controller

    def _build_manual(self, runtime: RuntimeComposition) -> ManualLookupRuntime:
        capture = (
            CaptureService(roi_grid=DEFAULT_ROI_GRID, roi_size=self._roi_size)
            if self._roi_size is not None
            else CaptureService(roi_grid=DEFAULT_ROI_GRID)
        )
        try:
            return create_qt_manual_lookup(
                runtime,
                capture,
                hotkey=self._settings.config.hotkey,
                app_config=self._settings.config,
                hover_on_error=self._diagnostics.report,
                on_initialization_error=lambda error: _report_initialization_failure(
                    self._status, self._diagnostics, error
                ),
                trace_sink=self._trace_sink,
            )
        except Exception:
            capture.close()
            raise

    def _build_update_coordinator(self, runtime: HanlyRuntime) -> UpdateCoordinator | None:
        return _update_coordinator(
            runtime.config_path,
            runtime.resource_manager,
            self._diagnostics,
            before_install=self._before_install,
            after_install=lambda resource_id: self._after_install(resource_id, runtime),
            # A staged application build only lands when the process holding
            # the old one exits, so finishing the update is the quit path.
            on_restart_required=lambda: _dispatch_sync(
                self._dispatcher, self.desktop.quit, cancel=self._closing
            ),
            automatic_check=self._settings.config.update_checks_enabled,
        )

    def _before_install(self, _resource_id: str) -> None:
        def prepare() -> None:
            self._previous_state = self.state
            # Already on Qt, and UI-owned teardown only; the worker join
            # happens on the update thread once this dispatch returns.
            self._with_controller(DesktopController.begin_shutdown)

        _dispatch_sync(self._dispatcher, prepare, cancel=self._closing)
        if not self.await_shutdown(_SHUTDOWN_WAIT_SECONDS):
            raise DesktopApplicationError(
                "lookup providers did not release their resources before activation"
            )

    def _after_install(self, _resource_id: str, previous: HanlyRuntime) -> None:
        def restore() -> None:
            refreshed = load_runtime(previous.config_path)
            manual = self._build_manual(refreshed)
            self._manual = manual
            self._status.update(
                "preparing", "lookup providers", "Loading the lookup engine..."
            )
            self._watch_readiness(manual)
            controller = self._require_controller()
            controller.replace_runtime(manual)
            self.bridge.replace_capture_service(manual.capture_service)
            self.bridge.apply_live_state()
            if self._previous_state in {DesktopState.RUNNING, DesktopState.PAUSED}:
                controller.start()
            if self._previous_state is DesktopState.PAUSED:
                controller.pause()
            self.refresh_tray()

        try:
            _dispatch_sync(self._dispatcher, restore, cancel=self._closing)
        except DesktopShuttingDown:
            # The desktop is closing; the activated resource is already safe
            # and the rebuilt runtime would be torn down immediately anyway.
            self._diagnostics.add("Update completed while the desktop was closing.")


def run_desktop(
    runtime_config: str | Path | None = None,
    *,
    app_config: str | Path | None = None,
    roi_size: tuple[int, int] | None = None,
    trace_sink: RuntimeTraceSink | None = None,
    diagnostics: DiagnosticLog | None = None,
    runtime_resolver: Callable[[Path | None], Path] | None = None,
) -> int:
    """Open the Hanly interface, then prepare its runtime behind it.

    ``runtime_config`` is the operator's explicit choice and skips automatic
    provisioning; ``None`` means discover-or-provision in the background while
    the window is already on screen.

    ``trace_sink`` is the developer instrumentation seam: the benchmark harness
    passes a sink that draws events on screen. ``None`` is the shipped path and
    costs nothing, the tracing wrappers are not constructed at all.

    ``diagnostics`` is the session log the entry point already opened. Passing
    ``None`` keeps everything in memory, which is what a test wants.
    """

    diagnostics = diagnostics if diagnostics is not None else DiagnosticLog()
    timeline = StartupTimeline(diagnostics)
    resolve = runtime_resolver if runtime_resolver is not None else resolve_runtime_config
    explicit_runtime = (
        None if runtime_config is None else Path(runtime_config).expanduser().resolve()
    )

    # One bootstrap owns the OCR-before-Qt ordering, the WebEngine attribute,
    # and the shared application's program name.
    try:
        with timeline.phase("qt bootstrap"):
            application = cast(QtApplication, ensure_qt_application(diagnostics=diagnostics))

            from .qt_popup import QtResultDispatcher
    except (ImportError, ControlCenterUnavailable) as error:
        raise DesktopApplicationError(
            "Hanly Desktop requires the hanly-app runtime extra with Qt6"
        ) from error

    # A source launch preloads OCR inside the bootstrap above; a packaged one
    # did it in the runtime hook, where the CLI has already claimed it.
    record_preload_timing(timeline)

    dispatcher = QtResultDispatcher()
    status = RuntimeStatusPublisher(dispatcher)
    settings = _load_settings(
        Path(app_config).expanduser().resolve()
        if app_config is not None
        else default_app_config_path(),
        diagnostics,
    )

    session = _DesktopSession(
        settings,
        diagnostics=diagnostics,
        status=status,
        dispatcher=dispatcher,
        roi_size=roi_size,
        trace_sink=trace_sink,
        timeline=timeline,
    )
    status.subscribe(_readiness_milestone(timeline))
    desktop = DesktopApplication(
        application,
        session,
        session.tray,
        session.host,
        diagnostics=diagnostics,
    )
    session.attach(desktop)

    startup = StartupCoordinator(
        # The prepared runtime carries the timeline, so provider construction
        # reports what it cost from the worker thread that pays for it.
        lambda explicit: replace(load_runtime(resolve(explicit)), timeline=timeline),
        session.activate,
        status=status,
        dispatcher=dispatcher,
        diagnostics=diagnostics,
        release=session.release,
        timeline=timeline,
    )
    session.bridge.set_retry(startup.retry)
    desktop.attach_startup(startup)

    signal_bridge = QtSignalBridge(
        application,
        desktop.shutdown,
        on_error=lambda error: diagnostics.report("SIGINT shutdown", error),
    )
    desktop.attach_signal_bridge(signal_bridge)

    startup.start(explicit_runtime)
    return desktop.run()


def _readiness_milestone(timeline: StartupTimeline) -> Callable[[RuntimeStatus], None]:
    """Record when the runtime first became usable, once per session."""

    reported = False

    def observe(status: RuntimeStatus) -> None:
        nonlocal reported

        if status.ready and not reported:
            reported = True
            timeline.reached("runtime ready")

    return observe


def _load_settings(path: Path, diagnostics: DiagnosticLog) -> ConfigManager:
    """Read preferences, falling back to defaults rather than refusing to open.

    A corrupt or unreadable ``config.json`` is exactly when the user needs the
    interface most: they cannot fix a setting from a window that never appears.
    """

    settings = ConfigManager(path)
    try:
        settings.load()
    except ConfigError as error:
        diagnostics.report("Preferences", error)
    return settings


def _report_initialization_failure(
    status: RuntimeStatusPublisher,
    diagnostics: DiagnosticLog,
    error: BaseException,
) -> None:
    """Surface a provider-construction failure without inventing a lookup.

    The worker never produced a result, so there is nothing to present as one:
    the cause goes to the durable log and to the runtime status the interface
    already shows.
    """

    diagnostics.report("Lookup providers", error)
    status.fail("lookup providers", error)


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


def report_startup_error(error: BaseException, *, log_path: Path | None = None) -> None:
    """Report startup failure even when the packaged app has no console."""

    message = f"Hanly Desktop: {error}"
    if log_path is not None:
        message = f"{message}\n\nDiagnostics log: {log_path}"
    print(message, file=sys.stderr, flush=True)
    if not getattr(sys, "frozen", False):
        return

    _show_native_startup_error(message)


def _can_show_native_dialog(environment: Mapping[str, str] | None = None) -> bool:
    """Whether asking Qt for a window here could work at all.

    Qt does not raise when it cannot load a platform plugin: it aborts the
    process, which no ``except`` can catch. A session with no display is
    therefore answered before Qt is asked rather than after it has killed the
    process that was reporting an error.
    """

    if sys.platform in {"win32", "darwin"}:
        return True
    env = os.environ if environment is None else environment
    return any(env.get(name) for name in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"))


def _show_native_startup_error(message: str) -> None:
    """Show a minimal native error dialog for a windowed packaged launch."""

    if not _can_show_native_dialog():
        # stderr already carries the message; a dialog is not possible here.
        return

    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox

        # The shared bootstrap keeps the OCR-before-Qt ordering on the failure
        # path too, and gives Chromium the program name it needs even here.
        application = ensure_qt_application()
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
    "RUNTIME_CONFIG_NAME",
    "default_app_config_path",
    "default_log_directory",
    "default_runtime_config_path",
    "discover_runtime_config",
    "load_update_service",
    "report_startup_error",
    "resolve_runtime_config",
    "run_desktop",
]
