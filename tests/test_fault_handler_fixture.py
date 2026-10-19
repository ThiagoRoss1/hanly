"""COM teardown diagnostics remain compatible with pytest's captured stderr."""

from __future__ import annotations

import faulthandler
import io
import sys

import pytest

from tests.hanly_fixtures.fault_handler import quiet_fault_handler


@pytest.mark.parametrize("raises", [False, True])
def test_fault_handler_restores_reporting_with_a_stderr_without_fileno(
    monkeypatch: pytest.MonkeyPatch, raises: bool,
) -> None:
    enabled = faulthandler.is_enabled()
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    def exercise() -> None:
        with quiet_fault_handler():
            assert not faulthandler.is_enabled()
            if raises:
                raise ValueError("test body failed")

    if raises:
        with pytest.raises(ValueError, match="test body failed"):
            exercise()
    else:
        exercise()

    assert faulthandler.is_enabled() is enabled


def test_nested_suppression_preserves_a_previously_disabled_handler() -> None:
    enabled = faulthandler.is_enabled()

    with quiet_fault_handler():
        with quiet_fault_handler():
            assert not faulthandler.is_enabled()
        assert not faulthandler.is_enabled()

    assert faulthandler.is_enabled() is enabled
