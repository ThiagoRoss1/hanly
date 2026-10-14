"""Native image windows for Lab-owned, pixel-only fixtures and diagnostics."""

from __future__ import annotations

import ctypes
import importlib
import io
import os
import queue
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from PIL import Image


@dataclass(frozen=True)
class Point:
    """A point in the fixture's logical desktop coordinate space."""

    x: float
    y: float


@dataclass(frozen=True)
class Rect:
    """A rectangle with an exclusive right and bottom edge."""

    x: float
    y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    def contains(self, point: Point) -> bool:
        return self.x <= point.x < self.right and self.y <= point.y < self.bottom

    def inset(self, left: float, top: float, right: float, bottom: float) -> Rect:
        return Rect(
            self.x + left,
            self.y + top,
            max(0.0, self.width - left - right),
            max(0.0, self.height - top - bottom),
        )

    def expand(self, left: float, top: float, right: float, bottom: float) -> Rect:
        return Rect(
            self.x - left,
            self.y - top,
            self.width + left + right,
            self.height + top + bottom,
        )


@dataclass(frozen=True)
class DesktopGeometry:
    """The window-system bounds and pointer-coordinate transform for one desktop."""

    bounds: Rect
    pointer_origin: tuple[float, float]
    pointer_scale: float
    display_scale: float
    primary: Rect

    def to_pointer(self, point: Point) -> tuple[int, int]:
        return (
            round(self.pointer_origin[0] + point.x * self.pointer_scale),
            round(self.pointer_origin[1] + point.y * self.pointer_scale),
        )

    def from_pointer(self, point: tuple[float, float]) -> Point:
        return Point(
            (point[0] - self.pointer_origin[0]) / self.pointer_scale,
            (point[1] - self.pointer_origin[1]) / self.pointer_scale,
        )

    def to_window(self, rect: Rect) -> Rect:
        return Rect(
            self.bounds.x + rect.x,
            self.bounds.y + rect.y,
            rect.width,
            rect.height,
        )


class ImageWindow(Protocol):
    """An opaque, optionally topmost native window that shows only raster pixels."""

    def set_image(self, image: Image.Image) -> None: ...

    def set_bounds(self, bounds: Rect) -> None: ...

    def show(self) -> None: ...

    def hide(self) -> None: ...

    def close(self) -> None: ...


class UIHost(Protocol):
    """The event loop and image-window factory for the current operating system."""

    geometry: DesktopGeometry

    def create_window(
        self, bounds: Rect, *, topmost: bool = True, ignore_mouse: bool = True
    ) -> ImageWindow: ...

    def call_after(self, callback: Callable[[], None]) -> None: ...

    def call_later(self, delay_ms: int, callback: Callable[[], None]) -> None: ...

    def close(self) -> None: ...

    def run(
        self,
        poll: Callable[[], int | None],
        *,
        interval_ms: int,
        duration_s: float | None,
        on_duration: Callable[[], None],
    ) -> int: ...


def create_ui_host() -> UIHost:
    """Create the one native Lab window backend supported by this platform."""

    if sys.platform == "darwin":
        return _MacUIHost()
    if sys.platform in {"win32", "linux"}:
        try:
            return _TkUIHost()
        except (ImportError, ModuleNotFoundError) as error:
            raise RuntimeError(
                "Lab pages and HUDs need a Python build with Tk support on Windows/Linux. "
                "Install the platform's Tk development package and rebuild Python."
            ) from error
    raise RuntimeError(f"Lab image windows are unsupported on {sys.platform}")


class _MacUIHost:
    def __init__(self) -> None:
        try:
            import AppKit
            from Foundation import NSMakeRect
        except ImportError as error:
            raise RuntimeError(
                "Lab pages and HUDs need the hanly-app runtime extra on macOS for PyObjC"
            ) from error
        try:
            app_helper = importlib.import_module("PyObjCTools.AppHelper")
        except ImportError as error:
            raise RuntimeError(
                "Lab pages and HUDs need the hanly-app runtime extra on macOS for PyObjC"
            ) from error

        self._appkit = AppKit
        self._main_thread_id = threading.get_ident()
        self._make_rect = NSMakeRect
        self._helper = app_helper
        self._app = AppKit.NSApplication.sharedApplication()
        self._app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        screens = list(AppKit.NSScreen.screens())
        if not screens:
            raise RuntimeError("no screen is available for a Lab fixture")

        primary_screen = screens[0]
        primary_frame = primary_screen.frame()
        primary_top = primary_frame.origin.y + primary_frame.size.height
        self._primary_origin = (primary_frame.origin.x, primary_frame.origin.y)
        self._primary_top = primary_top
        logical: list[tuple[Rect, Any, float]] = []
        for screen in screens:
            frame = screen.frame()
            scale = float(screen.backingScaleFactor())
            rect = Rect(
                frame.origin.x - primary_frame.origin.x,
                primary_top - (frame.origin.y + frame.size.height),
                frame.size.width,
                frame.size.height,
            )
            logical.append((rect, frame, scale))

        left = min(rect.left for rect, _frame, _scale in logical)
        top = min(rect.top for rect, _frame, _scale in logical)
        right = max(rect.right for rect, _frame, _scale in logical)
        bottom = max(rect.bottom for rect, _frame, _scale in logical)
        scales = {scale for _rect, _frame, scale in logical}
        if len(scales) > 1:
            raise RuntimeError(
                "Lab full-desktop fixtures require all connected displays to use the same "
                "backing scale; disconnect or match the display scaling before a tour"
            )
        primary = logical[0][0]
        self.geometry = DesktopGeometry(
            bounds=Rect(left, top, right - left, bottom - top),
            pointer_origin=(left, top),
            pointer_scale=1.0,
            display_scale=max(scale for _rect, _frame, scale in logical),
            primary=primary,
        )

    def create_window(
        self, bounds: Rect, *, topmost: bool = True, ignore_mouse: bool = True
    ) -> ImageWindow:
        return _MacImageWindow(self, bounds, topmost=topmost, ignore_mouse=ignore_mouse)

    def call_after(self, callback: Callable[[], None]) -> None:
        if threading.get_ident() == self._main_thread_id:
            callback()
        else:
            self._helper.callAfter(callback)

    def call_later(self, delay_ms: int, callback: Callable[[], None]) -> None:
        self._helper.callLater(delay_ms / 1000, callback)

    def run(
        self,
        poll: Callable[[], int | None],
        *,
        interval_ms: int,
        duration_s: float | None,
        on_duration: Callable[[], None],
    ) -> int:
        result = 1

        def tick() -> None:
            nonlocal result
            value = poll()
            if value is not None:
                result = value
                self._helper.stopEventLoop()
                return
            self.call_later(interval_ms, tick)

        def duration() -> None:
            on_duration()

        self.call_later(interval_ms, tick)
        if duration_s is not None:
            self.call_later(max(1, int(duration_s * 1000)), duration)
        # AppHelper's application loop terminates Python when stopped, bypassing
        # the session's report, window and process cleanup. Its run-loop variant
        # returns to the owner after the same scheduled callbacks are drained.
        self._app.finishLaunching()
        self._helper.runConsoleEventLoop(maxTimeout=interval_ms / 1000)
        return result

    def _native_frame(self, bounds: Rect) -> Any:
        return self._make_rect(
            self._primary_origin[0] + bounds.x,
            self._primary_top - bounds.bottom,
            bounds.width,
            bounds.height,
        )

    def close(self) -> None:
        return


class _MacImageWindow:
    def __init__(
        self, host: _MacUIHost, bounds: Rect, *, topmost: bool, ignore_mouse: bool
    ) -> None:
        self._host = host
        self._bounds = bounds
        self._window = None
        self._image_view = None

        def create() -> None:
            appkit = host._appkit
            style = appkit.NSWindowStyleMaskBorderless
            self._window = appkit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                host._native_frame(bounds), style, appkit.NSBackingStoreBuffered, False
            )
            self._window.setReleasedWhenClosed_(False)
            self._window.setOpaque_(True)
            self._window.setBackgroundColor_(appkit.NSColor.blackColor())
            self._window.setIgnoresMouseEvents_(ignore_mouse)
            self._window.setHidesOnDeactivate_(False)
            if topmost:
                self._window.setLevel_(appkit.NSFloatingWindowLevel)
            self._window.setCollectionBehavior_(
                appkit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | appkit.NSWindowCollectionBehaviorStationary
            )
            self._image_view = appkit.NSImageView.alloc().initWithFrame_(
                appkit.NSMakeRect(0, 0, bounds.width, bounds.height)
            )
            self._image_view.setImageScaling_(appkit.NSImageScaleAxesIndependently)
            self._window.setContentView_(self._image_view)

        host.call_after(create)
        _wait_for(lambda: self._window is not None, "could not create the Lab image window")

    def set_image(self, image: Image.Image) -> None:
        window = self._window
        image_view = self._image_view
        assert window is not None and image_view is not None
        data = io.BytesIO()
        image.convert("RGB").save(data, format="PNG")
        payload = data.getvalue()

        def apply() -> None:
            ns_data = self._host._appkit.NSData.dataWithBytes_length_(payload, len(payload))
            native = self._host._appkit.NSImage.alloc().initWithData_(ns_data)
            native.setSize_(self._host._appkit.NSMakeSize(self._bounds.width, self._bounds.height))
            image_view.setImage_(native)
            window.orderFrontRegardless()

        _dispatch_sync(self._host.call_after, apply, "could not update the Lab image window")

    def show(self) -> None:
        window = self._window
        assert window is not None
        _dispatch_sync(
            self._host.call_after,
            window.orderFrontRegardless,
            "could not show the Lab image window",
        )

    def set_bounds(self, bounds: Rect) -> None:
        self._bounds = bounds
        window = self._window
        image_view = self._image_view
        assert window is not None and image_view is not None

        def move() -> None:
            window.setFrame_display_(self._host._native_frame(bounds), True)
            image_view.setFrame_(self._host._appkit.NSMakeRect(0, 0, bounds.width, bounds.height))

        _dispatch_sync(self._host.call_after, move, "could not move the Lab image window")

    def hide(self) -> None:
        window = self._window
        assert window is not None
        _dispatch_sync(
            self._host.call_after,
            lambda: window.orderOut_(None),
            "could not hide the Lab image window",
        )

    def close(self) -> None:
        window = self._window
        assert window is not None
        _dispatch_sync(self._host.call_after, window.close, "could not close the Lab image window")


class _TkUIHost:
    def __init__(self) -> None:
        self._main_thread_id = threading.get_ident()
        if sys.platform == "win32":
            _enable_windows_dpi_awareness()
        self._tk = __import__("tkinter")
        from PIL import ImageTk

        self._image_tk = ImageTk
        self._commands: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._root = self._tk.Tk()
        self._root.withdraw()
        self._root.update_idletasks()

        try:
            import mss

            with mss.mss() as capture:
                monitor = capture.monitors[0]
        except Exception as error:
            self._root.destroy()
            raise RuntimeError("Lab needs mss to read the desktop bounds") from error

        virtual_x = int(self._root.winfo_vrootx())
        virtual_y = int(self._root.winfo_vrooty())
        virtual_width = int(self._root.winfo_vrootwidth() or self._root.winfo_screenwidth())
        virtual_height = int(self._root.winfo_vrootheight() or self._root.winfo_screenheight())
        scale_x = float(monitor["width"]) / max(1, virtual_width)
        scale_y = float(monitor["height"]) / max(1, virtual_height)
        if abs(scale_x - scale_y) > 0.02:
            self._root.destroy()
            raise RuntimeError(
                "Lab cannot map pointer coordinates on a desktop with nonuniform scaling"
            )
        self._scale = (scale_x + scale_y) / 2
        primary = Rect(virtual_x, virtual_y, virtual_width, virtual_height)
        self.geometry = DesktopGeometry(
            bounds=primary,
            pointer_origin=(float(monitor["left"]), float(monitor["top"])),
            pointer_scale=self._scale,
            display_scale=self._scale,
            primary=primary,
        )
        self._windows: list[_TkImageWindow] = []
        self._running = False
        self._root.after(16, self._drain_commands)

    def create_window(
        self, bounds: Rect, *, topmost: bool = True, ignore_mouse: bool = True
    ) -> ImageWindow:
        window = _TkImageWindow(self, bounds, topmost=topmost, ignore_mouse=ignore_mouse)
        self._windows.append(window)
        return window

    def call_after(self, callback: Callable[[], None]) -> None:
        if threading.get_ident() == self._main_thread_id:
            callback()
        else:
            self._commands.put(callback)

    def call_later(self, delay_ms: int, callback: Callable[[], None]) -> None:
        self.call_after(lambda: self._root.after(delay_ms, callback))

    def run(
        self,
        poll: Callable[[], int | None],
        *,
        interval_ms: int,
        duration_s: float | None,
        on_duration: Callable[[], None],
    ) -> int:
        result = 1

        def tick() -> None:
            nonlocal result
            value = poll()
            if value is not None:
                result = value
                self._root.quit()
                return
            self._root.after(interval_ms, tick)

        self._root.after(interval_ms, tick)
        if duration_s is not None:
            self._root.after(max(1, int(duration_s * 1000)), on_duration)
        self._running = True
        try:
            self._root.mainloop()
        finally:
            self._running = False
        return result

    def close(self) -> None:
        self.call_after(self._root.destroy)

    def _drain_commands(self) -> None:
        if not self._running and not self._windows:
            return
        while True:
            try:
                callback = self._commands.get_nowait()
            except queue.Empty:
                break
            callback()
        self._root.after(16, self._drain_commands)


class _TkImageWindow:
    def __init__(self, host: _TkUIHost, bounds: Rect, *, topmost: bool, ignore_mouse: bool) -> None:
        self._host = host
        self._bounds = bounds
        self._topmost = topmost
        self._ignore_mouse = ignore_mouse
        self._window: Any = None
        self._canvas: Any = None
        self._image: Any = None
        self._closed = False
        host.call_after(self._create)
        _wait_for(lambda: self._window is not None, "could not create the Lab image window")

    def set_image(self, image: Image.Image) -> None:
        owned = image.copy()
        logical_width = max(1, round(self._bounds.width))
        logical_height = max(1, round(self._bounds.height))
        if owned.size != (logical_width, logical_height):
            owned = owned.resize((logical_width, logical_height), Image.Resampling.LANCZOS)
        complete = threading.Event()
        failure: list[BaseException] = []

        def apply() -> None:
            try:
                self._image = self._host._image_tk.PhotoImage(owned, master=self._window)
                self._canvas.configure(width=owned.width, height=owned.height)
                self._canvas.delete("all")
                self._canvas.create_image(0, 0, image=self._image, anchor="nw")
                self._window.deiconify()
                if self._topmost:
                    self._window.attributes("-topmost", True)
            except BaseException as error:
                failure.append(error)
            finally:
                complete.set()

        self._host.call_after(apply)
        _wait_for(complete.is_set, "could not update the Lab image window")
        if failure:
            raise RuntimeError("could not update the Lab image window") from failure[0]

    def show(self) -> None:
        _dispatch_sync(
            self._host.call_after, self._window.deiconify, "could not show the Lab image window"
        )

    def set_bounds(self, bounds: Rect) -> None:
        self._bounds = bounds

        def move() -> None:
            self._window.geometry(
                f"{round(bounds.width)}x{round(bounds.height)}"
                f"{round(bounds.x):+d}{round(bounds.y):+d}"
            )

        _dispatch_sync(self._host.call_after, move, "could not move the Lab image window")

    def hide(self) -> None:
        _dispatch_sync(
            self._host.call_after, self._window.withdraw, "could not hide the Lab image window"
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _dispatch_sync(
            self._host.call_after, self._window.destroy, "could not close the Lab image window"
        )

    def _create(self) -> None:
        window = self._host._tk.Toplevel(self._host._root)
        window.overrideredirect(True)
        window.geometry(
            f"{round(self._bounds.width)}x{round(self._bounds.height)}"
            f"{round(self._bounds.x):+d}{round(self._bounds.y):+d}"
        )
        window.configure(background="black", borderwidth=0, highlightthickness=0)
        if self._topmost:
            window.attributes("-topmost", True)
        canvas = self._host._tk.Canvas(
            window,
            width=round(self._bounds.width),
            height=round(self._bounds.height),
            background="black",
            borderwidth=0,
            highlightthickness=0,
        )
        canvas.pack(fill="both", expand=True)
        self._window = window
        self._canvas = canvas
        if self._ignore_mouse:
            _tk_ignore_mouse(window, self._host._tk, self._bounds)


def _tk_ignore_mouse(window: Any, tkinter: Any, bounds: Rect) -> None:
    """Make an opaque fixture pass pointer input through on X11 and Windows."""

    if sys.platform == "win32":
        window.update_idletasks()
        hwnd = int(window.winfo_id())
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            raise RuntimeError("Lab could not access Windows window styles")
        hwnd = int(windll.user32.GetAncestor(hwnd, 2) or hwnd)
        get_long = windll.user32.GetWindowLongPtrW
        set_long = windll.user32.SetWindowLongPtrW
        style = get_long(hwnd, -20)
        set_long(hwnd, -20, style | 0x00000020 | 0x00080000)
        if not windll.user32.SetLayeredWindowAttributes(hwnd, 0, 255, 0x00000002):
            raise RuntimeError("Lab could not enable opaque pointer-transparent fixtures")
        return

    if sys.platform != "linux":
        raise RuntimeError("Tk pointer pass-through is unavailable on this platform")

    import ctypes
    import ctypes.util

    x11_name = ctypes.util.find_library("X11")
    xext_name = ctypes.util.find_library("Xext")
    if not x11_name or not xext_name:
        raise RuntimeError("Lab needs X11 Shape support for pointer-transparent fixtures")
    x11 = ctypes.CDLL(x11_name)
    xext = ctypes.CDLL(xext_name)
    display = x11.XOpenDisplay(os.environ.get("DISPLAY", "").encode() or None)
    if not display:
        raise RuntimeError("Lab cannot open the X11 display for pointer-transparent fixtures")
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xext.XShapeCombineRectangles.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    display_handle = int(window.winfo_id())
    # ShapeInput with an empty rectangle list gives the window no hit-test area.
    xext.XShapeCombineRectangles(display, display_handle, 2, 0, 0, None, 0, 0, 0)
    x11.XFlush(display)
    x11.XCloseDisplay(display)


def _enable_windows_dpi_awareness() -> None:
    """Keep Tk, screenshots, pointer coordinates and the fixture in one DPI space."""

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        raise RuntimeError("Lab could not access the Windows DPI APIs")
    try:
        result = windll.shcore.SetProcessDpiAwareness(2)
    except AttributeError:
        if not windll.user32.SetProcessDPIAware():
            raise RuntimeError("Lab could not enable per-monitor DPI awareness")
        return
    if result not in (0, 0x80070005):
        raise RuntimeError(f"Lab could not enable per-monitor DPI awareness ({result:#x})")


def _wait_for(predicate: Callable[[], bool], message: str, timeout: float = 5.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise RuntimeError(message)
        time.sleep(0.005)


def _dispatch_sync(
    dispatch: Callable[[Callable[[], None]], None],
    callback: Callable[[], None],
    message: str,
) -> None:
    complete = threading.Event()
    failure: list[BaseException] = []

    def apply() -> None:
        try:
            callback()
        except BaseException as error:
            failure.append(error)
        finally:
            complete.set()

    dispatch(apply)
    _wait_for(complete.is_set, message)
    if failure:
        raise RuntimeError(message) from failure[0]


__all__ = ["DesktopGeometry", "ImageWindow", "Point", "Rect", "UIHost", "create_ui_host"]
