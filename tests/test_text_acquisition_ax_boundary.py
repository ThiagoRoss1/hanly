"""Security checks before any AX text-range operation, with no desktop reads."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace
from typing import Any

import pytest
from hanly import Point
from hanly_app import text_acquisition_ax as ax


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
        assert provider.refine_bounds(Point(1, 1), 0, 1, timeout_ms=40) is None
    else:
        result = provider.read_at(Point(1, 1), timeout_ms=40)
        assert result is not None and result.secure
        assert result.text == "" and result.bounds is None
    assert text_reads == []
