"""Converting accessibility offsets into Python string indices.

macOS counts characters in UTF-16 code units and Python counts code points.
They agree for Korean and diverge by one per surrogate pair, so the conversion
happens once, at this boundary, and everything above it stays in code points.
"""

from __future__ import annotations

import ctypes
from typing import Any

import pytest
from hanly import Point
from hanly_app.text_acquisition_ax import AccessibilityTextProvider, _code_point_index


class _Bridge:
    """The native bridge stands in; only release is ever reached."""

    def release(self, reference: Any) -> None:
        return None


def _bridge() -> Any:
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


@pytest.mark.parametrize(
    ("text", "utf16_offset", "expected"),
    [
        # Korean alone: the two counts agree.
        ("초대받았어요", 0, 0),
        ("초대받았어요", 3, 3),
        ("초대받았어요", 6, 6),
        # One and several emoji before the Korean.
        ("🙂초대받았어요", 2, 1),
        ("🙂초대받았어요", 4, 3),
        ("🙂🙂초대받았어요", 4, 2),
        ("🙂🙂초대받았어요", 9, 7),
        # An emoji after, and inside, the surrounding text.
        ("초대🙂받다", 2, 2),
        ("초대🙂받다", 4, 3),
        ("초대받았어요🙂", 6, 6),
        # Combining marks are single code points and move nothing.
        ("가́나", 2, 2),
        # Multiline values keep counting through the separator.
        ("초대\n받다", 3, 3),
        # Both edges of the string.
        ("🙂초대", 0, 0),
        ("🙂초대", 4, 3),
    ],
)
def test_offsets_convert_to_code_point_indices(
    text: str, utf16_offset: int, expected: int
) -> None:
    assert _code_point_index(text, utf16_offset) == expected


@pytest.mark.parametrize(
    ("text", "utf16_offset"),
    [
        ("🙂초대", 1),        # inside the surrogate pair
        ("🙂🙂초대", 3),       # inside the second pair
        ("초대", -1),          # negative
        ("초대", 99),          # past the end
        ("", 1),               # past the end of nothing
    ],
)
def test_an_offset_naming_no_character_is_refused(text: str, utf16_offset: int) -> None:
    """Choosing the neighbouring character is how the wrong word gets defined."""

    assert _code_point_index(text, utf16_offset) is None


def test_a_line_with_emoji_now_reads_the_character_under_the_pointer() -> None:
    """`🙂🙂초대받았어요`: UTF-16 offset 4 is `초`, and Python index 4 is `받`."""

    line = "🙂🙂초대받았어요"
    assert line[4] == "받"

    reading = _adapter_for(line, utf16_index=4)._read_element(
        _bridge(), ctypes.c_void_p(1), Point(10, 10)
    )

    assert reading is not None
    assert line[reading.cursor_index] == "초"


def test_korean_without_surrogate_pairs_is_unchanged() -> None:
    line = "초대받았어요"

    reading = _adapter_for(line, utf16_index=2)._read_element(
        _bridge(), ctypes.c_void_p(1), Point(10, 10)
    )

    assert reading is not None
    assert reading.text == line
    assert line[reading.cursor_index] == "받"


def test_an_offset_inside_a_surrogate_pair_refuses_the_whole_reading() -> None:
    reading = _adapter_for("🙂초대", utf16_index=1)._read_element(
        _bridge(), ctypes.c_void_p(1), Point(10, 10)
    )

    assert reading is None
