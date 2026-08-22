"""Smoke tests for the two independently installable distributions."""

import importlib


def test_hanly_imports() -> None:
    module = importlib.import_module("hanly")

    assert module.__name__ == "hanly"


def test_hanly_app_imports() -> None:
    module = importlib.import_module("hanly_app")

    assert module.__name__ == "hanly_app"
    assert module.MouseObserver.__name__ == "MouseObserver"
    assert module.HoverController.__name__ == "HoverController"
    assert module.HoverLookupRuntime.__name__ == "HoverLookupRuntime"
    assert module.ControlCenterBridge.__name__ == "ControlCenterBridge"
