"""The real Hanly V1 provider runtime, described by a JSON config file.

``hanly_app.composition`` accepts provider factories and knows nothing about
local resources; this module supplies them, reading a runtime configuration
file and passing ResourceManager-validated values to the real V1 providers.

Provider construction is deferred to the ``JobExecutor`` thread. Constructing
``KRDICTProvider`` opens a thread-affine SQLite connection that must be closed
on the same thread, and keeping each OCR library's import lazy lets clients
import this package without the native OCR stack installed.

``ocr_backend`` selects which OCR adapter a configuration composes. The engine
seam is unchanged either way: both adapters are plain ``OCRProvider``
implementations and neither is visible to ``LookupPipeline``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, cast

from hanly import LookupResult
from hanly.easyocr_provider import EasyOCRConfig, EasyOCRProvider
from hanly.kiwi_provider import KiwiProvider
from hanly.krdict_provider import KRDICTProvider
from hanly.paddleocr_provider import (
    PaddleOCRConfig,
    PaddleOCRProvider,
    PaddleTextRecognitionProvider,
)
from hanly.resource_manager import ResourceManager, ResourceManifest, ResourceSpec

from .composition import (
    LookupWorker,
    OCRProviderFactory,
    ResolverFactory,
    TextRecognitionProviderFactory,
)
from .composition import build_lookup_worker_factory as _build_lookup_worker_factory
from .composition import create_lookup_controller as _create_lookup_controller
from .lookup_controller import LookupController, LookupRequest, ResultDispatcher
from .runtime_trace import RuntimeTraceSink


class RuntimeConfigError(ValueError):
    """Raised when a runtime configuration file cannot be composed."""


class OCRBackend(str, Enum):
    """The OCR adapter a runtime configuration selects."""

    PADDLE = "paddle"
    EASYOCR = "easyocr"

    @property
    def runtime_module(self) -> str:
        """The import whose native libraries must be loaded before Qt starts."""

        return "paddleocr" if self is OCRBackend.PADDLE else "easyocr"

    @property
    def display_name(self) -> str:
        """The provider name the Control Center shows for this backend."""

        return "PaddleOCR" if self is OCRBackend.PADDLE else "EasyOCR"


_REQUIRED_RESOURCE_IDS = {
    "detection": "paddle_detection_model",
    "recognition": "paddle_recognition_model",
    "krdict": "krdict",
}

_PADDLE_FIELDS = frozenset(
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

_EASYOCR_FIELDS = frozenset(
    {
        "languages",
        "model_storage_directory",
        "user_network_directory",
        "download_enabled",
        "cpu_threads",
    }
)


@dataclass(frozen=True, slots=True)
class HanlyRuntime:
    """Validated provider configuration with deferred factories.

    The runtime stores only immutable-ish configuration values and validated
    paths. Provider instances are local to the worker returned by
    :meth:`create_worker_factory`; callers cannot accidentally share an OCR,
    Kiwi, or SQLite object across threads. Exactly one OCR configuration is
    populated, the one ``ocr_backend`` names.
    """

    config_path: Path
    resource_manager: ResourceManager
    krdict_path: Path
    ocr_backend: OCRBackend = OCRBackend.EASYOCR
    paddle_config: PaddleOCRConfig | None = None
    easyocr_config: EasyOCRConfig | None = None
    confidence_threshold: float | None = None
    skip_flat_rois: bool = False

    def require_paddle_config(self) -> PaddleOCRConfig:
        """Return the Paddle options, rejecting a differently backed runtime.

        Paddle-specific tooling asks for its configuration through this method
        so that pointing it at, say, an EasyOCR runtime fails with a clear
        message instead of a ``None`` dereference.
        """

        if self.ocr_backend is not OCRBackend.PADDLE or self.paddle_config is None:
            raise RuntimeConfigError(
                f"{self.config_path} selects the {self.ocr_backend.value} OCR "
                "backend and carries no PaddleOCR configuration"
            )
        return self.paddle_config

    def _ocr_factories(
        self,
    ) -> tuple[OCRProviderFactory, TextRecognitionProviderFactory | None]:
        """Return the OCR provider factory and any hover fast-path companion.

        Only PaddleOCR exposes a geometry-free recognition module, so it is the
        only backend that supplies the hover fast path. EasyOCR returns ``None``
        and the worker uses the ordinary provider seam for every lookup.
        """

        if self.ocr_backend is OCRBackend.PADDLE:
            paddle_config = self.require_paddle_config()
            return (
                lambda: PaddleOCRProvider(config=paddle_config),
                lambda: PaddleTextRecognitionProvider(config=paddle_config),
            )

        easyocr_config = self.easyocr_config
        if easyocr_config is None:
            raise RuntimeConfigError(
                f"{self.config_path} carries no EasyOCR configuration"
            )
        return lambda: EasyOCRProvider(config=easyocr_config), None

    def create_worker_factory(
        self,
        *,
        word_resolver_factory: ResolverFactory | None = None,
        confidence_threshold: float | None = None,
        trace_sink: RuntimeTraceSink | None = None,
    ) -> Callable[[], LookupWorker]:
        """Build a worker factory whose providers are created on invocation."""

        threshold = (
            self.confidence_threshold
            if confidence_threshold is None
            else confidence_threshold
        )
        _validate_confidence_threshold(threshold)
        ocr_provider_factory, text_recognition_factory = self._ocr_factories()

        # Construct nothing here: JobExecutor calls this factory on its own
        # thread, so each factory below belongs to that worker's lifecycle.
        return _build_lookup_worker_factory(
            ocr_provider_factory,
            KiwiProvider,
            lambda: KRDICTProvider(self.krdict_path),
            hover_text_recognition_provider_factory=text_recognition_factory,
            word_resolver_factory=word_resolver_factory,
            confidence_threshold=threshold,
            skip_flat_rois=self.skip_flat_rois,
            trace_sink=trace_sink,
        )


    def create_lookup_controller(
        self,
        on_result: Callable[[LookupResult], None] | None = None,
        *,
        word_resolver_factory: ResolverFactory | None = None,
        confidence_threshold: float | None = None,
        on_error: Callable[[LookupRequest, BaseException], None] | None = None,
        result_dispatcher: ResultDispatcher | None = None,
        thread_name: str | None = None,
        trace_sink: RuntimeTraceSink | None = None,
    ) -> LookupController:
        """Compose the existing bounded controller with real V1 factories."""

        threshold = (
            self.confidence_threshold
            if confidence_threshold is None
            else confidence_threshold
        )
        _validate_confidence_threshold(threshold)
        ocr_provider_factory, text_recognition_factory = self._ocr_factories()
        return _create_lookup_controller(
            ocr_provider_factory,
            KiwiProvider,
            lambda: KRDICTProvider(self.krdict_path),
            on_result,
            hover_text_recognition_provider_factory=text_recognition_factory,
            word_resolver_factory=word_resolver_factory,
            confidence_threshold=threshold,
            on_error=on_error,
            result_dispatcher=result_dispatcher,
            thread_name=thread_name,
            trace_sink=trace_sink,
        )



def load_runtime(config_path: str | Path) -> HanlyRuntime:
    """Load and validate a runtime configuration file.

    Relative paths in the JSON are resolved against the directory containing
    the configuration file, never against the process working directory.
    """

    path = Path(config_path).expanduser()
    raw = _load_runtime_payload(path)
    root = path.resolve().parent
    krdict_id = _REQUIRED_RESOURCE_IDS["krdict"]
    try:
        backend = _ocr_backend(raw)
        manager = _resource_manager_from_payload(raw, root)
        _require_valid_resources(manager)

        paddle_config: PaddleOCRConfig | None = None
        easyocr_config: EasyOCRConfig | None = None
        if backend is OCRBackend.PADDLE:
            paddle_config = _validated_paddle_config(raw, manager)
            backend_values = _paddle_values(raw)
        else:
            easyocr_config = _easyocr_config(raw, root)
            backend_values = _easyocr_values(raw)
        confidence_threshold = _confidence_threshold(raw, backend_values)
        skip_flat_rois = _skip_flat_rois(raw)
    except RuntimeConfigError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise RuntimeConfigError(f"invalid runtime config {path}: {exc}") from exc

    return HanlyRuntime(
        config_path=path.resolve(),
        resource_manager=manager,
        krdict_path=manager.validated_path(krdict_id),
        ocr_backend=backend,
        paddle_config=paddle_config,
        easyocr_config=easyocr_config,
        confidence_threshold=confidence_threshold,
        skip_flat_rois=skip_flat_rois,
    )


def _skip_flat_rois(raw: Mapping[str, object]) -> bool:
    """Read the opt-in that lets a flat ROI bypass OCR entirely.

    It is off by default because a wrong "there is no text here" decision makes
    the popup silently stop working, which is worse than the OCR call it saves.
    """

    value = raw.get("skip_flat_rois", False)
    if not isinstance(value, bool):
        raise ValueError("skip_flat_rois must be a boolean")
    return value


def read_ocr_backend(config_path: str | Path) -> OCRBackend:
    """Read only the OCR backend a configuration selects.

    Process bootstrap must import the configured OCR library before Qt starts,
    which is earlier than resources can be validated, so this deliberately
    inspects nothing else.
    """

    path = Path(config_path).expanduser()
    try:
        return _ocr_backend(_load_runtime_payload(path))
    except RuntimeConfigError:
        raise
    except (TypeError, ValueError) as exc:
        raise RuntimeConfigError(f"invalid runtime config {path}: {exc}") from exc


def _ocr_backend(raw: Mapping[str, object]) -> OCRBackend:
    value = raw.get("ocr_backend", OCRBackend.EASYOCR.value)
    if isinstance(value, str):
        try:
            return OCRBackend(value)
        except ValueError:
            pass
    supported = ", ".join(backend.value for backend in OCRBackend)
    raise ValueError(f"ocr_backend must be one of: {supported}")


def _require_valid_resources(manager: ResourceManager) -> None:
    """Reject startup while any declared resource is not usable."""

    invalid = []
    for resource_id, resource_metadata in manager.validate().items():
        if resource_metadata.status.value == "VALID":
            continue
        diagnostics = "; ".join(manager.diagnostics(resource_id))
        invalid.append(
            f"{resource_id} is {resource_metadata.status.value.lower()}"
            + (f": {diagnostics}" if diagnostics else "")
        )
    if invalid:
        raise RuntimeConfigError(
            "runtime resource validation failed: " + "; ".join(invalid)
        )


def _validated_paddle_config(
    raw: Mapping[str, object], manager: ResourceManager
) -> PaddleOCRConfig:
    """Build Paddle options from the manifest's validated model resources."""

    detection_id = _REQUIRED_RESOURCE_IDS["detection"]
    recognition_id = _REQUIRED_RESOURCE_IDS["recognition"]
    _require_model_files_at_root(manager, (detection_id, recognition_id))

    return _paddle_config(
        _paddle_values(raw),
        detection_path=manager.validated_path(detection_id),
        recognition_path=manager.validated_path(recognition_id),
        detection_name=_configuration_string(
            manager.configuration(detection_id), "model_name", detection_id
        ),
        recognition_name=_configuration_string(
            manager.configuration(recognition_id), "model_name", recognition_id
        ),
    )


def _require_model_files_at_root(
    manager: ResourceManager, resource_ids: tuple[str, ...]
) -> None:
    """Reject a model directory that holds no file directly at its root.

    ``ResourceManager`` validates a directory resource as existing, readable,
    and a directory. A model archive packed inside a wrapper directory passes
    all three, activates, and then fails much later inside PaddleOCR with no
    link back to the packaging mistake. The check is filename-agnostic: it
    asserts the layout PaddleOCR needs without encoding any model's file names.
    """

    for resource_id in resource_ids:
        path = manager.validated_path(resource_id)
        try:
            has_root_file = any(entry.is_file() for entry in path.iterdir())
        except OSError as exc:
            raise RuntimeConfigError(
                f"could not read the model directory for {resource_id}: {exc}"
            ) from exc
        if not has_root_file:
            raise RuntimeConfigError(
                f"{resource_id} has no model file directly in {path}: a model archive "
                "must place its files at the resource root, not inside a wrapper directory"
            )


def load_resource_manager(config_path: str | Path) -> ResourceManager:
    """Load the local resource manifest without requiring resources to exist.

    First-run provisioning uses this composition-owned parser to inspect a
    generated or existing runtime configuration before asking ``UpdateService``
    to fill missing artifacts. Runtime startup still calls :func:`load_runtime`,
    which performs the final all-valid check and builds provider options.
    """

    path = Path(config_path).expanduser()
    raw = _load_runtime_payload(path)
    try:
        return _resource_manager_from_payload(raw, path.resolve().parent)
    except (TypeError, ValueError, KeyError) as exc:
        raise RuntimeConfigError(f"invalid runtime config {path}: {exc}") from exc


def _load_runtime_payload(path: Path) -> Mapping[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError(f"could not load runtime config {path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise RuntimeConfigError("runtime config must contain a JSON object")
    return raw


def _resource_manager_from_payload(
    raw: Mapping[str, object], root: Path
) -> ResourceManager:
    resources_value = raw.get("resources")
    if not isinstance(resources_value, Mapping):
        raise ValueError("resources is required and must be a JSON object")

    resource_values = dict(resources_value)
    krdict_id = _REQUIRED_RESOURCE_IDS["krdict"]
    required_configurations: dict[str, Mapping[str, object]] = {}
    required_kinds = {krdict_id: "krdict"}

    # EasyOCR resolves its own model files through EasyOCR's storage
    # directory, so a runtime backed by it declares no managed model resource.
    if _ocr_backend(raw) is OCRBackend.PADDLE:
        paddle_values = _paddle_values(raw)
        detection_id = _REQUIRED_RESOURCE_IDS["detection"]
        recognition_id = _REQUIRED_RESOURCE_IDS["recognition"]
        for resource_id in (detection_id, recognition_id):
            if resource_id not in resource_values:
                raise ValueError(f"resources.{resource_id} is required")
        _configured_model_dir(paddle_values, "detection", root, resource_values[detection_id])
        _configured_model_dir(
            paddle_values, "recognition", root, resource_values[recognition_id]
        )
        required_configurations = {
            detection_id: {"model_name": _model_name(paddle_values, "detection")},
            recognition_id: {"model_name": _model_name(paddle_values, "recognition")},
        }
        required_kinds |= {detection_id: "directory", recognition_id: "directory"}

    if krdict_id not in resource_values:
        raise ValueError(f"resources.{krdict_id} is required")
    _resource_path(resource_values[krdict_id], root, "krdict")

    specs = _resource_specs(
        resource_values,
        required_configurations=required_configurations,
        required_kinds=required_kinds,
    )
    return ResourceManager(ResourceManifest(specs), base_path=root)


def create_lookup_controller_from_config(
    config_path: str | Path,
    on_result: Callable[[LookupResult], None] | None = None,
    *,
    word_resolver_factory: ResolverFactory | None = None,
    confidence_threshold: float | None = None,
    on_error: Callable[[LookupRequest, BaseException], None] | None = None,
    result_dispatcher: ResultDispatcher | None = None,
    thread_name: str | None = None,
    trace_sink: RuntimeTraceSink | None = None,
) -> LookupController:
    """Load a runtime config and compose its worker-owned controller."""

    return load_runtime(config_path).create_lookup_controller(
        on_result,
        word_resolver_factory=word_resolver_factory,
        confidence_threshold=confidence_threshold,
        on_error=on_error,
        result_dispatcher=result_dispatcher,
        thread_name=thread_name,
        trace_sink=trace_sink,
    )


def create_worker_factory_from_config(
    config_path: str | Path,
    *,
    word_resolver_factory: ResolverFactory | None = None,
    confidence_threshold: float | None = None,
    trace_sink: RuntimeTraceSink | None = None,
) -> Callable[[], LookupWorker]:
    """Return a deferred real-provider worker factory for a runtime config."""

    return load_runtime(config_path).create_worker_factory(
        word_resolver_factory=word_resolver_factory,
        confidence_threshold=confidence_threshold,
        trace_sink=trace_sink,
    )


def _paddle_values(raw: Mapping[str, object]) -> dict[str, object]:
    value = raw.get("paddle")
    if not isinstance(value, Mapping):
        raise ValueError("paddle must be a JSON object")
    return dict(value)


def _easyocr_values(raw: Mapping[str, object]) -> dict[str, object]:
    """Read the optional EasyOCR section; its defaults are already usable."""

    value = raw.get("easyocr", {})
    if not isinstance(value, Mapping):
        raise ValueError("easyocr must be a JSON object")
    return dict(value)


def _easyocr_config(raw: Mapping[str, object], root: Path) -> EasyOCRConfig:
    """Build EasyOCR options, rooting any model directory at the config file."""

    values = _easyocr_values(raw)
    options: dict[str, Any] = {}

    languages = values.get("languages")
    if languages is not None:
        if isinstance(languages, str) or not isinstance(languages, Sequence):
            raise ValueError("easyocr.languages must be a JSON array of language codes")
        options["languages"] = tuple(languages)

    for field_name in ("model_storage_directory", "user_network_directory"):
        directory = values.get(field_name)
        if directory is not None:
            options[field_name] = _resolve_path(root, directory, f"easyocr {field_name}")

    for field_name in ("download_enabled", "cpu_threads"):
        value = values.get(field_name)
        if value is not None:
            options[field_name] = value

    # Unknown keys pass through as constructor options, matching how the paddle
    # section forwards library options it does not model itself.
    options["extra_options"] = {
        key: value
        for key, value in values.items()
        if key not in _EASYOCR_FIELDS | {"confidence_threshold"}
    }
    try:
        return EasyOCRConfig(**options)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid easyocr options: {exc}") from exc


def _configured_model_dir(
    paddle: Mapping[str, object],
    kind: str,
    root: Path,
    resource_value: object,
) -> Path:
    _model_name(paddle, kind)
    configured = _model_dir_value(paddle, kind)
    if configured is None:
        field_name = (
            "text_detection_model_dir"
            if kind == "detection"
            else "text_recognition_model_dir"
        )
        raise ValueError(f"{field_name} is required for paddle {kind} model")
    path = _resolve_path(root, configured, f"paddle {kind} model dir")
    resource_path = _resource_path(resource_value, root, f"paddle {kind} model")
    if path != resource_path:
        raise ValueError(f"paddle {kind} model dir does not match its resource path")
    return path


def _model_name(paddle: Mapping[str, object], kind: str) -> str:
    field_name = (
        "text_detection_model_name"
        if kind == "detection"
        else "text_recognition_model_name"
    )
    value = paddle.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required for paddle {kind} model")
    return value


def _model_dir_value(paddle: Mapping[str, object], kind: str) -> object | None:
    field_name = (
        "text_detection_model_dir"
        if kind == "detection"
        else "text_recognition_model_dir"
    )
    return paddle.get(field_name)


_RESOURCE_FIELDS = frozenset(
    {
        "path",
        "version",
        "checksum",
        "version_file",
        "installed_version",
        "expected_version",
        "kind",
        "configuration",
        "compatible_with",
        "requires",
    }
)


def _resource_specs(
    resources: Mapping[str, object],
    *,
    required_configurations: Mapping[str, Mapping[str, object]],
    required_kinds: Mapping[str, str],
) -> tuple[ResourceSpec, ...]:
    """Turn the config file's ``resources`` section into engine resource specs."""

    specs: list[ResourceSpec] = []
    for resource_id, raw_value in dict(resources).items():
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise ValueError("resource ids must be non-empty strings")

        value = _resource_fields(resource_id, raw_value)
        kind = _resource_kind(resource_id, value, required_kinds)

        path = _resource_path_field(resource_id, value, "path")
        if path is None:
            raise ValueError(f"resource {resource_id} path is required")
        version_file = _resource_path_field(resource_id, value, "version_file")

        configuration = _resource_configuration(
            resource_id, value, required_configurations
        )

        specs.append(
            ResourceSpec(
                resource_id=resource_id,
                path=path,
                version=_optional_string(value.get("version"), "version", resource_id),
                checksum=_optional_string(value.get("checksum"), "checksum", resource_id),
                version_file=version_file,
                installed_version=_optional_string(
                    value.get("installed_version"), "installed_version", resource_id
                ),
                expected_version=_optional_string(
                    value.get("expected_version"), "expected_version", resource_id
                ),
                kind=kind,
                configuration=configuration,
                compatible_with=_mapping_field(
                    value.get("compatible_with"), "compatible_with", resource_id
                ),
                requires=_mapping_field(value.get("requires"), "requires", resource_id),
            )
        )

    return tuple(specs)


def _resource_fields(resource_id: str, value: object) -> Mapping[str, object]:
    """Normalize one resource entry to a mapping and reject unknown fields."""

    if isinstance(value, str):
        value = {"path": value}
    if not isinstance(value, Mapping):
        raise ValueError(f"resource {resource_id} must be a JSON object")

    unknown = set(value) - _RESOURCE_FIELDS
    if unknown:
        raise ValueError(
            f"resource {resource_id} has unknown field(s): {', '.join(sorted(unknown))}"
        )
    return value


def _resource_kind(
    resource_id: str,
    value: Mapping[str, object],
    required_kinds: Mapping[str, str],
) -> str:
    """Resolve a resource kind, letting required kinds override the config file."""

    if resource_id in required_kinds:
        return required_kinds[resource_id]
    return cast(str, value.get("kind", "file"))


def _resource_path_field(
    resource_id: str,
    value: Mapping[str, object],
    field_name: str,
) -> Path | None:
    """Read one path-valued field, left unresolved for ``ResourceManager``."""

    raw = value.get(field_name)
    if raw is None:
        return None

    if not isinstance(raw, (str, Path)) or not str(raw).strip():
        label = "path" if field_name == "path" else "version file"
        raise ValueError(f"resource {resource_id} {label} must be a non-empty path")
    return Path(raw).expanduser()


def _resource_configuration(
    resource_id: str,
    value: Mapping[str, object],
    required_configurations: Mapping[str, Mapping[str, object]],
) -> dict[str, Any]:
    """Merge required provider configuration over the config file's own values.

    A key the file sets to a conflicting value is an error rather than a silent
    override, so a paddle model name cannot disagree with the resource that
    carries it.
    """

    configuration = dict(
        _mapping_field(value.get("configuration"), "configuration", resource_id)
    )
    for key, required_value in required_configurations.get(resource_id, {}).items():
        existing_value = configuration.get(key)
        if existing_value is not None and existing_value != required_value:
            raise ValueError(
                f"resource {resource_id} configuration {key!r} does not match "
                "the paddle section"
            )
        configuration[key] = required_value

    return configuration


def _paddle_config(
    paddle: Mapping[str, object],
    *,
    detection_path: Path,
    recognition_path: Path,
    detection_name: str,
    recognition_name: str,
) -> PaddleOCRConfig:
    values: dict[str, Any] = {}
    for field_name in _PADDLE_FIELDS:
        value = paddle.get(field_name)
        if value is not None:
            values[field_name] = value
    values["text_detection_model_name"] = detection_name
    values["text_detection_model_dir"] = detection_path
    values["text_recognition_model_name"] = recognition_name
    values["text_recognition_model_dir"] = recognition_path

    extra = paddle.get("extra_options", {})
    if not isinstance(extra, Mapping):
        raise ValueError("paddle.extra_options must be a JSON object")
    extra_options = dict(extra)
    # to_engine_kwargs applies extra_options last, so an extra option named
    # after an explicit field would silently replace a validated model path.
    # Unknown keys still pass through; PaddleOCR rejects the ones it refuses.
    colliding = sorted(set(extra_options) & _PADDLE_FIELDS)
    if colliding:
        raise ValueError(
            "paddle.extra_options must not override explicit paddle field(s): "
            + ", ".join(colliding)
        )
    for key, value in paddle.items():
        if key not in _PADDLE_FIELDS | {
            "extra_options",
            "confidence_threshold",
        }:
            extra_options[key] = value
    if "enable_mkldnn" in extra_options and not isinstance(
        extra_options["enable_mkldnn"], bool
    ):
        raise ValueError("paddle enable_mkldnn must be a boolean")
    values["extra_options"] = extra_options
    try:
        return PaddleOCRConfig(**values)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid paddle options: {exc}") from exc


def _confidence_threshold(
    raw: Mapping[str, object], backend_values: Mapping[str, object]
) -> float | None:
    """Read the threshold from the top level or the selected backend section."""

    value = raw.get("confidence_threshold", backend_values.get("confidence_threshold"))
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence_threshold must be a number between 0 and 1")
    threshold = float(value)
    if not 0 <= threshold <= 1:
        raise ValueError("confidence_threshold must be a number between 0 and 1")
    return threshold


def _validate_confidence_threshold(value: float | None) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise ValueError("confidence_threshold must be a number between 0 and 1")
    if value is not None and not 0 <= value <= 1:
        raise ValueError("confidence_threshold must be a number between 0 and 1")


def _resource_path(value: object, root: Path, label: str) -> Path:
    if isinstance(value, str):
        raw_path: object = value
    elif isinstance(value, Mapping):
        raw_path = value.get("path")
    else:
        raw_path = None
    if raw_path is None:
        raise ValueError(f"{label} path is required")
    return _resolve_path(root, raw_path, f"{label} path")


def _resolve_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError(f"{label} must be a non-empty path")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def _optional_string(value: object, field_name: str, resource_id: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"resource {resource_id} {field_name} must be a string")
    return value


def _mapping_field(value: object, field_name: str, resource_id: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"resource {resource_id} {field_name} must be a JSON object")
    return dict(value)


def _configuration_string(
    configuration: Mapping[str, Any], key: str, resource_id: str
) -> str:
    value = configuration.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeConfigError(
            f"resource {resource_id} configuration {key!r} must be a non-empty string"
        )
    return value


__all__ = [
    "HanlyRuntime",
    "OCRBackend",
    "RuntimeConfigError",
    "create_lookup_controller_from_config",
    "create_worker_factory_from_config",
    "load_resource_manager",
    "load_runtime",
    "read_ocr_backend",
]
