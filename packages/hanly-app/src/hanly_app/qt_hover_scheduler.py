"""Qt-timer debounce for the automatic-hover stability delay.

The default :mod:`threading` fallback creates one OS thread per scheduled
delay, which the hover path requests on every cursor movement. Inside a Qt
application the debounce belongs on the UI thread that already dispatches
those movements, so no thread is created and the stable callback needs no
further marshalling.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer

from .hover_controller import Cancellable, StabilityCallback


class QtHoverScheduler:
    """Schedule one pending hover delay on a reused single-shot ``QTimer``.

    ``HoverController`` keeps at most one delay pending and cancels the
    previous one before scheduling the next, so a single timer is enough.
    Instances must be created and called on the Qt UI thread.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)
        self._callback: StabilityCallback | None = None

    def __call__(self, delay_ms: float, callback: StabilityCallback) -> Cancellable:
        if not callable(callback):
            raise TypeError("callback must be callable")

        self._callback = callback
        # Restarting a running timer replaces its pending timeout.
        self._timer.start(max(0, int(delay_ms)))
        return _QtHoverHandle(self, callback)

    def _fire(self) -> None:
        callback, self._callback = self._callback, None
        if callback is not None:
            callback()

    def _cancel(self, callback: StabilityCallback) -> None:
        if self._callback is callback:
            self._callback = None
            self._timer.stop()


class _QtHoverHandle:
    """Cancel one scheduled delay without disturbing a newer one."""

    def __init__(self, scheduler: QtHoverScheduler, callback: StabilityCallback) -> None:
        self._scheduler = scheduler
        self._callback = callback

    def cancel(self) -> None:
        self._scheduler._cancel(self._callback)


__all__ = ["QtHoverScheduler"]
