"""The real Hanly V1 provider runtime, described by a JSON config file.

``hanly_app.composition`` accepts provider factories and knows nothing about
local resources; this module supplies them, reading a runtime configuration
file and passing ResourceManager-validated values to the real V1 providers.

Provider construction is deferred to the ``JobExecutor`` thread. Constructing
``KRDICTProvider`` opens a thread-affine SQLite connection that must be closed
on the same thread, and keeping each OCR library's import lazy lets clients
import this package without the native OCR stack installed.

EasyOCR is the only OCR adapter. It is a plain ``OCRProvider`` implementation
and is not visible to ``LookupPipeline``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from hanly import LookupResult
from hanly.easyocr_provider import EasyOCRConfig, EasyOCRProvider
from hanly.kiwi_provider import KiwiProvider
from hanly.krdict_provider import KRDICTProvider
from hanly.resource_manager import (
    ResourceManager,
    ResourceManifest,
    ResourceSpec,
)

from .composition import LookupWorker, OCRProviderFactory, ResolverFactory
from .composition import build_lookup_worker_factory as _build_lookup_worker_factory
from .composition import create_lookup_controller as _create_lookup_controller
from .lookup_controller import LookupController, LookupRequest, ResultDispatcher
from .runtime_trace import RuntimeTraceSink


class RuntimeConfigError(ValueError):
    """Raised when a runtime configuration file cannot be composed."""


#: The provider name the Control Center shows.
OCR_DISPLAY_NAME = "EasyOCR"
#: EasyOCR resolves its own models, so KRDICT is the only managed resource.
KRDICT_RESOURCE_ID = "krdict"

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
    Kiwi, or SQLite object across threads.
    """

    config_path: Path
    resource_manager: ResourceManager
    krdict_path: Path
    easyocr_config: EasyOCRConfig | None = None
    confidence_threshold: float | None = None
    skip_flat_rois: bool = False

    def _ocr_factory(self) -> OCRProviderFactory:
        easyocr_config = self.easyocr_config
        if easyocr_config is None:
            raise RuntimeConfigError(f"{self.config_path} carries no EasyOCR configuration")
        return lambda: EasyOCRProvider(config=easyocr_config)

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

        # Construct nothing here: JobExecutor calls this factory on its own
        # thread, so each factory below belongs to that worker's lifecycle.
        return _build_lookup_worker_factory(
            self._ocr_factory(),
            KiwiProvider,
            lambda: KRDICTProvider(self.krdict_path),
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
        return _create_lookup_controller(
            self._ocr_factory(),
            KiwiProvider,
            lambda: KRDICTProvider(self.krdict_path),
            on_result,
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
    try:
        manager = _resource_manager_from_payload(raw, root)
        _require_valid_resources(manager)

        easyocr_config = _easyocr_config(raw, root)
        confidence_threshold = _confidence_threshold(raw, _easyocr_values(raw))
        skip_flat_rois = _skip_flat_rois(raw)
    except RuntimeConfigError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise RuntimeConfigError(f"invalid runtime config {path}: {exc}") from exc

    return HanlyRuntime(
        config_path=path.resolve(),
        resource_manager=manager,
        krdict_path=manager.validated_path(KRDICT_RESOURCE_ID),
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
    if KRDICT_RESOURCE_ID not in resource_values:
        raise ValueError(f"resources.{KRDICT_RESOURCE_ID} is required")
    _resource_path(resource_values[KRDICT_RESOURCE_ID], root, "krdict")

    specs = _resource_specs(resource_values)
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

    # Unknown keys pass through as EasyOCR constructor options.
    options["extra_options"] = {
        key: value
        for key, value in values.items()
        if key not in _EASYOCR_FIELDS | {"confidence_threshold"}
    }
    try:
        return EasyOCRConfig(**options)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid easyocr options: {exc}") from exc


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


def _resource_specs(resources: Mapping[str, object]) -> tuple[ResourceSpec, ...]:
    """Turn the config file's ``resources`` section into engine resource specs."""

    specs: list[ResourceSpec] = []
    for resource_id, raw_value in dict(resources).items():
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise ValueError("resource ids must be non-empty strings")

        value = _resource_fields(resource_id, raw_value)
        kind = (
            "krdict"
            if resource_id == KRDICT_RESOURCE_ID
            else cast(str, value.get("kind", "file"))
        )

        path = _resource_path_field(resource_id, value, "path")
        if path is None:
            raise ValueError(f"resource {resource_id} path is required")
        version_file = _resource_path_field(resource_id, value, "version_file")

        configuration = _mapping_field(
            value.get("configuration"), "configuration", resource_id
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


def _confidence_threshold(
    raw: Mapping[str, object], easyocr_values: Mapping[str, object]
) -> float | None:
    """Read the threshold from the top level or the EasyOCR section."""

    value = raw.get("confidence_threshold", easyocr_values.get("confidence_threshold"))
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
    "KRDICT_RESOURCE_ID",
    "OCR_DISPLAY_NAME",
    "HanlyRuntime",
    "RuntimeConfigError",
    "create_lookup_controller_from_config",
    "create_worker_factory_from_config",
    "load_resource_manager",
    "load_runtime",
]
