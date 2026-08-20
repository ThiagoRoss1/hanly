"""Smoke tests for the two independently installable distributions."""

import importlib


def test_hanly_imports() -> None:
    module = importlib.import_module("hanly")

    assert module.__name__ == "hanly"


def test_hanly_app_imports() -> None:
    module = importlib.import_module("hanly_app")

    assert module.__name__ == "hanly_app"
