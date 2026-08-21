"""The real Hanly V1 provider runtime, described by a JSON config file.

``hanly_app.composition`` accepts provider factories and knows nothing about
local resources; this module supplies them, reading a runtime configuration
file and passing ResourceManager-validated values to the real V1 providers.

Provider construction is deferred to the ``JobExecutor`` thread. Constructing
``KRDICTProvider`` opens a thread-affine SQLite connection that must be closed
on the same thread, and keeping PaddleOCR's import lazy lets clients import
this package without the native Paddle stack installed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from hanly import LookupResult
from hanly.kiwi_provider import KiwiProvider
from hanly.krdict_provider import KRDICTProvider
from hanly.paddleocr_provider import PaddleOCRConfig, PaddleOCRProvider
from hanly.resource_manager import ResourceManager, ResourceManifest, ResourceSpec

from .composition import LookupWorker, ResolverFactory
from .composition import build_lookup_worker_factory as _build_lookup_worker_factory
from .composition import create_lookup_controller as _create_lookup_controller
from .lookup_controller import LookupController, LookupRequest, ResultDispatcher


class RuntimeConfigError(ValueError):
    """Raised when a runtime configuration file cannot be composed."""


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


@dataclass(frozen=True, slots=True)
class HanlyRuntime:
    """Validated provider configuration with deferred factories.

    The runtime stores only immutable-ish configuration values and validated
    paths. Provider instances are local to the worker returned by
    :meth:`create_worker_factory`; callers cannot accidentally share a Paddle,
    Kiwi, or SQLite object across threads.
    """

    config_path: Path
    resource_manager: ResourceManager
    paddle_config: PaddleOCRConfig
    krdict_path: Path
    confidence_threshold: float | None = None

    def create_worker_factory(
        self,
        *,
        word_resolver_factory: ResolverFactory | None = None,
        confidence_threshold: float | None = None,
    ) -> Callable[[], LookupWorker]:
        """Build a worker factory whose providers are created on invocation."""

        threshold = (
            self.confidence_threshold
            if confidence_threshold is None
            else confidence_threshold
        )
        _validate_confidence_threshold(threshold)

        # Construct nothing here: JobExecutor calls this factory on its own
        # thread, so each lambda below belongs to that worker's lifecycle.
        return _build_lookup_worker_factory(
            lambda: PaddleOCRProvider(config=self.paddle_config),
            KiwiProvider,
            lambda: KRDICTProvider(self.krdict_path),
            word_resolver_factory=word_resolver_factory,
            confidence_threshold=threshold,
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
    ) -> LookupController:
        """Compose the existing bounded controller with real V1 factories."""

        threshold = (
            self.confidence_threshold
            if confidence_threshold is None
            else confidence_threshold
        )
        _validate_confidence_threshold(threshold)
        return _create_lookup_controller(
            lambda: PaddleOCRProvider(config=self.paddle_config),
            KiwiProvider,
            lambda: KRDICTProvider(self.krdict_path),
            on_result,
            word_resolver_factory=word_resolver_factory,
            confidence_threshold=threshold,
            on_error=on_error,
            result_dispatcher=result_dispatcher,
            thread_name=thread_name,
        )



def load_runtime(config_path: str | Path) -> HanlyRuntime:
    """Load and validate a runtime configuration file.

    Relative paths in the JSON are resolved against the directory containing
    the configuration file, never against the process working directory.
    """

    path = Path(config_path).expanduser()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError(f"could not load runtime config {path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise RuntimeConfigError("runtime config must contain a JSON object")

    root = path.resolve().parent
    try:
        paddle_values = _paddle_values(raw)
        resources_value = raw.get("resources")
        if not isinstance(resources_value, Mapping):
            raise ValueError("resources is required and must be a JSON object")

        resource_values = dict(resources_value)
        detection_id = _REQUIRED_RESOURCE_IDS["detection"]
        recognition_id = _REQUIRED_RESOURCE_IDS["recognition"]
        krdict_id = _REQUIRED_RESOURCE_IDS["krdict"]
        for resource_id in (detection_id, recognition_id, krdict_id):
            if resource_id not in resource_values:
                raise ValueError(f"resources.{resource_id} is required")
        detection_value = resource_values[detection_id]
        recognition_value = resource_values[recognition_id]
        krdict_value = resource_values[krdict_id]

        _configured_model_dir(
            paddle_values,
            "detection",
            root,
            detection_value,
        )
        _configured_model_dir(
            paddle_values,
            "recognition",
            root,
            recognition_value,
        )

        _resource_path(krdict_value, root, "krdict")

        specs = _resource_specs(
            resource_values,
            required_configurations={
                detection_id: {"model_name": _model_name(paddle_values, "detection")},
                recognition_id: {"model_name": _model_name(paddle_values, "recognition")},
            },
            required_kinds={
                detection_id: "directory",
                recognition_id: "directory",
                krdict_id: "krdict",
            },
        )
        manager = ResourceManager(ResourceManifest(specs), base_path=root)
        metadata = manager.validate()
        invalid = []
        for resource_id, resource_metadata in metadata.items():
            if resource_metadata.status.value != "VALID":
                diagnostics = "; ".join(manager.diagnostics(resource_id))
                invalid.append(
                    f"{resource_id} is {resource_metadata.status.value.lower()}"
                    + (f": {diagnostics}" if diagnostics else "")
                )
        if invalid:
            raise RuntimeConfigError(
                "runtime resource validation failed: " + "; ".join(invalid)
            )

        paddle_config = _paddle_config(
            paddle_values,
            detection_path=manager.validated_path(detection_id),
            recognition_path=manager.validated_path(recognition_id),
            detection_name=_configuration_string(
                manager.configuration(detection_id), "model_name", detection_id
            ),
            recognition_name=_configuration_string(
                manager.configuration(recognition_id), "model_name", recognition_id
            ),
        )
        confidence_threshold = _confidence_threshold(raw, paddle_values)
    except RuntimeConfigError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise RuntimeConfigError(f"invalid runtime config {path}: {exc}") from exc

    return HanlyRuntime(
        config_path=path.resolve(),
        resource_manager=manager,
        paddle_config=paddle_config,
        krdict_path=manager.validated_path(krdict_id),
        confidence_threshold=confidence_threshold,
    )


def create_lookup_controller_from_config(
    config_path: str | Path,
    on_result: Callable[[LookupResult], None] | None = None,
    *,
    word_resolver_factory: ResolverFactory | None = None,
    confidence_threshold: float | None = None,
    on_error: Callable[[LookupRequest, BaseException], None] | None = None,
    result_dispatcher: ResultDispatcher | None = None,
    thread_name: str | None = None,
) -> LookupController:
    """Load a runtime config and compose its worker-owned controller."""

    return load_runtime(config_path).create_lookup_controller(
        on_result,
        word_resolver_factory=word_resolver_factory,
        confidence_threshold=confidence_threshold,
        on_error=on_error,
        result_dispatcher=result_dispatcher,
        thread_name=thread_name,
    )


def create_worker_factory_from_config(
    config_path: str | Path,
    *,
    word_resolver_factory: ResolverFactory | None = None,
    confidence_threshold: float | None = None,
) -> Callable[[], LookupWorker]:
    """Return a deferred real-provider worker factory for a runtime config."""

    return load_runtime(config_path).create_worker_factory(
        word_resolver_factory=word_resolver_factory,
        confidence_threshold=confidence_threshold,
    )


def _paddle_values(raw: Mapping[str, object]) -> dict[str, object]:
    value = raw.get("paddle")
    if not isinstance(value, Mapping):
        raise ValueError("paddle must be a JSON object")
    return dict(value)


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
    raw: Mapping[str, object], paddle: Mapping[str, object]
) -> float | None:
    value = raw.get("confidence_threshold", paddle.get("confidence_threshold"))
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
    "RuntimeConfigError",
    "create_lookup_controller_from_config",
    "create_worker_factory_from_config",
    "load_runtime",
]
