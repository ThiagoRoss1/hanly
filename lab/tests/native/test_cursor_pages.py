"""Browser cursor fixtures use native cursors, not pointer-shaped page pixels."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from lab.grammar_inventory import GrammarInventory, GrammarTarget
from lab.grammar_pages import CURSORS, build_pages
from tests.hanly_fixtures.capabilities import require_display, require_modules

pytestmark = [pytest.mark.native, pytest.mark.skipif(sys.platform != "darwin", reason="AppKit")]


def test_webview_installs_real_native_magnifier_cursors(tmp_path: Path) -> None:
    require_display()
    require_modules("AppKit", "Foundation", "Quartz", "WebKit")
    kit = pytest.importorskip("AppKit")
    foundation = pytest.importorskip("Foundation")
    quartz = pytest.importorskip("Quartz")
    webkit = pytest.importorskip("WebKit")
    target = GrammarTarget("cursor-case", "particle", "에서", "학교에서 공부해요", "학교에서", 0,
                           "lab_authored")
    build_pages(tmp_path, GrammarInventory(targets=[target]), stress_cases=0)
    app = kit.NSApplication.sharedApplication()
    app.setActivationPolicy_(kit.NSApplicationActivationPolicyRegular)
    window = kit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        ((100, 120), (1000, 600)), kit.NSWindowStyleMaskTitled, kit.NSBackingStoreBuffered, False,
    )
    window.setReleasedWhenClosed_(False)
    window.setTitle_("Hanly owned native cursor fixture")
    view = webkit.WKWebView.alloc().initWithFrame_(((0, 0), (1000, 600)))
    window.setContentView_(view)

    def pump(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for _ in range(16):
                event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                    kit.NSEventMaskAny, foundation.NSDate.date(),
                    foundation.NSDefaultRunLoopMode, True,
                )
                if event is None:
                    break
                app.sendEvent_(event)
            app.updateWindows()
            time.sleep(0.005)

    def evaluate(script: str) -> Any:
        results = []
        view.evaluateJavaScript_completionHandler_(script, lambda value, error: results.append(
            (value, error),
        ))
        deadline = time.monotonic() + 5
        while not results and time.monotonic() < deadline:
            pump(0.01)
        assert results and results[0][1] is None, results
        return results[0][0]

    try:
        url = foundation.NSURL.fileURLWithPath_(str(tmp_path / "ocr.html"))
        view.loadFileURL_allowingReadAccessToURL_(
            url, foundation.NSURL.fileURLWithPath_(str(tmp_path)),
        )
        window.makeKeyAndOrderFront_(None)
        app.activateIgnoringOtherApps_(True)
        deadline = time.monotonic() + 8
        while view.isLoading() and time.monotonic() < deadline:
            pump(0.02)
        assert not view.isLoading()
        assert evaluate("document.querySelector('.sample').getAttribute('alt')") == ""
        assert evaluate("document.body.innerText.includes('학교')") is False
        pump(0.2)
        rect = evaluate("JSON.stringify(document.querySelector('.sample').getBoundingClientRect())")
        box = json.loads(rect)
        screen = window.convertPointToScreen_((box["x"] + 35, 600 - box["y"] - 25))
        top = kit.NSScreen.screens()[0].frame().size.height
        identities = {}
        for cursor in CURSORS:
            evaluate(f"choice.value='{cursor}';update();true")
            for x in (screen.x, screen.x + 1):
                quartz.CGEventPost(quartz.kCGHIDEventTap, quartz.CGEventCreateMouseEvent(
                    None, quartz.kCGEventMouseMoved, (x, top - screen.y), 0,
                ))
                pump(0.06)
            native = kit.NSCursor.currentSystemCursor()
            assert native is not None
            pixels = bytes(native.image().TIFFRepresentation())
            identities[cursor] = hashlib.sha256(pixels).hexdigest()
        assert identities["zoom-in"] != identities["default"]
        assert identities["zoom-out"] != identities["zoom-in"]
        assert identities["text"] != identities["default"]
        assert window.isKeyWindow()
    finally:
        window.orderOut_(None)
        window.close()
