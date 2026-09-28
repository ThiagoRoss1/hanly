"""AX security and snapshot checks at the adapter boundary, with no desktop reads."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace
from typing import Any

import pytest
from hanly import BoundingBox, Point
from hanly_app import text_acquisition_ax as ax
from hanly_app.text_acquisition import DirectTextCoordinator, Outcome


@pytest.mark.parametrize("refine", [False, True])
def test_secure_subrole_prevents_read_and_refinement(
    monkeypatch: pytest.MonkeyPatch, refine: bool
) -> None:
    bridge = SimpleNamespace(
        element_at=lambda *args: ctypes.c_void_p(1), release=lambda *args: None
    )
    monkeypatch.setattr(ax, "_bridge_once", lambda: bridge)
    provider = ax.AccessibilityTextProvider()
    monkeypatch.setattr(
        provider, "_string_attribute",
        lambda bridge, element, name: {
            "AXRole": "AXTextField", "AXSubrole": "AXSecureTextField"
        }.get(name),
    )
    text_reads: list[bool] = []

    def index(*args: Any) -> None:
        text_reads.append(True)

    monkeypatch.setattr(provider, "_index_at", index)
    if refine:
        assert provider.refine_bounds(Point(1, 1), 0, 1, line="초", timeout_ms=40) is None
    else:
        result = provider.read_at(Point(1, 1), timeout_ms=40)
        assert result is not None and result.secure
        assert result.text == "" and result.bounds is None
    assert text_reads == []


_LINE_BOUNDS = BoundingBox(0, 0, 20, 10)


@pytest.mark.parametrize(
    ("refined_text", "refined_subrole", "element_gone", "expected"),
    [
        ("초대", None, False, Outcome.DIRECT),
        ("사과", None, False, Outcome.AMBIGUOUS),
        ("초대받", None, False, Outcome.AMBIGUOUS),
        (None, None, False, Outcome.AMBIGUOUS),
        ("초대", None, True, Outcome.AMBIGUOUS),
        ("초대", "AXSecureTextField", False, Outcome.AMBIGUOUS),
    ],
    ids=["unchanged", "same-length", "different-length", "unreadable", "gone", "secure"],
)
def test_refinement_belongs_to_the_line_originally_read(
    monkeypatch: pytest.MonkeyPatch,
    refined_text: str | None,
    refined_subrole: str | None,
    element_gone: bool,
    expected: Outcome,
) -> None:
    """Bounds are only kept for exactly the content the lookup is about."""

    elements = iter([ctypes.c_void_p(1), None if element_gone else ctypes.c_void_p(2)])
    bridge = SimpleNamespace(
        element_at=lambda *args: next(elements), release=lambda *args: None
    )
    monkeypatch.setattr(ax, "_bridge_once", lambda: bridge)
    provider = ax.AccessibilityTextProvider()
    refining = {"now": False}

    def attribute(bridge: Any, element: Any, name: str) -> str | None:
        if name == "AXRole":
            return "AXTextArea"
        return refined_subrole if refining["now"] else None

    def string_for_range(*args: Any) -> str | None:
        answer = "초대" if not refining["now"] else refined_text
        refining["now"] = True
        return answer

    monkeypatch.setattr(provider, "_string_attribute", attribute)
    monkeypatch.setattr(provider, "_index_at", lambda *args: 0)
    monkeypatch.setattr(provider, "_line_range", lambda *args: (0, 2))
    monkeypatch.setattr(provider, "_string_for_range", string_for_range)
    monkeypatch.setattr(provider, "_bounds_for_range", lambda *args: _LINE_BOUNDS)

    # A fixed clock: this is about the snapshot, and a runner stall past the real
    # 40 ms deadline once turned the unchanged case into ``timed_out`` in CI.
    coordinator = DirectTextCoordinator(provider, clock=lambda: 0)
    acquired = coordinator.acquire(Point(5, 5))

    assert acquired.outcome is expected
    if expected is not Outcome.DIRECT:
        assert acquired.selection is None and acquired.bounds is None
