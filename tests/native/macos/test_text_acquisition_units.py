"""The accessibility adapter's index units, which are not Python's.

macOS counts characters in UTF-16 code units and Python counts code points.
They agree for Korean and diverge by one per surrogate pair, so a line holding
an emoji hands back an index naming a different character than the one under
the pointer.
"""

from __future__ import annotations

import ctypes
from typing import Any

from hanly import Point
from hanly_app.text_acquisition_ax import AccessibilityTextProvider


class _Bridge:
    """Stands in for the native bridge; only release is ever reached."""

    def release(self, reference: Any) -> None:
        return None


def _bridge() -> Any:
    """The native bridge stands in; only release is ever reached."""

    return _Bridge()


def _adapter_for(line: str, utf16_index: int) -> AccessibilityTextProvider:
    """An adapter whose native reads answer the way macOS really answers."""

    provider = AccessibilityTextProvider()
    provider._string_attribute = staticmethod(  # type: ignore[method-assign]
        lambda bridge, element, name: "AXTextArea" if name == "AXRole" else None
    )
    provider._index_at = staticmethod(  # type: ignore[method-assign]
        lambda bridge, element, point: utf16_index
    )
    provider._line_range = staticmethod(  # type: ignore[method-assign]
        lambda bridge, element, index: (0, len(line.encode("utf-16-le")) // 2)
    )
    provider._string_for_range = staticmethod(  # type: ignore[method-assign]
        lambda bridge, element, start, length: line
    )
    provider._bounds_for_range = staticmethod(  # type: ignore[method-assign]
        lambda bridge, element, start, length: None
    )
    return provider


def test_a_line_whose_offsets_are_not_python_indices_is_refused() -> None:
    """`🙂🙂초대받았어요`: UTF-16 index 4 is `초`, Python index 4 is `받`.

    Using it would define the wrong word while the pointer is on the right one,
    so the reading is refused and the caller falls back to OCR.
    """

    line = "🙂🙂초대받았어요"
    assert line[4] == "받"
    assert line.encode("utf-16-le")[8:10].decode("utf-16-le") == "초"

    adapter = _adapter_for(line, utf16_index=4)

    assert adapter._read_element(_bridge(), ctypes.c_void_p(1), Point(10, 10)) is None


def test_korean_without_surrogate_pairs_is_still_read() -> None:
    line = "초대받았어요"
    adapter = _adapter_for(line, utf16_index=2)

    reading = adapter._read_element(_bridge(), ctypes.c_void_p(1), Point(10, 10))

    assert reading is not None
    assert reading.text == line
    assert line[reading.cursor_index] == "받"


def test_plain_ascii_is_not_refused_by_the_unit_check() -> None:
    adapter = _adapter_for("hello", utf16_index=1)

    reading = adapter._read_element(_bridge(), ctypes.c_void_p(1), Point(10, 10))

    assert reading is not None and reading.cursor_index == 1
