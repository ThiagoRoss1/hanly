"""Desktop global-hotkey registration and action delivery.

The service deliberately stops at normalized desktop actions.  The caller owns
the orchestration that decides what a lookup, capture start/resume, or pause
means; this module only translates a global key combination into that action.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum
from threading import RLock
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, TypeAlias

if TYPE_CHECKING:
    # Type-only: the concrete listener is still imported lazily at call time.
    from pynput import keyboard


class HotkeyAction(str, Enum):
    """Actions that a desktop hotkey may request from application orchestration."""

    LOOKUP = "lookup"
    START_CAPTURE = "start_capture"
    PAUSE_CAPTURE = "pause_capture"


class HotkeyError(ValueError):
    """Base error for invalid or conflicting hotkey configuration."""


class DuplicateHotkeyError(HotkeyError):
    """Raised when two actions are assigned the same key combination."""


class HotkeyListener(Protocol):
    """Minimal listener lifecycle hidden behind the desktop hotkey seam."""

    def start(self) -> None:
        """Start receiving global key events."""

    def stop(self) -> None:
        """Stop receiving global key events."""


HotkeyHandler: TypeAlias = Callable[[HotkeyAction], None]
HotkeyDispatcher: TypeAlias = Callable[[Callable[[], None]], None]
HotkeyListenerFactory: TypeAlias = Callable[
    [Mapping[str, Callable[[], None]]], HotkeyListener
]
HotkeyBindings: TypeAlias = Mapping[HotkeyAction | str, str]


DEFAULT_HOTKEYS: Mapping[HotkeyAction | str, str] = MappingProxyType(
    {
        HotkeyAction.LOOKUP: "ctrl+shift+space",
        HotkeyAction.START_CAPTURE: "ctrl+shift+f9",
        HotkeyAction.PAUSE_CAPTURE: "ctrl+shift+f10",
    }
)

_ACTION_ALIASES = {
    "lookup": HotkeyAction.LOOKUP,
    "start_capture": HotkeyAction.START_CAPTURE,
    "pause_capture": HotkeyAction.PAUSE_CAPTURE,
}

_MODIFIER_ALIASES = {
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "shift": "<shift>",
    "alt": "<alt>",
    "option": "<alt>",
    "cmd": "<cmd>",
    "command": "<cmd>",
    "win": "<cmd>",
    "windows": "<cmd>",
    "super": "<cmd>",
}

_SPECIAL_KEY_ALIASES = {
    "space": "<space>",
    "enter": "<enter>",
    "return": "<enter>",
    "esc": "<esc>",
    "escape": "<esc>",
    "tab": "<tab>",
    "backspace": "<backspace>",
    "delete": "<delete>",
    "insert": "<insert>",
    "home": "<home>",
    "end": "<end>",
    "pageup": "<page_up>",
    "pagedown": "<page_down>",
    "up": "<up>",
    "down": "<down>",
    "left": "<left>",
    "right": "<right>",
}


def _inline_dispatch(callback: Callable[[], None]) -> None:
    callback()


def _coerce_action(value: HotkeyAction | str) -> HotkeyAction:
    if isinstance(value, HotkeyAction):
        return value
    if not isinstance(value, str):
        raise HotkeyError("hotkey actions must be HotkeyAction values or strings")

    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return _ACTION_ALIASES[normalized]
    except KeyError as error:
        raise HotkeyError(f"unsupported hotkey action: {value!r}") from error


def _canonical_key_part(part: str) -> str:
    token = part.strip().lower()
    if not token:
        raise HotkeyError("hotkey combinations cannot contain empty key parts")

    if token.startswith("<") or token.endswith(">"):
        if not (token.startswith("<") and token.endswith(">")):
            raise HotkeyError(f"invalid hotkey key part: {part!r}")
        token = token[1:-1].strip()
        if not token:
            raise HotkeyError(f"invalid hotkey key part: {part!r}")

    if token in _MODIFIER_ALIASES:
        return _MODIFIER_ALIASES[token]
    if token in _SPECIAL_KEY_ALIASES:
        return _SPECIAL_KEY_ALIASES[token]
    if len(token) == 1:
        return token

    # Pynput names non-character keys (function keys, media keys, and virtual
    # key codes) in angle brackets. Keeping the conversion here also lets the
    # existing human-friendly ``ctrl+shift+space`` setting remain valid.
    return f"<{token}>"


def _canonical_hotkey(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HotkeyError("hotkey bindings must be non-empty strings")

    parts = [_canonical_key_part(part) for part in value.split("+")]
    if len(set(parts)) != len(parts):
        raise HotkeyError(f"hotkey binding contains a duplicate key: {value!r}")

    # A combination is unordered. Canonical sorting catches the same binding
    # written as ``shift+ctrl+k`` and ``ctrl+shift+k`` while keeping the usual
    # modifier-first spelling expected by pynput and configuration files.
    modifier_order = {"<ctrl>": 0, "<shift>": 1, "<alt>": 2, "<cmd>": 3}
    return "+".join(sorted(parts, key=lambda part: (modifier_order.get(part, 4), part)))


def _normalize_bindings(bindings: HotkeyBindings) -> dict[HotkeyAction, str]:
    if not isinstance(bindings, Mapping):
        raise HotkeyError("hotkey bindings must be a mapping")
    if not bindings:
        raise HotkeyError("at least one hotkey binding is required")

    normalized: dict[HotkeyAction, str] = {}
    by_binding: dict[str, HotkeyAction] = {}
    for raw_action, raw_binding in bindings.items():
        action = _coerce_action(raw_action)
        if action in normalized:
            raise HotkeyError(f"hotkey action is registered more than once: {action.value}")
        binding = _canonical_hotkey(raw_binding)
        previous = by_binding.get(binding)
        if previous is not None:
            raise DuplicateHotkeyError(
                f"hotkey {raw_binding!r} is already bound to {previous.value}"
            )
        normalized[action] = binding
        by_binding[binding] = action

    return normalized


def _pynput_listener_factory(
    callbacks: Mapping[str, Callable[[], None]],
) -> HotkeyListener:
    """Construct the concrete listener lazily so importing the app stays cheap."""

    try:
        from pynput import keyboard as pynput_keyboard
    except ImportError as error:
        raise RuntimeError("pynput is required to register global hotkeys") from error

    return _PynputListener(pynput_keyboard.GlobalHotKeys(dict(callbacks)))


class _PynputListener:
    """Contain the external pynput listener object behind :class:`HotkeyListener`."""

    def __init__(self, listener: keyboard.GlobalHotKeys) -> None:
        self._listener = listener

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()

    def join(self, timeout: float | None = 1.0) -> None:
        self._listener.join(timeout)


def _stop_listener(listener: HotkeyListener) -> None:
    """Stop and boundedly join a listener when its backend provides ``join``."""

    listener.stop()

    join = getattr(listener, "join", None)
    if not callable(join):
        return

    try:
        join(timeout=1.0)
    except TypeError:
        # Small test doubles and third-party wrappers sometimes expose join()
        # without the standard thread timeout parameter.
        try:
            join()
        except RuntimeError:
            pass
    except RuntimeError:
        # pynput's listener is itself a Thread and runs hotkey callbacks on it,
        # so a handler that shuts the service down would be joining itself.
        # Stopping is already requested; waiting here is neither possible nor
        # needed.
        pass


class HotkeyService:
    """Register global hotkeys and deliver normalized actions safely.

    ``dispatcher`` must post and return without waiting. It exists so a
    pynput listener thread need not run application/UI orchestration directly.
    The default dispatcher is inline, which does run the handler on the
    listener thread; desktop composition is expected to supply a real UI
    dispatcher.
    """

    def __init__(
        self,
        on_action: HotkeyHandler,
        *,
        bindings: HotkeyBindings | None = None,
        dispatcher: HotkeyDispatcher | None = None,
        listener_factory: HotkeyListenerFactory | None = None,
    ) -> None:
        if not callable(on_action):
            raise TypeError("on_action must be callable")
        if dispatcher is not None and not callable(dispatcher):
            raise TypeError("dispatcher must be callable")
        if listener_factory is not None and not callable(listener_factory):
            raise TypeError("listener_factory must be callable")

        configured = DEFAULT_HOTKEYS if bindings is None else bindings
        self._bindings = _normalize_bindings(configured)
        self._on_action = on_action
        self._dispatcher = dispatcher or _inline_dispatch
        self._listener_factory = listener_factory or _pynput_listener_factory
        self._lock = RLock()
        self._listener: HotkeyListener | None = None
        self._registered = False
        self._shutdown = False

    @property
    def registered(self) -> bool:
        """Whether this service currently owns an active listener."""

        with self._lock:
            return self._registered

    @property
    def bindings(self) -> Mapping[HotkeyAction, str]:
        """Return the normalized, human-independent bindings."""

        with self._lock:
            return MappingProxyType(dict(self._bindings))

    def register(self) -> None:
        """Start one listener, rolling back completely if startup fails."""

        listener: HotkeyListener | None = None
        try:
            # Hold the lifecycle lock through start so unregister cannot stop a
            # listener in the small window between ownership and thread start.
            with self._lock:
                if self._shutdown:
                    raise RuntimeError("hotkey service has been shut down")
                if self._registered:
                    return

                callbacks = {
                    binding: (lambda action=action: self._trigger(action))
                    for action, binding in self._bindings.items()
                }
                listener = self._listener_factory(callbacks)
                if not callable(getattr(listener, "start", None)):
                    raise TypeError("hotkey listener must provide start()")
                if not callable(getattr(listener, "stop", None)):
                    raise TypeError("hotkey listener must provide stop()")
                self._listener = listener
                self._registered = True
                listener.start()
        except Exception:
            with self._lock:
                self._listener = None
                self._registered = False
            if listener is not None:
                try:
                    _stop_listener(listener)
                except Exception:
                    pass
            raise

    def unregister(self) -> None:
        """Stop the listener; repeated calls are safe and leave clean state."""

        with self._lock:
            listener = self._listener
            self._listener = None
            self._registered = False
        if listener is not None:
            _stop_listener(listener)

    def shutdown(self) -> None:
        """Unregister once and permanently close this service."""

        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
        self.unregister()

    def _trigger(self, action: HotkeyAction) -> None:
        with self._lock:
            if not self._registered or self._shutdown:
                return
            dispatcher = self._dispatcher

        def deliver() -> None:
            # Re-check currency under the lock, then release it before calling
            # application code: holding it across the handler would block any
            # other thread trying to unregister or shut the service down.
            with self._lock:
                if not self._registered or self._shutdown:
                    return
                handler = self._on_action
            handler(action)

        dispatcher(deliver)


__all__ = [
    "DEFAULT_HOTKEYS",
    "DuplicateHotkeyError",
    "HotkeyAction",
    "HotkeyBindings",
    "HotkeyDispatcher",
    "HotkeyError",
    "HotkeyHandler",
    "HotkeyListener",
    "HotkeyListenerFactory",
    "HotkeyService",
]
