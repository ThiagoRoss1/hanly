"""PaddleOCR adapter for the normalized Hanly OCR provider seam.

PaddleOCR is intentionally imported lazily.  The engine package can therefore
be imported by clients that do not install the optional Paddle runtime, while a
composition root can still construct this provider when PaddleOCR is available.
Only :class:`~hanly.contracts.OCRResult` values leave this module; Paddle's
result dictionaries and NumPy arrays remain implementation details here.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Any

from .contracts import OCRResult, PixelFormat, Point, Quad, ROIImage
from .errors import ProviderError


@dataclass(frozen=True)
class PaddleOCRConfig:
    """Explicit PaddleOCR construction options supplied by composition code.

    The model names are deliberately separate from the model directories. In
    PaddleOCR 3.7, passing a cached model directory without its matching model
    name can make the library compare the directory against its newer default
    model family and fail during startup.
    """

    text_detection_model_name: str | None = None
    text_detection_model_dir: str | Path | None = None
    text_recognition_model_name: str | None = None
    text_recognition_model_dir: str | Path | None = None
    textline_orientation_model_name: str | None = None
    textline_orientation_model_dir: str | Path | None = None
    doc_orientation_classify_model_name: str | None = None
    doc_orientation_classify_model_dir: str | Path | None = None
    doc_unwarping_model_name: str | None = None
    doc_unwarping_model_dir: str | Path | None = None
    lang: str | None = None
    ocr_version: str | None = None
    use_doc_orientation_classify: bool | None = None
    use_doc_unwarping: bool | None = None
    use_textline_orientation: bool | None = None
    text_rec_score_thresh: float | None = None
    return_word_box: bool | None = None
    extra_options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Freeze the mapping boundary as far as the public value object can;
        # callers cannot mutate the mapping held by a config after creation.
        object.__setattr__(self, "extra_options", dict(self.extra_options))

        for directory_field, name_field in (
            ("text_detection_model_dir", "text_detection_model_name"),
            ("text_recognition_model_dir", "text_recognition_model_name"),
            ("textline_orientation_model_dir", "textline_orientation_model_name"),
            (
                "doc_orientation_classify_model_dir",
                "doc_orientation_classify_model_name",
            ),
            ("doc_unwarping_model_dir", "doc_unwarping_model_name"),
        ):
            directory = getattr(self, directory_field)
            name = getattr(self, name_field)
            if directory is not None and name is None:
                raise ValueError(
                    f"{name_field} is required when {directory_field} is supplied"
                )

    def to_engine_kwargs(self) -> dict[str, Any]:
        """Return only the explicit options accepted by PaddleOCR 3.7."""

        options: dict[str, Any] = {}
        for name in (
            "text_detection_model_name",
            "text_detection_model_dir",
            "text_recognition_model_name",
            "text_recognition_model_dir",
            "textline_orientation_model_name",
            "textline_orientation_model_dir",
            "doc_orientation_classify_model_name",
            "doc_orientation_classify_model_dir",
            "doc_unwarping_model_name",
            "doc_unwarping_model_dir",
            "lang",
            "ocr_version",
            "use_doc_orientation_classify",
            "use_doc_unwarping",
            "use_textline_orientation",
            "text_rec_score_thresh",
            "return_word_box",
        ):
            value = getattr(self, name)
            if value is not None:
                options[name] = str(value) if name.endswith("_dir") else value
        options.update(self.extra_options)
        return options


class PaddleOCRProviderError(ProviderError):
    """Expected failure while constructing or invoking the Paddle adapter."""


@dataclass(frozen=True, slots=True)
class TextRecognitionResult:
    """One geometry-free result from Paddle's public recognition module."""

    text: str
    confidence: float

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("recognition text must be a string")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("recognition confidence must be between 0 and 1")


class PaddleTextRecognitionProvider:
    """Bounded adapter around PaddleOCR's public ``TextRecognition`` module."""

    def __init__(
        self,
        config: PaddleOCRConfig | None = None,
        *,
        engine: Any | None = None,
        engine_factory: Callable[..., Any] | None = None,
    ) -> None:
        if engine is not None and engine_factory is not None:
            raise ValueError("engine and engine_factory are mutually exclusive")

        if engine is None:
            provider_config = config or PaddleOCRConfig()
            model_name = provider_config.text_recognition_model_name
            model_dir = provider_config.text_recognition_model_dir
            if model_name is None or model_dir is None:
                raise PaddleOCRProviderError(
                    "text recognition model name and directory are required"
                )
            factory = engine_factory or self._load_text_recognition_factory()
            try:
                engine = factory(
                    model_name=model_name,
                    model_dir=str(model_dir),
                    input_shape=[3, 48, 160],
                    cpu_threads=2,
                    enable_mkldnn=False,
                )
            except Exception as exc:
                raise PaddleOCRProviderError(
                    f"TextRecognition initialization failed: {exc}"
                ) from exc

        if not callable(getattr(engine, "predict", None)):
            raise PaddleOCRProviderError(
                "TextRecognition engine must provide a callable predict method"
            )
        self._engine = engine
        self._prewarmed = False

    @staticmethod
    def _load_text_recognition_factory() -> Callable[..., Any]:
        try:
            from paddleocr import TextRecognition
        except Exception as exc:
            raise PaddleOCRProviderError(
                f"Paddle TextRecognition is unavailable: {exc}"
            ) from exc
        return TextRecognition

    def recognize_text(self, image: ROIImage) -> TextRecognitionResult | None:
        """Recognize one already-cropped line image without text detection."""

        if not isinstance(image, ROIImage):
            raise TypeError("image must be an ROIImage")
        paddle_image = PaddleOCRProvider._to_paddle_image(image)
        try:
            raw_results = self._engine.predict(paddle_image)
        except Exception as exc:
            raise PaddleOCRProviderError(
                f"TextRecognition inference failed: {exc}"
            ) from exc
        try:
            return self._normalize_result(raw_results)
        except PaddleOCRProviderError:
            raise
        except Exception as exc:
            raise PaddleOCRProviderError(
                f"TextRecognition returned malformed output: {exc}"
            ) from exc

    def prewarm(self) -> None:
        """Run one real, idempotent inference before the worker becomes ready."""

        if self._prewarmed:
            return
        blank = ROIImage(96, 32, PixelFormat.RGB_888, bytes(96 * 32 * 3))
        self.recognize_text(blank)
        self._prewarmed = True

    def close(self) -> None:
        close = getattr(self._engine, "close", None)
        if callable(close):
            close()

    @classmethod
    def _normalize_result(cls, raw_results: Any) -> TextRecognitionResult | None:
        if raw_results is None:
            return None
        if cls._is_result_mapping(raw_results):
            items = [raw_results]
        elif PaddleOCRProvider._is_sequence(raw_results):
            items = list(raw_results)
        else:
            raise PaddleOCRProviderError(
                "TextRecognition returned malformed output: expected a result sequence"
            )
        if not items:
            return None
        if len(items) != 1:
            raise PaddleOCRProviderError(
                "TextRecognition must return exactly one result for one crop"
            )

        result = cls._result_mapping(items[0])
        text = result.get("rec_text")
        confidence = result.get("rec_score")
        if not isinstance(text, str) or isinstance(confidence, bool) or not isinstance(
            confidence, (int, float)
        ):
            raise PaddleOCRProviderError(
                "TextRecognition returned malformed output: invalid text or confidence"
            )
        try:
            return TextRecognitionResult(text.strip(), float(confidence))
        except (TypeError, ValueError) as exc:
            raise PaddleOCRProviderError(
                f"TextRecognition returned malformed output: {exc}"
            ) from exc

    @staticmethod
    def _is_result_mapping(value: Any) -> bool:
        return isinstance(value, Mapping) or (
            hasattr(value, "__getitem__")
            and (hasattr(value, "rec_text") or hasattr(value, "keys"))
        )

    @staticmethod
    def _result_mapping(value: Any) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            return value
        json_value = getattr(value, "json", None)
        if callable(json_value):
            json_value = json_value()
        if isinstance(json_value, Mapping):
            nested = json_value.get("res", json_value)
            if isinstance(nested, Mapping):
                return nested
        try:
            return {
                "rec_text": value["rec_text"],
                "rec_score": value["rec_score"],
            }
        except Exception as exc:
            raise PaddleOCRProviderError(
                "TextRecognition returned malformed output: invalid result mapping"
            ) from exc


class PaddleOCRProvider:
    """Adapt PaddleOCR 3.7's prediction results to normalized OCR contracts.

    ``engine`` and ``engine_factory`` are dependency-injection seams for unit
    tests and application composition.  With neither supplied, the provider
    lazily constructs ``paddleocr.PaddleOCR`` using ``config``.  No resource
    manager is consulted here: validated model paths and configuration are
    explicit constructor inputs.
    """

    _CONFIG_FIELDS = frozenset(
        {
            "text_detection_model_name",
            "text_detection_model_dir",
            "text_recognition_model_name",
            "text_recognition_model_dir",
            "textline_orientation_model_name",
            "textline_orientation_model_dir",
            "doc_orientation_classify_model_name",
            "doc_orientation_classify_model_dir",
            "doc_unwarping_model_name",
            "doc_unwarping_model_dir",
            "lang",
            "ocr_version",
            "use_doc_orientation_classify",
            "use_doc_unwarping",
            "use_textline_orientation",
            "text_rec_score_thresh",
            "return_word_box",
        }
    )
    _ALIASES = {
        "det_model_name": "text_detection_model_name",
        "det_model_dir": "text_detection_model_dir",
        "rec_model_name": "text_recognition_model_name",
        "rec_model_dir": "text_recognition_model_dir",
        "use_angle_cls": "use_textline_orientation",
    }

    def __init__(
        self,
        config: PaddleOCRConfig | Mapping[str, Any] | None = None,
        *,
        engine: Any | None = None,
        engine_factory: Callable[..., Any] | None = None,
        **overrides: Any,
    ) -> None:
        if engine is not None and engine_factory is not None:
            raise ValueError("engine and engine_factory are mutually exclusive")

        try:
            provider_config = self._coerce_config(config, overrides)
        except (TypeError, ValueError) as exc:
            raise PaddleOCRProviderError(
                f"invalid PaddleOCR configuration: {exc}"
            ) from exc

        if engine is not None:
            self._engine = engine
        else:
            factory = engine_factory or self._load_paddleocr_factory()
            try:
                self._engine = factory(**provider_config.to_engine_kwargs())
            except Exception as exc:
                raise PaddleOCRProviderError(
                    f"PaddleOCR initialization failed: {exc}"
                ) from exc

        if not callable(getattr(self._engine, "predict", None)) and not callable(
            getattr(self._engine, "ocr", None)
        ):
            raise PaddleOCRProviderError(
                "PaddleOCR engine must provide a callable predict method"
            )

    @staticmethod
    def _load_paddleocr_factory() -> Callable[..., Any]:
        try:
            # Keep this import before any direct paddle import.  On Windows,
            # PaddleOCR's supported import order avoids a native DLL conflict.
            from paddleocr import PaddleOCR
        except Exception as exc:
            raise PaddleOCRProviderError(
                f"PaddleOCR is unavailable: {exc}"
            ) from exc
        return PaddleOCR

    @classmethod
    def _coerce_config(
        cls,
        config: PaddleOCRConfig | Mapping[str, Any] | None,
        overrides: Mapping[str, Any],
    ) -> PaddleOCRConfig:
        values: dict[str, Any] = {}
        extra: dict[str, Any] = {}

        if isinstance(config, PaddleOCRConfig):
            values = {
                field_name: getattr(config, field_name)
                for field_name in cls._CONFIG_FIELDS
                if getattr(config, field_name) is not None
            }
            extra.update(config.extra_options)
        elif config is not None:
            if not isinstance(config, Mapping):
                raise TypeError("config must be PaddleOCRConfig or a mapping")
            for key, value in config.items():
                canonical = cls._ALIASES.get(key, key)
                if canonical in cls._CONFIG_FIELDS:
                    values[canonical] = value
                elif key != "extra_options":
                    extra[key] = value
            if "extra_options" in config:
                supplied_extra = config["extra_options"]
                if not isinstance(supplied_extra, Mapping):
                    raise TypeError("extra_options must be a mapping")
                extra.update(supplied_extra)

        for key, value in overrides.items():
            canonical = cls._ALIASES.get(key, key)
            if canonical in cls._CONFIG_FIELDS:
                values[canonical] = value
            else:
                extra[key] = value

        return PaddleOCRConfig(**values, extra_options=extra)

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        """Run PaddleOCR for one ROI and return normalized results in order."""

        if not isinstance(image, ROIImage):
            raise TypeError("image must be an ROIImage")

        try:
            paddle_image = self._to_paddle_image(image)
        except PaddleOCRProviderError:
            raise
        except Exception as exc:
            raise PaddleOCRProviderError(
                f"PaddleOCR input conversion failed: {exc}"
            ) from exc

        try:
            predict = getattr(self._engine, "predict", None)
            if callable(predict):
                raw_results = predict(paddle_image)
            else:
                # PaddleOCR 3.7 uses predict; this narrow fallback keeps the
                # adapter usable with a legacy engine supplied by a caller.
                raw_results = self._engine.ocr(paddle_image)
        except Exception as exc:
            raise PaddleOCRProviderError(
                f"PaddleOCR recognition failed: {exc}"
            ) from exc

        try:
            return self._normalize_results(raw_results)
        except PaddleOCRProviderError:
            raise
        except Exception as exc:
            raise PaddleOCRProviderError(
                f"PaddleOCR returned malformed OCR output: {exc}"
            ) from exc

    @staticmethod
    def _to_paddle_image(image: ROIImage) -> Any:
        try:
            import numpy as np
        except Exception as exc:
            raise PaddleOCRProviderError(
                f"NumPy is required by PaddleOCR: {exc}"
            ) from exc

        channels = image.bytes_per_pixel
        shape: tuple[int, ...] = (image.height, image.width)
        if channels > 1:
            shape += (channels,)
        array: Any = np.frombuffer(image.data, dtype=np.uint8).reshape(shape)

        if image.pixel_format is PixelFormat.GRAYSCALE_8:
            # PaddleX unpacks height, width, and channels from the array it is
            # given, so a two-dimensional grayscale ROI fails before inference.
            # Replicating the single channel is the cheapest faithful
            # conversion and leaves the pixel values untouched.
            array = np.repeat(array[..., np.newaxis], 3, axis=2)
        elif image.pixel_format is PixelFormat.RGB_888:
            # PaddleX's OCR reader treats ndarray input as BGR.
            array = array[..., ::-1]
        elif image.pixel_format is PixelFormat.RGBA_8888:
            # Drop alpha and convert RGBA to Paddle's BGR convention.
            array = array[..., [2, 1, 0]]

        if array.ndim != 3 or array.dtype != np.uint8:
            # PaddleX unpacks height, width, and channels from the array it is
            # given. Checking here turns a malformed buffer into a clear
            # provider error instead of an obscure failure inside the library.
            raise PaddleOCRProviderError(
                "normalized ROI must be a 3-D uint8 array, got "
                f"{array.ndim}-D {array.dtype}"
            )
        return np.array(array, dtype=np.uint8, copy=True)

    @classmethod
    def _normalize_results(cls, raw_results: Any) -> tuple[OCRResult, ...]:
        if raw_results is None:
            return ()

        if cls._is_result_mapping(raw_results):
            batches = (raw_results,)
        elif cls._is_sequence(raw_results):
            raw_sequence = list(raw_results)
            if not raw_sequence:
                return ()
            first = raw_sequence[0]
            if cls._is_result_mapping(first):
                batches = tuple(raw_sequence)
            elif cls._is_legacy_detection(first):
                batches = (raw_sequence,)
            elif cls._is_sequence(first) and first and cls._is_legacy_detection(first[0]):
                # Legacy OCR output may contain one detection list per image.
                batches = tuple(raw_sequence)
            else:
                raise PaddleOCRProviderError(
                    "PaddleOCR returned malformed OCR output: unsupported result shape"
                )
        else:
            raise PaddleOCRProviderError(
                "PaddleOCR returned malformed OCR output: expected a result sequence"
            )

        normalized: list[OCRResult] = []
        for batch in batches:
            if cls._is_result_mapping(batch):
                normalized.extend(cls._normalize_v3_result(batch))
            else:
                normalized.extend(cls._normalize_legacy_result(batch))
        return tuple(normalized)

    @staticmethod
    def _is_sequence(value: Any) -> bool:
        return not isinstance(value, (str, bytes, bytearray, Mapping)) and (
            isinstance(value, Sequence)
            or (hasattr(value, "__len__") and hasattr(value, "__getitem__"))
        )

    @classmethod
    def _is_result_mapping(cls, value: Any) -> bool:
        if isinstance(value, Mapping):
            return True
        return any(
            hasattr(value, field_name)
            for field_name in ("rec_texts", "rec_scores", "rec_polys", "dt_polys")
        )

    @classmethod
    def _field(cls, value: Any, name: str) -> Any:
        if isinstance(value, Mapping):
            return value.get(name)
        return getattr(value, name, None)

    @classmethod
    def _normalize_v3_result(cls, result: Any) -> list[OCRResult]:
        texts_value = cls._field(result, "rec_texts")
        scores_value = cls._field(result, "rec_scores")
        if texts_value is None and scores_value is None:
            # A completely empty dict-like result is a valid no-detection
            # response from a fake or a future Paddle result wrapper.
            if isinstance(result, Mapping) and not result:
                return []
            raise PaddleOCRProviderError(
                "PaddleOCR returned malformed OCR output: missing rec_texts/rec_scores"
            )

        texts = cls._as_list(texts_value)
        scores = cls._as_list(scores_value)
        if not texts and not scores:
            return []
        if len(texts) != len(scores):
            raise PaddleOCRProviderError(
                "PaddleOCR returned malformed OCR output: text/confidence lengths differ"
            )

        geometry = None
        for name in ("rec_polys", "dt_polys", "rec_boxes"):
            candidate = cls._field(result, name)
            if candidate is not None:
                candidate_list = cls._as_list(candidate)
                if candidate_list or geometry is None:
                    geometry = candidate_list
                if candidate_list:
                    break
        if geometry is None or len(geometry) != len(texts):
            raise PaddleOCRProviderError(
                "PaddleOCR returned malformed OCR output: text/geometry lengths differ"
            )

        normalized: list[OCRResult] = []
        for text, confidence, raw_quad in zip(texts, scores, geometry):
            try:
                normalized.append(
                    OCRResult(
                        text=str(text),
                        confidence=float(confidence),
                        quad=cls._to_quad(raw_quad),
                    )
                )
            except Exception as exc:
                raise PaddleOCRProviderError(
                    f"PaddleOCR returned malformed OCR output: {exc}"
                ) from exc
        return normalized

    @classmethod
    def _normalize_legacy_result(cls, result: Any) -> list[OCRResult]:
        normalized: list[OCRResult] = []
        for entry in cls._as_list(result):
            if not cls._is_legacy_detection(entry):
                raise PaddleOCRProviderError(
                    "PaddleOCR returned malformed OCR output: invalid legacy detection"
                )
            raw_quad, recognition = entry
            try:
                text, confidence = recognition
                normalized.append(
                    OCRResult(
                        text=str(text),
                        confidence=float(confidence),
                        quad=cls._to_quad(raw_quad),
                    )
                )
            except Exception as exc:
                raise PaddleOCRProviderError(
                    f"PaddleOCR returned malformed OCR output: {exc}"
                ) from exc
        return normalized

    @classmethod
    def _is_legacy_detection(cls, value: Any) -> bool:
        if not cls._is_sequence(value):
            return False
        parts = cls._as_list(value)
        if len(parts) != 2 or not cls._is_sequence(parts[1]):
            return False
        recognition = cls._as_list(parts[1])
        return len(recognition) == 2

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, (str, bytes, bytearray)):
            return [value]
        if hasattr(value, "tolist"):
            value = value.tolist()
        try:
            return list(value)
        except TypeError:
            return [value]

    @staticmethod
    def _to_quad(raw_quad: Any) -> Quad:
        if isinstance(raw_quad, Quad):
            return raw_quad
        if hasattr(raw_quad, "tolist"):
            raw_quad = raw_quad.tolist()
        points = PaddleOCRProvider._as_list(raw_quad)
        if len(points) == 8 and all(
            not PaddleOCRProvider._is_sequence(point) for point in points
        ):
            points = [points[offset : offset + 2] for offset in range(0, 8, 2)]
        if len(points) == 4 and all(
            PaddleOCRProvider._is_sequence(point)
            and len(PaddleOCRProvider._as_list(point)) == 2
            for point in points
        ):
            normalized_points = [PaddleOCRProvider._as_list(point) for point in points]
            return Quad(
                p1=Point(float(normalized_points[0][0]), float(normalized_points[0][1])),
                p2=Point(float(normalized_points[1][0]), float(normalized_points[1][1])),
                p3=Point(float(normalized_points[2][0]), float(normalized_points[2][1])),
                p4=Point(float(normalized_points[3][0]), float(normalized_points[3][1])),
            )
        if len(points) == 4 and all(
            not PaddleOCRProvider._is_sequence(point) for point in points
        ):
            left, top, right, bottom = (float(point) for point in points)
            return Quad(
                p1=Point(left, top),
                p2=Point(right, top),
                p3=Point(right, bottom),
                p4=Point(left, bottom),
            )
        raise ValueError("each OCR geometry must contain four points or a box")


__all__ = [
    "PaddleOCRConfig",
    "PaddleOCRProvider",
    "PaddleOCRProviderError",
    "PaddleTextRecognitionProvider",
    "TextRecognitionResult",
]
