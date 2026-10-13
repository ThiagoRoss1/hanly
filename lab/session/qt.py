"""Qt setup for Lab-owned pages and HUDs, outside the product bootstrap."""

from __future__ import annotations

from typing import Any, cast


def create_application() -> Any:
    """Create the developer harness application without importing product UI."""

    from PyQt6.QtWidgets import QApplication

    application = cast(QApplication, QApplication.instance() or QApplication([]))
    application.setQuitOnLastWindowClosed(False)
    return application


__all__ = ["create_application"]
