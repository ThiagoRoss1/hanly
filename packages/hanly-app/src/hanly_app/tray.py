"""Small, UI-dispatched system-tray integration for Hanly Desktop.

``TrayService`` owns only the pystray adapter and its lifecycle. Application
orchestration stays in the composition root: menu actions are normalized into
callbacks supplied by the caller and are always posted through the injected
dispatcher before they run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Protocol, TypeAlias, cast

from .desktop_controller import DesktopState


class TrayState(str, Enum):
    """Application states represented by the tray menu."""

    NEW = "new"
    RUNNING = "running"
    PAUSED = "paused"
    SHUTDOWN = "shutdown"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TrayStatus:
    """Normalized status exposed to the tray and its menu."""

    state: TrayState
    label: str
    detail: str | None = None


TrayStatusProvider: TypeAlias = Callable[[], DesktopState]
TrayCallback: TypeAlias = Callable[[], None]
TrayDispatcher: TypeAlias = Callable[[TrayCallback], None]
TrayMenuAction: TypeAlias = Callable[..., None]


class TrayIcon(Protocol):
    """The pystray ``Icon`` surface :class:`TrayService` actually uses."""

    menu: object
    title: str

    def run_detached(self) -> None:
        """Start the backend loop without blocking the application thread."""

    def update_menu(self) -> None:
        """Re-read the menu after it has been replaced."""

    def stop(self) -> None:
        """Stop the backend loop."""


class TrayBackend(Protocol):
    """The pystray module members :class:`TrayService` actually uses."""

    Icon: Callable[..., TrayIcon]
    Menu: Callable[..., object]
    MenuItem: Callable[..., object]


TrayIconFactory: TypeAlias = Callable[[str, object, str, object], TrayIcon]


_STATE_LABELS = {
    DesktopState.NEW: (TrayState.NEW, "Not started"),
    DesktopState.RUNNING: (TrayState.RUNNING, "Running"),
    DesktopState.PAUSED: (TrayState.PAUSED, "Paused"),
    DesktopState.SHUTDOWN: (TrayState.SHUTDOWN, "Shut down"),
}


def normalize_status(state: DesktopState, detail: str | None = None) -> TrayStatus:
    """Convert a desktop lifecycle state into what the tray displays.

    Every caller is Hanly's own composition root, so the conversion is a plain
    lookup rather than a normalizer for arbitrary shapes.
    """

    tray_state, label = _STATE_LABELS.get(state, (TrayState.ERROR, "Error"))
    return TrayStatus(state=tray_state, label=label, detail=detail)


class TrayService:
    """Adapt pystray into a lifecycle-safe, UI-dispatched desktop service.

    The service never decides what starting, pausing, opening, or quitting
    means.  It selects the appropriate supplied callback from the normalized
    application state and posts that callback through ``dispatcher``.
    """

    def __init__(
        self,
        status_provider: TrayStatusProvider,
        *,
        dispatcher: TrayDispatcher,
        on_start: TrayCallback | None = None,
        on_resume: TrayCallback | None = None,
        on_pause: TrayCallback | None = None,
        on_open_control_center: TrayCallback | None = None,
        on_quit: TrayCallback | None = None,
        name: str = "hanly",
        title: str = "Hanly",
        icon_factory: TrayIconFactory | None = None,
        backend: TrayBackend | None = None,
        icon_image: object | None = None,
    ) -> None:
        if not callable(status_provider):
            raise TypeError("status_provider must be callable")
        if not callable(dispatcher):
            raise TypeError("dispatcher must be callable")
        if not name.strip() or not title.strip():
            raise ValueError("tray name and title must not be empty")

        self._status_provider = status_provider
        self._dispatcher = dispatcher
        self._on_start = on_start
        self._on_resume = on_resume
        self._on_pause = on_pause
        self._on_open_control_center = on_open_control_center
        self._on_quit = on_quit
        self._name = name
        self._title = title
        self._icon_factory = icon_factory
        self._backend: TrayBackend | None = backend
        self._icon_image = icon_image
        self._icon: TrayIcon | None = None
        self._started = False
        self._shutdown = False
        self._lock = RLock()

    @property
    def started(self) -> bool:
        """Whether the tray backend has been started."""

        with self._lock:
            return self._started

    @property
    def status(self) -> TrayStatus:
        """Return the current normalized application status."""

        return normalize_status(self._status_provider())

    def start(self) -> None:
        """Create and start the tray icon once."""

        with self._lock:
            if self._started or self._shutdown:
                return
            self._started = True

        try:
            backend = self._backend or _load_pystray()
            menu = self._build_menu(backend)
            image = self._icon_image if self._icon_image is not None else _default_image()
            factory = self._icon_factory or _backend_icon_factory(backend)
            icon = factory(self._name, image, self._window_title(), menu)
            icon.run_detached()
        except Exception:
            with self._lock:
                self._started = False
            raise

        with self._lock:
            self._icon = icon

    def refresh(self) -> None:
        """Refresh the displayed title/menu after application state changes."""

        with self._lock:
            icon = self._icon
            backend = self._backend
        if icon is None:
            return

        icon.menu = self._build_menu(backend or _load_pystray())
        icon.title = self._window_title()
        icon.update_menu()

    def shutdown(self) -> None:
        """Stop the tray backend at most once."""

        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._started = False
            icon = self._icon
            self._icon = None

        if icon is not None:
            icon.stop()

    def _build_menu(self, backend: TrayBackend) -> object:
        menu_item = backend.MenuItem
        menu_factory = backend.Menu
        status = self.status
        return menu_factory(
            menu_item(
                f"Status: {status.label}",
                lambda *_args: None,
                enabled=False,
            ),
            menu_item(
                "Start / Resume",
                self._start_or_resume,
                enabled=lambda _item: status.state in {TrayState.NEW, TrayState.PAUSED},
            ),
            menu_item(
                "Pause",
                self._pause,
                enabled=lambda _item: status.state is TrayState.RUNNING,
            ),
            menu_item("Open Control Center", self._open_control_center),
            menu_item("Quit", self._quit),
        )

    def _start_or_resume(self, *_args: object) -> None:
        status = self.status
        callback = self._on_start if status.state is TrayState.NEW else self._on_resume
        if callback is not None and status.state in {TrayState.NEW, TrayState.PAUSED}:
            self._dispatch(callback)

    def _pause(self, *_args: object) -> None:
        if self.status.state is TrayState.RUNNING and self._on_pause is not None:
            self._dispatch(self._on_pause)

    def _open_control_center(self, *_args: object) -> None:
        if self._on_open_control_center is not None:
            self._dispatch(self._on_open_control_center)

    def _quit(self, *_args: object) -> None:
        if self._on_quit is not None:
            self._dispatch(self._on_quit)

    def _dispatch(self, callback: TrayCallback) -> None:
        self._dispatcher(callback)

    def _window_title(self) -> str:
        return f"{self._title} — {self.status.label}"


def _load_pystray() -> TrayBackend:
    """Load pystray only when a real tray is requested.

    pystray ships no ``py.typed`` marker, so the import is untyped at this one
    external boundary; :class:`TrayBackend` describes what is used from it.
    """

    import pystray  # type: ignore[import-untyped]

    return cast(TrayBackend, pystray)


def _backend_icon_factory(backend: TrayBackend) -> TrayIconFactory:
    return backend.Icon


def _default_image() -> object:
    """Create a tiny neutral icon without importing Pillow at package load."""

    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (32, 32), (35, 39, 47, 255))
    ImageDraw.Draw(image).rectangle((7, 7, 24, 24), outline=(240, 240, 240, 255), width=2)
    return image


__all__ = [
    "TrayCallback",
    "TrayDispatcher",
    "TrayBackend",
    "TrayIcon",
    "TrayIconFactory",
    "TrayState",
    "TrayStatus",
    "TrayStatusProvider",
    "TrayService",
    "normalize_status",
]
