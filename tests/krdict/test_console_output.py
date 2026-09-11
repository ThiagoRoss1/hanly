"""What the Korean CLI tools are allowed to change about their streams."""

from __future__ import annotations

import io

import pytest

from tools.krdict import configure_utf8_output


def test_reconfiguring_for_utf8_keeps_the_error_handler_the_stream_had(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``reconfigure(encoding=...)`` resets the error handler to strict unless
    it is named too. The stream being reconfigured belongs to whoever is
    running the tool, and under pytest that is the capture file: losing
    ``replace`` there ends the session on the first undecodable byte a native
    library writes to the inherited descriptor."""

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="replace")
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setattr("sys.stderr", stream)

    configure_utf8_output()

    assert stream.encoding == "utf-8"
    assert stream.errors == "replace"
