from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from hanly_app.desktop_controller import DesktopState
from hanly_app.tray import (
    TrayBackend,
    TrayIconFactory,
    TrayService,
    TrayState,
    TrayStatus,
    normalize_status,
)


@dataclass
class _Item:
    label: str
    action: Callable[..., None]
    enabled: object = True


class _Menu:
    def __init__(self, *items: _Item) -> None:
        self.items = items


class _Backend:
    MenuItem = _Item
    Menu = _Menu


class _Icon:
    def __init__(self, _name: str, _image: object, title: str, menu: object) -> None:
        self.title = title
        self.menu: object = menu
        self.detached = 0
        self.stopped = 0
        self.refreshed = 0

    def run_detached(self) -> None:
        self.detached += 1

    def stop(self) -> None:
        self.stopped += 1

    def update_menu(self) -> None:
        self.refreshed += 1

    @property
    def items(self) -> tuple[_Item, ...]:
        assert isinstance(self.menu, _Menu)
        return self.menu.items


def _service(
    status: list[DesktopState],
    posted: list[Callable[[], None]],
    events: list[str],
) -> tuple[TrayService, _Icon]:
    icons: list[_Icon] = []

    def factory(name: str, image: object, title: str, menu: object) -> _Icon:
        assert isinstance(menu, _Menu)
        icon = _Icon(name, image, title, menu)
        icons.append(icon)
        return icon

    service = TrayService(
        lambda: status[0],
        dispatcher=posted.append,
        on_start=lambda: events.append("start"),
        on_resume=lambda: events.append("resume"),
        on_pause=lambda: events.append("pause"),
        on_open_control_center=lambda: events.append("control_center"),
        on_quit=lambda: events.append("quit"),
        backend=cast(TrayBackend, _Backend()),
        icon_factory=cast(TrayIconFactory, factory),
        icon_image=object(),
    )
    service.start()
    return service, icons[0]


def test_normalize_status_maps_every_desktop_state() -> None:
    assert normalize_status(DesktopState.PAUSED) == TrayStatus(TrayState.PAUSED, "Paused")
    assert normalize_status(DesktopState.NEW) == TrayStatus(TrayState.NEW, "Not started")
    assert normalize_status(DesktopState.RUNNING) == TrayStatus(TrayState.RUNNING, "Running")
    assert normalize_status(DesktopState.SHUTDOWN) == TrayStatus(
        TrayState.SHUTDOWN, "Shut down"
    )


def test_tray_callbacks_are_dispatched_and_start_is_idempotent() -> None:
    status: list[DesktopState] = [DesktopState.NEW]
    posted: list[Callable[[], None]] = []
    events: list[str] = []
    service, icon = _service(status, posted, events)

    assert service.started is True
    assert icon.detached == 1
    service.start()
    assert icon.detached == 1

    start_item = icon.items[1]
    start_item.action(icon, start_item)
    assert events == []
    assert len(posted) == 1
    posted.pop()()
    assert events == ["start"]


def test_tray_pause_resume_open_and_quit_use_current_status() -> None:
    status: list[DesktopState] = [DesktopState.RUNNING]
    posted: list[Callable[[], None]] = []
    events: list[str] = []
    service, icon = _service(status, posted, events)

    icon.items[2].action(icon, icon.items[2])
    icon.items[3].action(icon, icon.items[3])
    icon.items[4].action(icon, icon.items[4])
    assert events == []
    assert len(posted) == 3
    for callback in posted:
        callback()
    assert events == ["pause", "control_center", "quit"]

    status[0] = DesktopState.PAUSED
    icon.items[1].action(icon, icon.items[1])
    assert len(posted) == 4
    posted[-1]()
    assert events[-1] == "resume"

    service.shutdown()
    service.shutdown()
    assert icon.stopped == 1


def test_refresh_rebuilds_title_and_menu_without_restarting_icon() -> None:
    status: list[DesktopState] = [DesktopState.NEW]
    posted: list[Callable[[], None]] = []
    service, icon = _service(status, posted, [])

    status[0] = DesktopState.RUNNING
    service.refresh()

    assert icon.title == "Hanly — Running"
    assert icon.items[0].label == "Status: Running"
    assert icon.refreshed == 1
