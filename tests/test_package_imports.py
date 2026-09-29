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


def test_every_exported_name_resolves_to_its_defining_module() -> None:
    import hanly_app

    for name in hanly_app.__all__:
        value = getattr(hanly_app, name)
        module = importlib.import_module(f"hanly_app.{hanly_app._EXPORTS[name]}")
        assert value is getattr(module, name), name
    assert len(hanly_app.__all__) == len(set(hanly_app.__all__))
    assert set(hanly_app.__all__) <= set(dir(hanly_app))


def test_importing_one_submodule_does_not_execute_the_desktop() -> None:
    """The frozen hook and the spawned lookup child import one module each."""

    import subprocess
    import sys

    probe = (
        "import sys, hanly_app.ocr_preload\n"
        "loaded = sorted(m for m in sys.modules if m.startswith('hanly_app.'))\n"
        "print(','.join(loaded))\n"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    ).stdout.strip().split(",")

    assert loaded == ["hanly_app.ocr_preload"]


def test_a_submodule_is_still_importable_by_name_from_the_package() -> None:
    from hanly_app import capture, composition

    assert capture.__name__ == "hanly_app.capture"
    assert composition.__name__ == "hanly_app.composition"
