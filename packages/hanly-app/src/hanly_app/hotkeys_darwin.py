"""macOS global hotkeys through Carbon's ``RegisterEventHotKey``.

pynput's keyboard listener asks for the input-source list off the main queue,
which macOS 26 aborts instead of raising. Carbon needs no privacy grant and
delivers physical-key combinations on the Qt-owned main run loop.

Both edges are installed, so a held combination is a real hold here. Carbon
reports a hot key as released when its non-modifier key goes up: letting a
modifier go first while the primary key stays down does not end the hold. That
was measured on this backend, and the alternatives -- a global ``NSEvent``
monitor, which needs an Accessibility grant this backend deliberately does not
ask for, or polling the modifier state -- both cost more than the case is
worth.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from collections.abc import Mapping
from itertools import count
from threading import RLock

from .hotkeys import HotkeyEdge, HotkeyEdgeHandler, HotkeyError, HotkeyListener

#: Carbon modifier bits, which are not the Cocoa or Quartz ones.
_MODIFIER_MASKS = {
    "<cmd>": 0x0100,
    "<shift>": 0x0200,
    "<alt>": 0x0800,
    "<ctrl>": 0x1000,
}

#: ``kVK_*`` virtual key codes. They identify a position on the keyboard, so
#: they stay valid when the active input source changes.
_VIRTUAL_KEY_CODES = {
    "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3, "g": 5, "h": 4,
    "i": 34, "j": 38, "k": 40, "l": 37, "m": 46, "n": 45, "o": 31, "p": 35,
    "q": 12, "r": 15, "s": 1, "t": 17, "u": 32, "v": 9, "w": 13, "x": 7,
    "y": 16, "z": 6,
    "0": 29, "1": 18, "2": 19, "3": 20, "4": 21,
    "5": 23, "6": 22, "7": 26, "8": 28, "9": 25,
    "-": 27, "=": 24, "[": 33, "]": 30, "\\": 42, ";": 41, "'": 39,
    ",": 43, ".": 47, "/": 44, "`": 50,
    "<space>": 49, "<enter>": 36, "<tab>": 48, "<backspace>": 51, "<esc>": 53,
    "<delete>": 117, "<home>": 115, "<end>": 119, "<page_up>": 116,
    "<page_down>": 121, "<left>": 123, "<right>": 124, "<down>": 125,
    "<up>": 126,
    # Apple keyboards spell the Insert position "Help"; a binding persisted on
    # Windows or Linux stays registrable here rather than failing at start.
    "<insert>": 114,
    "<f1>": 122, "<f2>": 120, "<f3>": 99, "<f4>": 118, "<f5>": 96, "<f6>": 97,
    "<f7>": 98, "<f8>": 100, "<f9>": 101, "<f10>": 109, "<f11>": 103,
    "<f12>": 111, "<f13>": 105, "<f14>": 107, "<f15>": 113, "<f16>": 106,
    "<f17>": 64, "<f18>": 79, "<f19>": 80, "<f20>": 90,
}

_NO_ERROR = 0
#: Returned so a combination this listener does not own reaches the next handler.
_EVENT_NOT_HANDLED = -9874
_HOT_KEY_EXISTS = -9878

_EVENT_CLASS_KEYBOARD = 0x6B657962  # 'keyb'
_EVENT_HOT_KEY_PRESSED = 5
_EVENT_HOT_KEY_RELEASED = 6
_EVENT_KINDS = (_EVENT_HOT_KEY_PRESSED, _EVENT_HOT_KEY_RELEASED)
_PARAM_DIRECT_OBJECT = 0x2D2D2D2D  # '----'
_TYPE_EVENT_HOT_KEY_ID = 0x686B6964  # 'hkid'
_HANLY_SIGNATURE = 0x686E6C79  # 'hnly'


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


_EventHandlerProc = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)

#: Hot key ids are unique for the whole process, not per listener: every
#: listener's handler sees every Hanly hot key, and must recognise its own.
_next_hotkey_id = count(1)
_carbon_lock = RLock()
_carbon: ctypes.CDLL | None = None


def carbon_binding(binding: str) -> tuple[int, int]:
    """Translate one canonical Hanly binding into ``(key code, modifiers)``."""

    key_code: int | None = None
    modifiers = 0
    for part in binding.split("+"):
        mask = _MODIFIER_MASKS.get(part)
        if mask is not None:
            modifiers |= mask
            continue
        if key_code is not None:
            raise HotkeyError(f"macOS hotkeys take one non-modifier key: {binding!r}")
        code = _VIRTUAL_KEY_CODES.get(part)
        if code is None:
            raise HotkeyError(f"macOS has no key for {part!r} in hotkey {binding!r}")
        key_code = code

    if key_code is None:
        raise HotkeyError(f"hotkey needs a non-modifier key: {binding!r}")
    return key_code, modifiers


def darwin_listener_factory(
    callbacks: Mapping[str, HotkeyEdgeHandler],
) -> HotkeyListener:
    """Build the macOS listener for already-canonical bindings."""

    return _CarbonHotkeyListener(callbacks)


def _load_carbon() -> ctypes.CDLL:
    """Load Carbon once and describe the five functions this backend calls."""

    global _carbon
    with _carbon_lock:
        if _carbon is not None:
            return _carbon

        path = ctypes.util.find_library("Carbon")
        if path is None:
            raise RuntimeError("macOS global hotkeys require the Carbon framework")
        carbon = ctypes.cdll.LoadLibrary(path)

        carbon.GetEventDispatcherTarget.restype = ctypes.c_void_p
        carbon.GetEventDispatcherTarget.argtypes = []
        carbon.InstallEventHandler.restype = ctypes.c_int32
        carbon.InstallEventHandler.argtypes = [
            ctypes.c_void_p,
            _EventHandlerProc,
            ctypes.c_uint32,
            ctypes.POINTER(_EventTypeSpec),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        carbon.RemoveEventHandler.restype = ctypes.c_int32
        carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]
        carbon.RegisterEventHotKey.restype = ctypes.c_int32
        carbon.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            _EventHotKeyID,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        carbon.UnregisterEventHotKey.restype = ctypes.c_int32
        carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        carbon.GetEventKind.restype = ctypes.c_uint32
        carbon.GetEventKind.argtypes = [ctypes.c_void_p]
        carbon.GetEventParameter.restype = ctypes.c_int32
        carbon.GetEventParameter.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        ]

        _carbon = carbon
        return carbon


def _registration_error(status: int, binding: str) -> RuntimeError:
    if status == _HOT_KEY_EXISTS:
        return RuntimeError(f"another application already uses the hotkey {binding}")
    return RuntimeError(f"macOS refused to register the hotkey {binding} (error {status})")


class _CarbonHotkeyListener:
    """One Carbon event handler and the hot keys registered alongside it.

    There is no listener thread: the window server delivers the combination to
    the main run loop, so ``join`` has nothing to wait for. Every combination is
    translated before anything is registered, so an unusable binding is an
    ordinary error rather than a half-registered listener.
    """

    def __init__(self, callbacks: Mapping[str, HotkeyEdgeHandler]) -> None:
        self._bindings = {
            binding: (carbon_binding(binding), callback)
            for binding, callback in callbacks.items()
        }
        self._lock = RLock()
        self._carbon: ctypes.CDLL | None = None
        self._handler_ref: ctypes.c_void_p | None = None
        # ctypes does not own the trampoline it hands to C, so the process
        # would call freed memory if this reference were dropped while the
        # handler is still installed.
        self._handler_proc = _EventHandlerProc(self._handle_event)
        self._hotkey_refs: dict[str, tuple[ctypes.c_void_p, int]] = {}
        self._callbacks: dict[int, HotkeyEdgeHandler] = {}
        # Carbon does not repeat a hot key press, but a duplicate down edge
        # would still latch a hold twice, so the state is tracked rather than
        # assumed.
        self._held: set[int] = set()

    def start(self) -> None:
        """Install the handler and register every combination, or nothing."""

        with self._lock:
            if self._handler_ref is not None:
                return
            carbon = _load_carbon()
            self._carbon = carbon
            try:
                self._install_handler(carbon)
                for binding, (combination, callback) in self._bindings.items():
                    self._register_one(carbon, binding, combination, callback)
            except Exception:
                self._teardown()
                raise

    def stop(self) -> None:
        """Release the hot keys and the handler; repeated calls are safe."""

        with self._lock:
            self._teardown()

    def join(self, timeout: float | None = None) -> None:
        """Satisfy the listener seam; this backend owns no thread."""

    def rebind(self, callbacks: Mapping[str, HotkeyEdgeHandler]) -> None:
        """Replace one active registration without installing a second handler."""

        bindings = {
            binding: (carbon_binding(binding), callback)
            for binding, callback in callbacks.items()
        }
        with self._lock:
            if self._handler_ref is None or self._carbon is None:
                self._bindings = bindings
                return

            removed = self._bindings.keys() - bindings.keys()
            added = bindings.keys() - self._bindings.keys()
            if len(removed) != 1 or len(added) != 1:
                raise RuntimeError("macOS hotkey rebind must replace exactly one binding")

            old_binding = next(iter(removed))
            new_binding = next(iter(added))
            old_combination, old_callback = self._bindings[old_binding]
            new_combination, new_callback = bindings[new_binding]
            carbon = self._carbon

            self._unregister_one(carbon, old_binding)
            try:
                self._register_one(
                    carbon, new_binding, new_combination, new_callback
                )
            except Exception:
                try:
                    self._register_one(
                        carbon, old_binding, old_combination, old_callback
                    )
                except Exception as rollback_error:
                    raise RuntimeError(
                        "macOS hotkey rebind failed and the previous binding "
                        "could not be restored"
                    ) from rollback_error
                raise

            for binding in self._bindings.keys() & bindings.keys():
                _reference, hotkey_id = self._hotkey_refs[binding]
                self._callbacks[hotkey_id] = bindings[binding][1]
            self._bindings = bindings

    def _install_handler(self, carbon: ctypes.CDLL) -> None:
        specs = (_EventTypeSpec * len(_EVENT_KINDS))(
            *(_EventTypeSpec(_EVENT_CLASS_KEYBOARD, kind) for kind in _EVENT_KINDS)
        )
        handler_ref = ctypes.c_void_p()
        status = carbon.InstallEventHandler(
            ctypes.c_void_p(carbon.GetEventDispatcherTarget()),
            self._handler_proc,
            len(_EVENT_KINDS),
            specs,
            None,
            ctypes.byref(handler_ref),
        )
        if status != _NO_ERROR:
            raise RuntimeError(
                f"macOS refused the global hotkey event handler (error {status})"
            )
        self._handler_ref = handler_ref

    def _register_one(
        self,
        carbon: ctypes.CDLL,
        binding: str,
        combination: tuple[int, int],
        callback: HotkeyEdgeHandler,
    ) -> None:
        key_code, modifiers = combination
        hotkey_id = next(_next_hotkey_id)
        reference = ctypes.c_void_p()
        status = carbon.RegisterEventHotKey(
            key_code,
            modifiers,
            _EventHotKeyID(_HANLY_SIGNATURE, hotkey_id),
            ctypes.c_void_p(carbon.GetEventDispatcherTarget()),
            0,
            ctypes.byref(reference),
        )
        if status != _NO_ERROR:
            raise _registration_error(status, binding)
        self._hotkey_refs[binding] = (reference, hotkey_id)
        self._callbacks[hotkey_id] = callback

    def _unregister_one(self, carbon: ctypes.CDLL, binding: str) -> None:
        reference, hotkey_id = self._hotkey_refs[binding]
        status = carbon.UnregisterEventHotKey(reference)
        if status != _NO_ERROR:
            raise RuntimeError(
                f"macOS refused to unregister the hotkey {binding} (error {status})"
            )
        del self._hotkey_refs[binding]
        self._callbacks.pop(hotkey_id, None)
        self._held.discard(hotkey_id)

    def _teardown(self) -> None:
        carbon = self._carbon
        handler_ref = self._handler_ref
        hotkey_refs = self._hotkey_refs.values()
        self._carbon = None
        self._handler_ref = None
        self._hotkey_refs = {}
        # Dropped before the hot keys are released, so a combination that
        # arrives while teardown is still running finds nothing left to run.
        self._callbacks = {}
        self._held = set()
        if carbon is None:
            return
        for reference, _hotkey_id in hotkey_refs:
            carbon.UnregisterEventHotKey(reference)
        if handler_ref is not None:
            carbon.RemoveEventHandler(handler_ref)

    def _handle_event(
        self,
        _call_ref: int | None,
        event: int | None,
        _user_data: int | None,
    ) -> int:
        """Run the callback for one hot key, on the main run loop.

        Carbon fixes the three-argument signature, so the two ignored ones have
        to stay: declining the event replaces the handler chain, and the user
        data is NULL because hot key ids already identify the callback.

        Called from C, where an exception has nowhere to go, so every failure
        ends as a declined event instead.
        """

        try:
            delivery = self._delivery_for(event)
        except Exception:
            return _EVENT_NOT_HANDLED
        if delivery is None:
            return _EVENT_NOT_HANDLED
        callback, edge = delivery
        try:
            callback(edge)
        except Exception:
            return _EVENT_NOT_HANDLED
        return _NO_ERROR

    def _delivery_for(
        self, event: int | None
    ) -> tuple[HotkeyEdgeHandler, HotkeyEdge] | None:
        """Resolve one Carbon event into this listener's callback and edge."""

        with self._lock:
            carbon = self._carbon
        if carbon is None or event is None:
            return None

        kind = carbon.GetEventKind(ctypes.c_void_p(event))
        if kind not in _EVENT_KINDS:
            return None

        hotkey_id = _EventHotKeyID()
        received = ctypes.c_uint32()
        status = carbon.GetEventParameter(
            ctypes.c_void_p(event),
            _PARAM_DIRECT_OBJECT,
            _TYPE_EVENT_HOT_KEY_ID,
            None,
            ctypes.sizeof(hotkey_id),
            ctypes.byref(received),
            ctypes.byref(hotkey_id),
        )
        if status != _NO_ERROR or hotkey_id.signature != _HANLY_SIGNATURE:
            return None

        down = kind == _EVENT_HOT_KEY_PRESSED
        with self._lock:
            callback = self._callbacks.get(hotkey_id.id)
            if callback is None:
                return None
            if down == (hotkey_id.id in self._held):
                # A second down for a chord already held, or an up for one that
                # was never seen going down: neither is an edge.
                return None
            if down:
                self._held.add(hotkey_id.id)
            else:
                self._held.discard(hotkey_id.id)
        return callback, HotkeyEdge.DOWN if down else HotkeyEdge.UP


__all__ = ["carbon_binding", "darwin_listener_factory"]
