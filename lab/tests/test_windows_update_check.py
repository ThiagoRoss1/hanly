"""The isolated Windows update check's own reporting."""

from __future__ import annotations

from lab.checks.windows_update import public_message


def test_a_failure_keeps_the_updater_wording_and_drops_every_path() -> None:
    message = (
        r"Update failed: could not move C:\Users\someone\Hanly\x.dll "
        r"to \\server\share\y and C:/Users/someone/z; the update helper did not start"
    )

    public = public_message(message)

    assert public == (
        "Update failed: could not move <path> to <path> and <path>; "
        "the update helper did not start"
    )
    assert public_message(None) is None
