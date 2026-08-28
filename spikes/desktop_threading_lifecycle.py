"""Directly executable Windows evidence spike for desktop threading/lifecycle risks.

This is deliberately a small observation harness, not a desktop subsystem or a
pytest test.  Optional desktop libraries are imported only when already present;
the harness never installs packages, opens a window, or downloads anything.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import platform
import queue
import sys
import threading
from typing import Any

WAIT_SECONDS = 2.0


def _module_probe(
    module_name: str, distribution_name: str | None = None
) -> dict[str, Any]:
    """Report local import availability without treating optional absence as failure."""

    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError) as error:
        return {
            "available": False,
            "version": None,
            "detail": f"find_spec failed: {type(error).__name__}: {error}",
        }
    if spec is None:
        return {
            "available": False,
            "version": None,
            "detail": "not installed in the current interpreter",
        }

    try:
        module = importlib.import_module(module_name)
    except Exception as error:
        # Optional GUI imports can fail for local backend reasons.
        return {
            "available": False,
            "version": None,
            "detail": f"found but import failed: {type(error).__name__}: {error}",
        }
    distribution = distribution_name or module_name
    version: str | None
    try:
        version = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        version = getattr(module, "__version__", None)
    version_text = version or "version not reported"
    return {
        "available": True,
        "version": version,
        "detail": f"importable ({version_text})",
    }


def _threading_probe() -> dict[str, Any]:
    """Exercise cross-thread delivery, completion, and acknowledged shutdown.

    Every recorded observation must be capable of being False.  Comparing an
    identifier captured on the main thread against the main thread proves
    nothing, so the worker reports its own identity and the shutdown worker
    reports whether it actually observed the stop request.
    """

    main_ident = threading.get_ident()
    events: queue.Queue[tuple[str, int]] = queue.Queue()
    worker_started = threading.Event()

    def completion_worker() -> None:
        worker_started.set()
        # The worker publishes its own identity; the main thread can then show
        # the result genuinely crossed a thread boundary.
        events.put(("worker-complete", threading.get_ident()))

    worker = threading.Thread(
        target=completion_worker,
        name="spike-completion-worker",
        daemon=False,
    )
    worker.start()
    started = worker_started.wait(WAIT_SECONDS)

    callback_event: str | None = None
    worker_ident: int | None = None
    if started:
        try:
            callback_event, worker_ident = events.get(timeout=WAIT_SECONDS)
        except queue.Empty:
            callback_event = None
    worker.join(WAIT_SECONDS)

    # Shutdown: the worker records whether the request was observed or whether
    # its wait simply timed out.  Without this, a worker that never saw the
    # request is indistinguishable from one that honoured it.
    shutdown_requested = threading.Event()
    shutdown_started = threading.Event()
    shutdown_observation: dict[str, Any] = {}

    def shutdown_worker() -> None:
        shutdown_started.set()
        observed = shutdown_requested.wait(WAIT_SECONDS)
        shutdown_observation["request_observed"] = observed
        shutdown_observation["worker_ident"] = threading.get_ident()

    lifecycle_worker = threading.Thread(
        target=shutdown_worker,
        name="spike-shutdown-worker",
        daemon=False,
    )
    lifecycle_worker.start()
    lifecycle_started = shutdown_started.wait(WAIT_SECONDS)
    shutdown_requested.set()
    lifecycle_worker.join(WAIT_SECONDS)

    return {
        "main_thread_ident": main_ident,
        "main_thread_name": threading.main_thread().name,
        "queue_pump_callback_event": callback_event,
        "worker_reported_ident": worker_ident,
        # Real: false if the result never arrived or never crossed a boundary.
        "result_crossed_thread_boundary": (
            worker_ident is not None and worker_ident != main_ident
        ),
        "result_consumed_on_main_thread": callback_event is not None,
        "completion_worker_stopped": not worker.is_alive(),
        "shutdown_worker_started": lifecycle_started,
        # Real: false if the worker's wait timed out instead of being released.
        "shutdown_request_acknowledged_by_worker": bool(
            shutdown_observation.get("request_observed")
        ),
        "shutdown_worker_ident": shutdown_observation.get("worker_ident"),
        "shutdown_join_completed": not lifecycle_worker.is_alive(),
    }


def _pyqt6_probe() -> dict[str, Any]:
    """Exercise the real GUI layer: QApplication, a frameless always-on-top
    widget, tray availability, and a worker-thread result delivered to the UI
    thread.

    A ``QCoreApplication`` has no widget layer, so it cannot answer the
    question this spike exists for.  The widget is created but never shown, so
    nothing appears on screen.
    """

    module = _module_probe("PyQt6", "PyQt6")
    if not module["available"]:
        return {
            "status": "UNAVAILABLE",
            "version": None,
            "detail": module["detail"],
            "gui_application_created": False,
            "ui_loop_exercised": False,
            "tray_available": False,
        }

    try:
        from PyQt6 import QtCore, QtWidgets

        existing = QtWidgets.QApplication.instance()
        app = existing or QtWidgets.QApplication([])
        main_ident = threading.get_ident()
        observations: dict[str, Any] = {}

        class _Receiver(QtCore.QObject):
            """Main-thread receiver for a worker-produced result."""

            delivered = QtCore.pyqtSignal(int)

            def on_delivered(self, worker_ident: int) -> None:
                observations["ui_slot_ident"] = threading.get_ident()
                observations["emitting_worker_ident"] = worker_ident
                app.quit()

        receiver = _Receiver()
        receiver.delivered.connect(receiver.on_delivered)

        # A frameless, always-on-top, translucent widget is the V1 popup shape.
        # Constructing it proves the widget layer works; it is never shown.
        popup = QtWidgets.QWidget(
            None,
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool,
        )
        popup.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        popup.resize(320, 160)
        popup_created = not popup.isVisible()

        def emit_from_worker() -> None:
            receiver.delivered.emit(threading.get_ident())

        worker = threading.Thread(
            target=emit_from_worker, name="spike-ui-delivery-worker", daemon=False
        )
        QtCore.QTimer.singleShot(0, worker.start)
        # Never let a locally broken Qt backend hang this evidence script.
        QtCore.QTimer.singleShot(int(WAIT_SECONDS * 1000), app.quit)
        loop_exit_code = app.exec()
        worker.join(WAIT_SECONDS)

        tray_available = QtWidgets.QSystemTrayIcon.isSystemTrayAvailable()
        ui_slot_ident = observations.get("ui_slot_ident")
        worker_ident = observations.get("emitting_worker_ident")
        ui_loop_exercised = ui_slot_ident is not None
        return {
            "status": "AVAILABLE" if ui_loop_exercised else "PRESENT_BUT_UNEXERCISED",
            "version": module["version"],
            "detail": (
                "QApplication (widget layer) created; bounded event loop completed"
                if ui_loop_exercised
                else "QApplication created; fallback timeout ended the event loop"
            ),
            "reused_existing_application": existing is not None,
            "gui_application_created": True,
            "frameless_popup_widget_constructed": popup_created,
            "ui_loop_exercised": ui_loop_exercised,
            "ui_loop_exit_code": loop_exit_code,
            # Real: false if the slot did not run on the main thread.
            "worker_result_delivered_on_ui_thread": ui_slot_ident == main_ident,
            # Real: false if the signal did not originate off the UI thread.
            "delivery_crossed_thread_boundary": (
                worker_ident is not None and worker_ident != main_ident
            ),
            "tray_available": tray_available,
            "tray_observation": (
                "QSystemTrayIcon.isSystemTrayAvailable() reported a usable tray; "
                "no tray icon was created"
                if tray_available
                else "no system tray reported available in this session"
            ),
        }
    except Exception as error:
        # Record a local Qt/backend limitation; do not install or fix it.
        return {
            "status": "PRESENT_BUT_UNEXERCISED",
            "version": module["version"],
            "detail": (
                "PyQt6 found but bounded GUI probe failed: "
                f"{type(error).__name__}: {error}"
            ),
            "gui_application_created": False,
            "ui_loop_exercised": False,
            "tray_available": False,
        }


def _display_probe() -> dict[str, Any]:
    """Record DPI awareness and monitor geometry.

    Cursor-to-ROI capture depends on whether the process is per-monitor DPI
    aware and on how monitors are laid out, including negative origins for a
    secondary monitor placed left of the primary one.
    """

    result: dict[str, Any] = {}
    try:
        import ctypes

        awareness = ctypes.c_int(-1)
        try:
            ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(awareness))
            result["process_dpi_awareness_raw"] = awareness.value
            result["process_dpi_awareness"] = {
                0: "UNAWARE",
                1: "SYSTEM_DPI_AWARE",
                2: "PER_MONITOR_DPI_AWARE",
            }.get(awareness.value, "UNKNOWN")
        except Exception as error:
            result["process_dpi_awareness"] = f"UNAVAILABLE: {type(error).__name__}"
        try:
            result["system_dpi"] = ctypes.windll.user32.GetDpiForSystem()
        except Exception as error:
            result["system_dpi"] = f"UNAVAILABLE: {type(error).__name__}"
    except Exception as error:
        result["ctypes_probe"] = f"UNAVAILABLE: {type(error).__name__}: {error}"

    module = _module_probe("PyQt6", "PyQt6")
    if not module["available"]:
        result["screens"] = "UNEXERCISED (PyQt6 unavailable)"
        return result

    try:
        from PyQt6 import QtWidgets

        existing = QtWidgets.QApplication.instance()
        app = (
            existing
            if isinstance(existing, QtWidgets.QApplication)
            else QtWidgets.QApplication([])
        )
        screens = []
        negative_origin = False
        scaled = False
        for screen in app.screens():
            geometry = screen.geometry()
            ratio = screen.devicePixelRatio()
            if geometry.x() < 0 or geometry.y() < 0:
                negative_origin = True
            if ratio != 1.0:
                scaled = True
            screens.append(
                {
                    "name": screen.name(),
                    "geometry": (
                        geometry.x(),
                        geometry.y(),
                        geometry.width(),
                        geometry.height(),
                    ),
                    "device_pixel_ratio": ratio,
                    "logical_dpi": round(screen.logicalDotsPerInch(), 2),
                }
            )
        result["screen_count"] = len(screens)
        result["screens"] = screens
        result["any_negative_origin"] = negative_origin
        result["any_display_scaling"] = scaled
        result["capture_constraint"] = (
            "cursor and ROI coordinates must be reconciled with device pixel "
            "ratio and virtual-desktop origin before capture"
        )
    except Exception as error:
        result["screens"] = f"UNEXERCISED: {type(error).__name__}: {error}"
    return result


def _webview2_runtime_probe() -> dict[str, Any]:
    """Detect the Evergreen WebView2 Runtime that pywebview's edgechromium
    backend requires on Windows.  This is a deployment prerequisite, not a
    Python dependency."""

    client_key = (
        r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
        r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    )
    try:
        import winreg
    except ImportError as error:
        return {"available": False, "detail": f"winreg unavailable: {error}"}

    for hive, label in (
        (winreg.HKEY_LOCAL_MACHINE, "HKLM"),
        (winreg.HKEY_CURRENT_USER, "HKCU"),
    ):
        try:
            with winreg.OpenKey(hive, client_key) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
        except OSError:
            continue
        if version:
            return {
                "available": True,
                "version": version,
                "source": label,
                "detail": (
                    "Evergreen WebView2 Runtime present; distribution must still "
                    "guarantee it on target machines"
                ),
            }
    return {
        "available": False,
        "version": None,
        "detail": (
            "Evergreen WebView2 Runtime not detected; the Control Center backend "
            "would require the runtime or a bootstrapper on such a machine"
        ),
    }


def _pywebview_probe() -> dict[str, Any]:
    """Probe pywebview's local backend selection without creating a window."""

    module = _module_probe("webview", "pywebview")
    if not module["available"]:
        return {
            "status": "UNAVAILABLE",
            "version": None,
            "detail": module["detail"],
            "backend_initialized": False,
            "window_or_web_loop_exercised": False,
            "observation": "module unavailable; no window or web loop created",
        }

    try:
        from webview.guilib import initialize

        backend = initialize()
        backend_name = getattr(backend, "__name__", "backend name not reported")
        renderer = getattr(backend, "renderer", "renderer not reported")
        return {
            "status": "AVAILABLE",
            "version": module["version"],
            "detail": module["detail"],
            "backend_initialized": True,
            "backend_module": backend_name,
            "renderer": renderer,
            "window_or_web_loop_exercised": False,
            "observation": (
                f"initialize() selected {backend_name} ({renderer}); "
                "no window or web loop created"
            ),
        }
    except Exception as error:
        return {
            "status": "PRESENT_BUT_BACKEND_UNAVAILABLE",
            "version": module["version"],
            "detail": (
                "module importable but backend initialization failed: "
                f"{type(error).__name__}: {error}"
            ),
            "backend_initialized": False,
            "window_or_web_loop_exercised": False,
            "observation": "no window or web loop created",
        }


def _pystray_probe() -> dict[str, Any]:
    """Probe pystray import and class availability without creating an icon."""

    module = _module_probe("pystray", "pystray")
    if not module["available"]:
        return {
            "status": "UNAVAILABLE",
            "version": None,
            "detail": module["detail"],
            "icon_class_available": False,
            "tray_loop_exercised": False,
            "observation": "module unavailable; no tray icon or loop created",
        }

    try:
        pystray = importlib.import_module("pystray")
        icon_class_available = hasattr(pystray, "Icon")
        return {
            "status": (
                "AVAILABLE" if icon_class_available else "PRESENT_BUT_UNEXERCISED"
            ),
            "version": module["version"],
            "detail": module["detail"],
            "icon_class_available": icon_class_available,
            "tray_loop_exercised": False,
            "observation": (
                "pystray.Icon class available; no tray icon or loop created"
                if icon_class_available
                else (
                    "pystray imported but Icon class unavailable; "
                    "no tray icon or loop created"
                )
            ),
        }
    except Exception as error:
        return {
            "status": "PRESENT_BUT_UNEXERCISED",
            "version": module["version"],
            "detail": (
                "module found but class probe failed: "
                f"{type(error).__name__}: {error}"
            ),
            "icon_class_available": False,
            "tray_loop_exercised": False,
            "observation": "no tray icon or loop created",
        }


def _capability_probes() -> dict[str, Any]:
    return {
        "PyQt6": _pyqt6_probe(),
        "pywebview": _pywebview_probe(),
        "webview2_runtime": _webview2_runtime_probe(),
        "pystray": _pystray_probe(),
    }


def _print_mapping(prefix: str, values: dict[str, Any]) -> None:
    for key, value in values.items():
        print(f"{prefix}.{key}={value}")


def main() -> int:
    print("desktop threading/lifecycle spike")
    print(f"platform={sys.platform}")
    print(f"windows_version={platform.platform()}")
    print(f"python={platform.python_version()}")

    if sys.platform != "win32":
        print("windows_evidence=UNEXERCISED (this harness exercises Windows only)")
        print("macos_linux=UNEXERCISED")
        return 0

    threading_evidence = _threading_probe()
    _print_mapping("threading", threading_evidence)
    print(
        "main_thread_ui_loop.observation="
        "a worker-produced result crossed a thread boundary and was consumed on "
        "the process main thread; this is evidence, not a production UI architecture"
    )

    capabilities = _capability_probes()
    for name, values in capabilities.items():
        _print_mapping(f"capability.{name}", values)

    display_evidence = _display_probe()
    _print_mapping("display", display_evidence)

    required_observations = (
        threading_evidence["result_crossed_thread_boundary"],
        threading_evidence["result_consumed_on_main_thread"],
        threading_evidence["completion_worker_stopped"],
        threading_evidence["shutdown_worker_started"],
        threading_evidence["shutdown_request_acknowledged_by_worker"],
        threading_evidence["shutdown_join_completed"],
    )
    status = "PASS" if all(required_observations) else "FAIL"
    print("macos_linux=UNEXERCISED")
    print(f"overall={status}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
