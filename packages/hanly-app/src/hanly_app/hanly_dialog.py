"""Hanly's own small dialogs: styled like the popup, and in front when asked for.

Styling and bringing the window forward live here, and nothing about what a
dialog is asking. :class:`HanlyPrompt` offers the part of ``QMessageBox`` its
callers use, so the question being asked stays with the caller.
"""

from __future__ import annotations

import sys
from enum import Enum
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .config import Theme
from .qt_theme import FONT_STACK, PALETTES, resolved_mode


class PromptRole(Enum):
    """How a choice reads: the one it expects, another action, or backing out."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    CANCEL = "cancel"


def dialog_style(mode: str) -> str:
    """The stylesheet every Hanly dialog shares, for ``"light"`` or ``"dark"``."""

    p = PALETTES[mode]
    return "".join(
        [
            f"QDialog#hanlyDialog {{ background:{p['bg']}; }}",
            f"QWidget {{ color:{p['ink']}; font-family:{FONT_STACK}; }}",
            "QLabel#hanlyDialogTitle { font-size:16px; font-weight:600; }",
            f"QLabel#hanlyDialogText {{ font-size:13px; color:{p['ink2']}; }}",
            f"QPushButton {{ min-height:28px; max-height:28px; padding:0 14px; "
            f"border-radius:7px; font-size:12px; font-weight:500; "
            f"color:{p['ink2']}; background:transparent; border:1px solid {p['line']}; }}",
            f"QPushButton:hover {{ color:{p['ink']}; background:{p['hover']}; "
            f"border-color:{p['border']}; }}",
            f"QPushButton:focus {{ border-color:{p['accent']}; }}",
            f"QPushButton[role=\"primary\"] {{ background:{p['accent']}; color:{p['on_accent']}; "
            f"border-color:{p['accent']}; font-weight:600; }}",
            f"QPushButton[role=\"primary\"]:hover {{ background:{p['accent_ink']}; "
            f"border-color:{p['accent_ink']}; color:{p['bg']}; }}",
            f"QPushButton[role=\"secondary\"] {{ color:{p['accent_ink']}; "
            f"background:{p['accent_wash']}; border-color:transparent; }}",
            f"QPushButton[role=\"secondary\"]:hover {{ background:{p['accent_hover']}; }}",
        ]
    )


class HanlyPrompt(QDialog):
    """A question with a few answers, in Hanly's colours and in front."""

    class ButtonRole:
        """``QMessageBox`` role names, so a caller need not know the difference."""

        AcceptRole = PromptRole.PRIMARY
        ActionRole = PromptRole.SECONDARY
        RejectRole = PromptRole.CANCEL

    def __init__(self, parent: QWidget | None = None, *, theme: Theme = Theme.SYSTEM) -> None:
        flags = Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setObjectName("hanlyDialog")
        self.setModal(True)
        self.setStyleSheet(dialog_style(resolved_mode(theme)))
        self._clicked: QPushButton | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(6)
        self._title = QLabel(self)
        self._title.setObjectName("hanlyDialogTitle")
        self._text = QLabel(self)
        self._text.setObjectName("hanlyDialogText")
        self._text.setWordWrap(True)
        layout.addWidget(self._title)
        layout.addWidget(self._text)
        layout.addSpacing(14)
        self._buttons = QHBoxLayout()
        self._buttons.setSpacing(8)
        self._buttons.addStretch(1)
        layout.addLayout(self._buttons)
        self.setMinimumWidth(380)

    def setWindowTitle(self, title: str | None) -> None:  # noqa: N802 - Qt's name
        super().setWindowTitle(title)
        self._title.setText(title or "")

    def setText(self, text: str) -> None:  # noqa: N802 - QMessageBox's name
        self._text.setText(text)

    def addButton(self, text: str, role: PromptRole) -> QPushButton:  # noqa: N802
        button = QPushButton(text, self)
        button.setProperty("role", role.value)
        button.setAccessibleName(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self._choose(button, role))
        if role is PromptRole.PRIMARY:
            button.setDefault(True)
        # Backing out sits first, the expected answer last, as on both desktops.
        index = 1 if role is PromptRole.CANCEL else self._buttons.count()
        self._buttons.insertWidget(index, button)
        return button

    def clickedButton(self) -> QPushButton | None:  # noqa: N802
        return self._clicked

    def _choose(self, button: QPushButton, role: PromptRole) -> None:
        self._clicked = button
        if role is PromptRole.CANCEL:
            self.reject()
        else:
            self.accept()

    def showEvent(self, event: QShowEvent | None) -> None:  # noqa: N802
        super().showEvent(event)
        bring_to_front(self)


def bring_to_front(window: Any) -> None:
    """Put a window in front and give it the keyboard, on the first request.

    macOS activates the whole application, which Cocoa leaves to the caller
    once a window of another process was last in front. Windows accepts the
    request because the process the user clicked allowed this one first.
    """

    if sys.platform == "darwin":
        try:
            from .app_identity_darwin import activate_application

            activate_application()
        except Exception:
            pass
    window.raise_()
    window.activateWindow()
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.SetForegroundWindow(int(window.winId()))
        except Exception:
            pass


__all__ = [
    "PromptRole",
    "HanlyPrompt",
    "bring_to_front",
    "dialog_style",
]
