"""A shortcut host double for the manual session.

The native root registers the combinations and reports each edge; this double
does the same for tests, delivering through the session's dispatcher only while
the runtime is registered.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from hanly_app.config import AppConfig
from hanly_app.hotkeys import HotkeyAction, HotkeyEdge, HotkeyHandler, canonical_hotkey

Dispatcher = Callable[[Callable[[], None]], None]


def _inline(callback: Callable[[], None]) -> None:
    callback()


class FakeHotkeys:
    """Hotkey factory and the single runtime it builds.

    ``config`` decides which combination maps to which action, as the host's
    registration would; ``dispatcher`` stands for the thread edges arrive on.
    """

    def __init__(
        self,
        *,
        config: AppConfig | None = None,
        dispatcher: Dispatcher | None = None,
        fail: str | None = None,
    ) -> None:
        config = config or AppConfig()
        self.combinations = {
            canonical_hotkey(binding): action
            for action, binding in (
                (HotkeyAction.PUSH_TO_HOVER, config.hotkey),
                (HotkeyAction.TOGGLE_HOVER, config.hover_hotkey),
                (HotkeyAction.TOGGLE_CAPTURE, config.capture_hotkey),
            )
            if binding.strip()
        }
        self.dispatcher = dispatcher or _inline
        self.started = 0
        self.shutdown_calls = 0
        self._fail = fail
        self._handler: HotkeyHandler | None = None
        self._registered = False

    def __call__(self, handler: HotkeyHandler) -> FakeHotkeys:
        self._handler = handler
        return self

    @property
    def bindings(self) -> Mapping[HotkeyAction, str]:
        if not self._registered:
            return {}
        return {action: binding for binding, action in self.combinations.items()}

    @property
    def registered(self) -> bool:
        return self._registered

    def register(self) -> None:
        if self._fail is not None:
            raise RuntimeError(self._fail)
        self.started += 1
        self._registered = True

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self._registered = False

    def press(self, binding: str, edge: HotkeyEdge = HotkeyEdge.DOWN) -> None:
        self.trigger(self.combinations[canonical_hotkey(binding)], edge)

    def release(self, binding: str) -> None:
        self.press(binding, HotkeyEdge.UP)

    def trigger(self, action: HotkeyAction, edge: HotkeyEdge = HotkeyEdge.DOWN) -> None:
        """Deliver one edge as the host would, or drop it once unregistered."""

        handler = self._handler
        if handler is None or not self._registered:
            return
        self.dispatcher(lambda: handler(action, edge))
