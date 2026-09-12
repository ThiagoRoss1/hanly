"""Desktop global-hotkey registration and action delivery.

The service deliberately stops at normalized desktop actions.  The caller owns
the orchestration that decides what a lookup, capture start/resume, or pause
means; this module only translates a global key combination into that action.
"""

from __future__ import annotations

import sys
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

    #: One capture and lookup at the cursor. Still reachable for a caller that
    #: binds it; the desktop no longer gives it a default shortcut, because the
    #: combination it used to own is now the hold.
    LOOKUP = "lookup"
    START_CAPTURE = "start_capture"
    PAUSE_CAPTURE = "pause_capture"
    #: Held, not tapped: hover follows the chord and stops when it is let go.
    PUSH_TO_HOVER = "push_to_hover"
    #: Mute and continue automatic hover, without touching capture or residency.
    TOGGLE_HOVER = "toggle_hover"
    #: Start and stop the capture session itself, which is what releases the
    #: lookup providers.
    TOGGLE_CAPTURE = "toggle_capture"


class HotkeyEdge(str, Enum):
    """Which half of a physical key press this delivery is.

    A hold needs both; a toggle acts on ``DOWN`` and ignores ``UP``. Backends
    that can only report activation deliver ``DOWN`` alone, which is why the
    hold actions are the only ones that read this.
    """

    DOWN = "down"
    UP = "up"


class HotkeyError(ValueError):
    """Base error for invalid or conflicting hotkey configuration."""


class DuplicateHotkeyError(HotkeyError):
    """Raised when two actions are assigned the same key combination."""


class HotkeyListener(Protocol):
    """The listener lifecycle hidden behind the desktop hotkey seam.

    ``join`` is part of the seam, not an optional extra: a backend that runs on
    its own thread must make shutdown bounded rather than fire and forget. A
    backend delivered on the main run loop has nothing to wait for and returns
    immediately.
    """

    def start(self) -> None:
        """Start receiving global key events."""

    def stop(self) -> None:
        """Stop receiving global key events."""

    def join(self, timeout: float | None = None) -> None:
        """Wait briefly for the listener thread to finish after ``stop``."""


HotkeyHandler: TypeAlias = Callable[[HotkeyAction, HotkeyEdge], None]
HotkeyDispatcher: TypeAlias = Callable[[Callable[[], None]], None]
#: A backend reports both edges of one combination through this callback.
HotkeyEdgeHandler: TypeAlias = Callable[[HotkeyEdge], None]
HotkeyListenerFactory: TypeAlias = Callable[
    [Mapping[str, HotkeyEdgeHandler]], HotkeyListener
]
HotkeyBindings: TypeAlias = Mapping[HotkeyAction | str, str]

#: The actions that follow a physical hold rather than a tap.
HELD_ACTIONS: frozenset[HotkeyAction] = frozenset({HotkeyAction.PUSH_TO_HOVER})


DEFAULT_HOTKEYS: Mapping[HotkeyAction | str, str] = MappingProxyType(
    {
        # Every action in this map has to be registrable alongside every other,
        # so these avoid one another. What the desktop actually registers is
        # the user's three preferences: the hold, the hover mute, and the
        # capture session. The one-shot lookup is bindable but unregistered,
        # because the combination it used to own is now the hold.
        HotkeyAction.LOOKUP: "ctrl+alt+space",
        HotkeyAction.START_CAPTURE: "ctrl+shift+f9",
        HotkeyAction.PAUSE_CAPTURE: "ctrl+shift+f10",
        HotkeyAction.PUSH_TO_HOVER: "ctrl+shift+space",
        HotkeyAction.TOGGLE_HOVER: "ctrl+shift+f11",
        HotkeyAction.TOGGLE_CAPTURE: "ctrl+shift+f12",
    }
)

#: Bounded wait for a stopped listener thread, so shutdown cannot hang.
_STOP_JOIN_SECONDS = 1.0

_ACTION_ALIASES = {
    "lookup": HotkeyAction.LOOKUP,
    "start_capture": HotkeyAction.START_CAPTURE,
    "pause_capture": HotkeyAction.PAUSE_CAPTURE,
    "push_to_hover": HotkeyAction.PUSH_TO_HOVER,
    "toggle_hover": HotkeyAction.TOGGLE_HOVER,
    "toggle_capture": HotkeyAction.TOGGLE_CAPTURE,
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


#: Where each modifier sits in the canonical spelling; anything else follows.
_MODIFIER_ORDER = {"<ctrl>": 0, "<shift>": 1, "<alt>": 2, "<cmd>": 3}


def _inline_dispatch(callback: Callable[[], None]) -> None:
    callback()


def _canonical_sort_key(part: str) -> tuple[int, str]:
    return (_MODIFIER_ORDER.get(part, len(_MODIFIER_ORDER)), part)


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
    # existing human-friendly ``ctrl+shift+space`` setting remain valid. Only
    # identifier-shaped names can be one, so punctuation is rejected instead of
    # being wrapped into a binding pynput could never register.
    if not token.replace("_", "").isalnum():
        raise HotkeyError(f"invalid hotkey key part: {part!r}")
    return f"<{token}>"


def canonical_hotkey(value: str) -> str:
    """Normalize a human-written combination, raising on anything unusable.

    Exposed so callers that persist a hotkey can reject a spelling this
    service could never register.
    """

    if not isinstance(value, str) or not value.strip():
        raise HotkeyError("hotkey bindings must be non-empty strings")

    parts = [_canonical_key_part(part) for part in value.split("+")]
    if len(set(parts)) != len(parts):
        raise HotkeyError(f"hotkey binding contains a duplicate key: {value!r}")

    # A combination is unordered. Canonical sorting catches the same binding
    # written as ``shift+ctrl+k`` and ``ctrl+shift+k`` while keeping the usual
    # modifier-first spelling expected by pynput and configuration files.
    return "+".join(sorted(parts, key=_canonical_sort_key))


def validate_binding(value: str) -> str:
    """Canonicalize a binding and check the running platform can register it.

    ``canonical_hotkey`` only proves the spelling is one this service
    understands. A combination can still be unusable on the machine in front of
    the user -- macOS has no key at that position, or the backend cannot express
    the modifier -- and finding that out when the user saves is much better than
    finding it out when the shortcut silently does nothing.
    """

    binding = canonical_hotkey(value)
    if sys.platform == "darwin":
        from .hotkeys_darwin import carbon_binding

        carbon_binding(binding)
    return binding


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
        binding = canonical_hotkey(raw_binding)
        previous = by_binding.get(binding)
        if previous is not None:
            raise DuplicateHotkeyError(
                f"hotkey {raw_binding!r} is already bound to {previous.value}"
            )
        normalized[action] = binding
        by_binding[binding] = action

    return normalized


def _default_listener_factory(
    callbacks: Mapping[str, HotkeyEdgeHandler],
) -> HotkeyListener:
    """Pick the backend the running operating system can actually use.

    pynput's macOS keyboard listener reads the keyboard layout from its own
    thread, which current macOS aborts the process for; see
    :mod:`hanly_app.hotkeys_darwin`. Every other platform keeps pynput.
    """

    if sys.platform == "darwin":
        from .hotkeys_darwin import darwin_listener_factory

        return darwin_listener_factory(callbacks)
    return _pynput_listener_factory(callbacks)


def _pynput_listener_factory(
    callbacks: Mapping[str, HotkeyEdgeHandler],
) -> HotkeyListener:
    """Construct the concrete listener lazily so importing the app stays cheap."""

    try:
        from pynput import keyboard as pynput_keyboard
    except ImportError as error:
        raise RuntimeError("pynput is required to register global hotkeys") from error

    return _PynputListener(pynput_keyboard, callbacks)


class _Chord:
    """The physical state of one combination, as both of its edges.

    pynput's own ``GlobalHotKeys`` reports activation and nothing else, which
    is enough for a tap and not enough for a hold: without the release edge
    hover would stay on after the user let the keys go.
    """

    def __init__(self, keys: frozenset[object], handler: HotkeyEdgeHandler) -> None:
        self._keys = keys
        self._handler = handler
        self._held: set[object] = set()
        self._active = False

    def press(self, key: object) -> None:
        if key not in self._keys:
            return
        self._held.add(key)
        # Already down means this is auto-repeat, which is not a new press.
        if self._active or self._held != self._keys:
            return
        self._active = True
        self._handler(HotkeyEdge.DOWN)

    def release(self, key: object) -> None:
        if key not in self._keys:
            return
        self._held.discard(key)
        self._end()

    def clear(self) -> None:
        """Drop held state, reporting the release the user never got to make."""

        self._held.clear()
        self._end()

    def _end(self) -> None:
        if not self._active:
            return
        self._active = False
        self._handler(HotkeyEdge.UP)


class _PynputListener:
    """Track each configured chord over pynput's raw key events.

    Raw events rather than ``GlobalHotKeys`` because the hold needs the release
    edge. Keys are canonicalized through the listener, which is how the same
    combination keeps working across layouts.
    """

    def __init__(
        self,
        keyboard_module: object,
        callbacks: Mapping[str, HotkeyEdgeHandler],
    ) -> None:
        hotkey = getattr(keyboard_module, "HotKey")
        self._chords = [
            _Chord(frozenset(hotkey.parse(binding)), handler)
            for binding, handler in callbacks.items()
        ]
        listener_factory = getattr(keyboard_module, "Listener")
        self._listener: keyboard.Listener = listener_factory(
            on_press=self._on_press, on_release=self._on_release
        )

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()
        # A chord held when observation stops would otherwise stay latched
        # until a release this listener will never see.
        for chord in self._chords:
            chord.clear()

    def join(self, timeout: float | None = None) -> None:
        self._listener.join(timeout)

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        canonical = self._listener.canonical(key)
        for chord in self._chords:
            chord.press(canonical)

    def _on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        canonical = self._listener.canonical(key)
        for chord in self._chords:
            chord.release(canonical)


def _stop_listener(listener: HotkeyListener) -> None:
    """Stop a listener and wait a bounded time for its thread to finish."""

    listener.stop()
    try:
        listener.join(_STOP_JOIN_SECONDS)
    except RuntimeError:
        # pynput's listener is itself a Thread and runs hotkey callbacks on it,
        # so a handler that shuts the service down would be joining itself.
        # Stopping is already requested; waiting here is neither possible nor
        # needed.
        pass


class HotkeyService:
    """Register global hotkeys and deliver normalized actions safely.

    ``dispatcher`` must post and return without waiting. It exists so whichever
    thread the backend delivers a combination on need not run application or UI
    orchestration directly. The default dispatcher is inline, which does run
    the handler on that thread; desktop composition is expected to supply a
    real UI dispatcher.
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
        self._listener_factory = listener_factory or _default_listener_factory
        self._lock = RLock()
        self._listener: HotkeyListener | None = None
        self._registered = False
        self._shutdown = False
        # Which listener owns the keyboard; a rebind replaces it, and events
        # from the previous one are no longer this service's.
        self._generation = 0

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

                candidate = self._generation + 1
                callbacks = self._callbacks(self._bindings, candidate)
                listener = self._listener_factory(callbacks)
                self._listener = listener
                self._registered = True
                self._generation = candidate
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

    def rebind(
        self,
        action: HotkeyAction | str,
        binding: str,
    ) -> None:
        """Replace one binding without interrupting an active service.

        Backends with an in-place rebind operation may use it when their native
        API makes duplicate registration impossible. Other backends start the
        replacement before stopping the previous listener. Either path restores
        or retains the previous binding when registration fails.
        """

        normalized_action = _coerce_action(action)
        normalized_binding = canonical_hotkey(binding)
        previous_listener: HotkeyListener | None = None

        with self._lock:
            if self._shutdown:
                raise RuntimeError("hotkey service has been shut down")
            configured_bindings: dict[HotkeyAction | str, str] = {
                configured_action: configured_binding
                for configured_action, configured_binding in self._bindings.items()
            }
            configured_bindings[normalized_action] = normalized_binding
            next_bindings = _normalize_bindings(configured_bindings)
            if next_bindings == self._bindings:
                return

            if not self._registered:
                self._bindings = next_bindings
                return

            candidate = self._generation + 1
            callbacks = self._callbacks(next_bindings, candidate)
            active_listener = self._listener
            if active_listener is None:
                raise RuntimeError("registered hotkey service has no listener")
            active_rebind = getattr(active_listener, "rebind", None)
            if callable(active_rebind):
                active_rebind(callbacks)
                self._generation = candidate
                self._bindings = next_bindings
                return

            listener = self._listener_factory(callbacks)
            try:
                listener.start()
            except Exception:
                try:
                    _stop_listener(listener)
                except Exception:
                    pass
                raise
            previous_listener = self._listener
            self._listener = listener
            self._generation = candidate
            self._bindings = next_bindings

        if previous_listener is not None:
            _stop_listener(previous_listener)

    def unbind(self, action: HotkeyAction | str) -> None:
        """Give up one action's combination, leaving the others registered.

        A migration that found no free position leaves an action unbound, and
        a user may clear one deliberately. Neither is a reason to stop
        listening for the shortcuts that do exist.
        """

        normalized = _coerce_action(action)
        previous_listener: HotkeyListener | None = None
        with self._lock:
            if self._shutdown or normalized not in self._bindings:
                return
            next_bindings = {
                configured: binding
                for configured, binding in self._bindings.items()
                if configured is not normalized
            }
            if not self._registered:
                self._bindings = next_bindings
                return
            if not next_bindings:
                # Nothing is left to listen for; the listener itself goes.
                previous_listener = self._listener
                self._listener = None
                self._registered = False
                self._generation += 1
                self._bindings = next_bindings
            else:
                candidate = self._generation + 1
                callbacks = self._callbacks(next_bindings, candidate)
                active_rebind = getattr(self._listener, "rebind", None)
                if callable(active_rebind):
                    active_rebind(callbacks)
                    self._generation = candidate
                    self._bindings = next_bindings
                    return

                listener = self._listener_factory(callbacks)
                try:
                    listener.start()
                except Exception:
                    try:
                        _stop_listener(listener)
                    except Exception:
                        pass
                    raise
                previous_listener = self._listener
                self._listener = listener
                self._generation = candidate
                self._bindings = next_bindings

        if previous_listener is not None:
            _stop_listener(previous_listener)

    def shutdown(self) -> None:
        """Unregister once and permanently close this service."""

        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
        self.unregister()

    def _callbacks(
        self,
        bindings: Mapping[HotkeyAction, str],
        generation: int,
    ) -> dict[str, HotkeyEdgeHandler]:
        """Bind each action to a handler that answers only for ``generation``.

        ``generation`` is the candidate a caller commits once its listener has
        started, never the current one: a start that fails must leave the
        listener that is still running current rather than silently stale.
        """

        def handler_for(action: HotkeyAction) -> HotkeyEdgeHandler:
            def handler(edge: HotkeyEdge) -> None:
                self._trigger(action, edge, generation)

            return handler

        return {
            binding: handler_for(action) for action, binding in bindings.items()
        }

    def _trigger(self, action: HotkeyAction, edge: HotkeyEdge, generation: int) -> None:
        """Deliver one edge, dropping a stale listener's late key events.

        A rebound or stopped listener can still have an event in flight, and a
        release from the chord the user no longer has must not reach the
        application as if it were the current one.
        """

        with self._lock:
            if not self._registered or self._shutdown:
                return
            if generation != self._generation:
                return
            dispatcher = self._dispatcher

        def deliver() -> None:
            # Re-check currency under the lock, then release it before calling
            # application code: holding it across the handler would block any
            # other thread trying to unregister or shut the service down.
            with self._lock:
                if not self._registered or self._shutdown:
                    return
                if generation != self._generation:
                    return
                handler = self._on_action
            handler(action, edge)

        dispatcher(deliver)


__all__ = [
    "DEFAULT_HOTKEYS",
    "HELD_ACTIONS",
    "DuplicateHotkeyError",
    "HotkeyAction",
    "HotkeyEdge",
    "HotkeyEdgeHandler",
    "HotkeyBindings",
    "HotkeyDispatcher",
    "HotkeyError",
    "HotkeyHandler",
    "HotkeyListener",
    "HotkeyListenerFactory",
    "HotkeyService",
    "canonical_hotkey",
    "validate_binding",
]
