"""Focused tests for the Apple Vision OCR adapter."""

import sys

import pytest
from hanly import OCRProvider, PixelFormat, ROIImage
from hanly.resource_manager import ResourceManager, ResourceManifest
from hanly.vision_provider import (
    DEFAULT_INPUT_SCALE,
    MAX_INPUT_SCALE,
    VisionConfig,
    VisionProvider,
    VisionProviderError,
)

from tests.hanly_fixtures.runtime_input import invoke_with_runtime_values


def _roi(width: int = 4, height: int = 2) -> ROIImage:
    return ROIImage(width, height, PixelFormat.RGB_888, bytes(width * height * 3))


def test_the_adapter_satisfies_the_engine_ocr_seam() -> None:
    assert isinstance(VisionProvider(), OCRProvider)


def test_availability_is_false_off_darwin_without_raising() -> None:
    if sys.platform != "darwin":
        assert VisionProvider.is_available() is False


def test_a_non_image_argument_is_a_type_error() -> None:
    with pytest.raises(TypeError):
        invoke_with_runtime_values(VisionProvider().recognize, "not an image")


@pytest.mark.skipif(sys.platform == "darwin", reason="covers the non-macOS path")
def test_recognizing_off_darwin_reports_a_provider_error() -> None:
    with pytest.raises(VisionProviderError, match="macOS"):
        VisionProvider().recognize(_roi())




def test_language_correction_is_off_by_default() -> None:
    """Correction can turn one real word into another, which a dictionary
    lookup must not do silently. It stays opt-in."""

    assert VisionConfig().language_correction is False
    assert VisionConfig().languages == ("ko-KR",)




def test_pinning_vision_where_it_does_not_exist_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Failing once at load beats failing identically on every lookup."""

    from hanly_app.config import OCRBackend
    from hanly_app.runtime import HanlyRuntime, RuntimeConfigError

    monkeypatch.setattr(VisionProvider, "is_available", staticmethod(lambda: False))
    runtime = HanlyRuntime(
        config_path=tmp_path / "runtime.json",
        resource_manager=ResourceManager(ResourceManifest(())),
        krdict_path=tmp_path / "krdict.sqlite3",
        ocr_backend=OCRBackend.VISION,
    )

    with pytest.raises(RuntimeConfigError, match="does not provide"):
        runtime._ocr_factory()


def test_auto_falls_back_instead_of_refusing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from hanly.easyocr_provider import EasyOCRConfig
    from hanly_app.config import OCRBackend
    from hanly_app.runtime import HanlyRuntime

    monkeypatch.setattr(VisionProvider, "is_available", staticmethod(lambda: False))
    runtime = HanlyRuntime(
        config_path=tmp_path / "runtime.json",
        resource_manager=ResourceManager(ResourceManifest(())),
        krdict_path=tmp_path / "krdict.sqlite3",
        ocr_backend=OCRBackend.AUTO,
        easyocr_config=EasyOCRConfig(),
    )

    assert runtime._ocr_factory() is not None


def test_host_vision_capability_resolves_without_loading_the_framework(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from hanly.easyocr_provider import EasyOCRConfig
    from hanly_app.config import OCRBackend
    from hanly_app.runtime import HanlyRuntime

    def unexpected_probe() -> bool:
        raise AssertionError("service runtime must use the native host capability")

    monkeypatch.setattr(VisionProvider, "is_available", staticmethod(unexpected_probe))
    runtime = HanlyRuntime(
        config_path=tmp_path / "runtime.json",
        resource_manager=ResourceManager(ResourceManifest(())),
        krdict_path=tmp_path / "krdict.sqlite3",
        easyocr_config=EasyOCRConfig(),
        ocr_backend=OCRBackend.AUTO,
        vision_available=True,
    )
    fallback = HanlyRuntime(
        config_path=tmp_path / "runtime.json",
        resource_manager=ResourceManager(ResourceManifest(())),
        krdict_path=tmp_path / "krdict.sqlite3",
        easyocr_config=EasyOCRConfig(),
        ocr_backend=OCRBackend.AUTO,
        vision_available=False,
    )

    assert runtime.resolved_ocr_backend() is OCRBackend.VISION
    assert fallback.resolved_ocr_backend() is OCRBackend.EASYOCR


def test_the_lookup_child_builds_the_recognizer_it_was_told_to(tmp_path) -> None:
    """The child never reads the runtime config.

    The recognizer choice has to travel with the spawn settings; while it did
    not, the parent resolved Vision and every actual lookup still ran EasyOCR.
    """

    from hanly.easyocr_provider import EasyOCRConfig
    from hanly_app.config import OCRBackend
    from hanly_app.lookup.process import LookupSettings, _ocr_provider_factory

    def settings(backend: OCRBackend) -> LookupSettings:
        return LookupSettings(
            krdict_path=tmp_path / "krdict.sqlite3",
            easyocr=EasyOCRConfig(),
            ocr_backend=backend,
        )

    # The factory is inspected rather than called: constructing the EasyOCR
    # provider would load Torch and its weights for an assertion about which
    # branch was taken.
    assert _ocr_provider_factory(settings(OCRBackend.VISION)) is VisionProvider
    assert _ocr_provider_factory(settings(OCRBackend.EASYOCR)) is not VisionProvider
    # ``auto`` never reaches the child; a stored one behaves as the historical
    # default rather than probing for a framework from a spawned process.
    assert _ocr_provider_factory(settings(OCRBackend.AUTO)) is not VisionProvider


def test_the_runtime_sends_its_backend_to_the_child(tmp_path) -> None:
    from hanly.easyocr_provider import EasyOCRConfig
    from hanly_app.config import OCRBackend
    from hanly_app.runtime import HanlyRuntime

    runtime = HanlyRuntime(
        config_path=tmp_path / "runtime.json",
        resource_manager=ResourceManager(ResourceManifest(())),
        krdict_path=tmp_path / "krdict.sqlite3",
        easyocr_config=EasyOCRConfig(),
        ocr_backend=OCRBackend.EASYOCR,
    )

    assert runtime.lookup_settings().ocr_backend is OCRBackend.EASYOCR
    # ``auto`` is resolved in the shell, so the child is never asked to decide.
    assert runtime.resolved_ocr_backend() is OCRBackend.EASYOCR
    assert (
        HanlyRuntime(
            config_path=tmp_path / "runtime.json",
            resource_manager=ResourceManager(ResourceManifest(())),
            krdict_path=tmp_path / "krdict.sqlite3",
            easyocr_config=EasyOCRConfig(),
            ocr_backend=OCRBackend.AUTO,
        ).lookup_settings().ocr_backend
        is not OCRBackend.AUTO
    )


# Vision can omit proportional text at capture size; enlarge only its model
# payload, never the ROI geometry returned to the resolver.


def test_the_recognizer_is_given_a_doubled_image_by_default() -> None:
    assert VisionConfig().input_scale == DEFAULT_INPUT_SCALE == 2


@pytest.mark.parametrize("scale", [0, -1, -100, 1.5, 2.0, True, False, "2", None])
def test_a_nonsensical_input_scale_is_refused(scale: object) -> None:
    with pytest.raises(ValueError, match="input_scale"):
        invoke_with_runtime_values(VisionConfig, input_scale=scale)


@pytest.mark.parametrize("scale", [MAX_INPUT_SCALE + 1, 64, 10**9])
def test_an_unreasonable_input_scale_is_refused(scale: int) -> None:
    """Scale grows the decoded image quadratically, so an unbounded value turns
    a configuration slip into an allocation the machine cannot satisfy."""

    with pytest.raises(ValueError, match="between 1 and"):
        VisionConfig(input_scale=scale)


def test_the_whole_permitted_range_is_constructible() -> None:
    for scale in range(1, MAX_INPUT_SCALE + 1):
        assert VisionConfig(input_scale=scale).input_scale == scale


def test_scaling_replicates_pixels_exactly_and_invents_no_detail() -> None:
    """Nearest-neighbour keeps this a presentation change: every output pixel
    is an input pixel, so the recognizer reads nothing that was not captured."""

    pytest.importorskip("PIL")
    from io import BytesIO

    from hanly.vision_provider import _png_bytes
    from PIL import Image

    source = Image.new("RGB", (3, 2))
    source.putpixel((0, 0), (255, 0, 0))
    source.putpixel((2, 1), (0, 0, 255))
    roi = ROIImage(3, 2, PixelFormat.RGB_888, source.tobytes())

    with Image.open(BytesIO(_png_bytes(roi, 2))) as doubled:
        assert doubled.size == (6, 4)
        # The red corner pixel became an exact 2x2 block of itself.
        assert {doubled.getpixel((x, y)) for x in (0, 1) for y in (0, 1)} == {(255, 0, 0)}
        assert {doubled.getpixel((x, y)) for x in (4, 5) for y in (2, 3)} == {(0, 0, 255)}
        # Only the counts change; no new colour is introduced.
        assert {colour for _count, colour in doubled.getcolors() or []} == {
            colour for _count, colour in source.getcolors() or []
        }

    with Image.open(BytesIO(_png_bytes(roi, 1))) as plain:
        assert plain.size == (3, 2)


# -- autorelease ownership ------------------------------------------------------------


class _RecordingPool:
    """Stands in for ``objc.autorelease_pool`` and records what ran inside it."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.active = False

    def __enter__(self) -> None:
        self.active = True
        self.events.append("enter")

    def __exit__(self, kind: object, value: object, traceback: object) -> None:
        self.active = False
        self.events.append("exit:error" if kind else "exit")


class _Observation:
    def __init__(self, events: list[str], pool: _RecordingPool) -> None:
        self._events = events
        self._pool = pool

    def topCandidates_(self, count: int) -> list[object]:
        self._events.append("normalize:" + ("inside" if self._pool.active else "outside"))
        candidate = type("Candidate", (), {"string": lambda self: "학교",
                                            "confidence": lambda self: 0.9})()
        return [candidate]

    def boundingBox(self) -> object:
        origin = type("P", (), {"x": 0.1, "y": 0.2})()
        size = type("S", (), {"width": 0.5, "height": 0.4})()
        return type("Box", (), {"origin": origin, "size": size})()


def _pooled_provider(
    monkeypatch: pytest.MonkeyPatch, run: object
) -> tuple[VisionProvider, list[str]]:
    import hanly.vision_provider as module

    events: list[str] = []
    pool = _RecordingPool(events)
    monkeypatch.setattr(module, "_autorelease_pool", lambda: pool)
    provider = VisionProvider()
    monkeypatch.setattr(provider, "_load", lambda: (object(), object()))
    monkeypatch.setattr(provider, "_payload", lambda image: b"png")
    monkeypatch.setattr(provider, "_run", lambda *args: run(events, pool))  # type: ignore[operator]
    return provider, events


def test_recognition_and_normalization_share_one_drained_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A worker thread has no pool of its own; normalization reads the native
    observations, so it must happen before the pool that owns them drains."""

    def run(events: list[str], pool: _RecordingPool) -> list[_Observation]:
        events.append("run:" + ("inside" if pool.active else "outside"))
        return [_Observation(events, pool)]

    provider, events = _pooled_provider(monkeypatch, run)

    results = provider.recognize(_roi(10, 10))

    assert events == ["enter", "run:inside", "normalize:inside", "exit"]
    # Plain values survive the drain.
    assert results[0].text == "학교" and isinstance(results[0].text, str)
    assert results[0].quad.p1.x == pytest.approx(1.0)


def test_a_failed_recognition_still_drains_its_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(events: list[str], pool: _RecordingPool) -> list[_Observation]:
        events.append("run")
        raise RuntimeError("Vision refused")

    provider, events = _pooled_provider(monkeypatch, run)

    with pytest.raises(VisionProviderError, match="Vision recognition failed"):
        provider.recognize(_roi(10, 10))
    assert events == ["enter", "run", "exit:error"]
