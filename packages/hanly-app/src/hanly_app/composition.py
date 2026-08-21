"""Application composition for the first Hanly engine worker.

Concrete provider construction intentionally happens in the executor worker
thread.  In particular, ``KRDICTProvider`` opens its SQLite connection there
and is closed there, preserving SQLite's thread affinity without changing the
engine adapter.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from hanly import (
    DictionaryProvider,
    LookupPipeline,
    LookupResult,
    MorphologyProvider,
    OCRProvider,
)
from hanly.word_resolver import WordResolver

from .lookup_controller import LookupController, LookupRequest, ResultDispatcher


class Worker(Protocol):
    """Worker shape consumed by :class:`hanly_app.job_executor.JobExecutor`."""

    def __call__(self, item: LookupRequest) -> object:
        ...

    def close(self) -> None:
        ...


# Each factory names the protocol it must produce. Returning ``object`` was
# what forced the call site to suppress mypy; the provider protocols are
# structural, so any conforming adapter still satisfies these without
# inheriting anything.
OCRProviderFactory = Callable[[], OCRProvider]
MorphologyProviderFactory = Callable[[], MorphologyProvider]
DictionaryProviderFactory = Callable[[], DictionaryProvider]

# ``WordResolver`` is a concrete engine class rather than a protocol, so a
# resolver double cannot satisfy it structurally. Narrowing this alias would
# require introducing a resolver protocol in the engine seam, which is out of
# scope here; the cast below is therefore deliberate.
ResolverFactory = Callable[[], Any]

#: Retained for callers that describe any provider factory generically.
ProviderFactory = Callable[[], object]


class LookupWorker:
    """Own one pipeline and its provider instances for one executor thread."""

    def __init__(
        self,
        ocr_provider_factory: OCRProviderFactory,
        morphology_provider_factory: MorphologyProviderFactory,
        dictionary_provider_factory: DictionaryProviderFactory,
        *,
        word_resolver_factory: ResolverFactory | None = None,
        confidence_threshold: float | None = None,
    ) -> None:
        for name, factory in (
            ("ocr_provider_factory", ocr_provider_factory),
            ("morphology_provider_factory", morphology_provider_factory),
            ("dictionary_provider_factory", dictionary_provider_factory),
        ):
            if not callable(factory):
                raise TypeError(f"{name} must be callable")
        if word_resolver_factory is not None and not callable(word_resolver_factory):
            raise TypeError("word_resolver_factory must be callable")

        providers: list[object] = []
        try:
            # These calls are intentionally in worker construction, not in the
            # composition root. JobExecutor invokes its worker factory on its
            # own thread.
            ocr_provider = ocr_provider_factory()
            providers.append(ocr_provider)
            morphology_provider = morphology_provider_factory()
            providers.append(morphology_provider)
            dictionary_provider = dictionary_provider_factory()
            providers.append(dictionary_provider)
            resolver = (
                word_resolver_factory() if word_resolver_factory is not None else WordResolver()
            )
            self._pipeline = LookupPipeline(
                ocr_provider=ocr_provider,
                morphology_provider=morphology_provider,
                dictionary_provider=dictionary_provider,
                word_resolver=cast(WordResolver, resolver),
                confidence_threshold=confidence_threshold,
            )
        except Exception:
            _close_providers(providers)
            raise
        self._providers = tuple(providers)
        self._closed = False

    @property
    def pipeline(self) -> LookupPipeline:
        """The pipeline owned by this worker (useful for focused diagnostics)."""

        return self._pipeline

    def __call__(self, item: LookupRequest) -> LookupResult:
        if not isinstance(item, LookupRequest):
            raise TypeError("lookup worker items must be LookupRequest values")
        return self._pipeline.lookup(item.image, item.target)

    def close(self) -> None:
        """Close all close-capable providers exactly once, in reverse order."""

        if self._closed:
            return
        self._closed = True
        _close_providers(self._providers)


def create_lookup_worker_factory(
    ocr_provider_factory: OCRProviderFactory,
    morphology_provider_factory: MorphologyProviderFactory,
    dictionary_provider_factory: DictionaryProviderFactory,
    *,
    word_resolver_factory: ResolverFactory | None = None,
    confidence_threshold: float | None = None,
) -> Callable[[], LookupWorker]:
    """Return a JobExecutor worker factory with deferred provider creation."""

    return lambda: LookupWorker(
        ocr_provider_factory=ocr_provider_factory,
        morphology_provider_factory=morphology_provider_factory,
        dictionary_provider_factory=dictionary_provider_factory,
        word_resolver_factory=word_resolver_factory,
        confidence_threshold=confidence_threshold,
    )


# ``build_*`` is the descriptive spelling used by composition roots; retain
# the create spelling above for callers that treat this as a factory function.
build_lookup_worker_factory = create_lookup_worker_factory


def create_lookup_controller(
    ocr_provider_factory: OCRProviderFactory,
    morphology_provider_factory: MorphologyProviderFactory,
    dictionary_provider_factory: DictionaryProviderFactory,
    on_result: Callable[[LookupResult], None] | None = None,
    *,
    word_resolver_factory: ResolverFactory | None = None,
    confidence_threshold: float | None = None,
    on_error: Callable[[LookupRequest, BaseException], None] | None = None,
    result_dispatcher: ResultDispatcher | None = None,
    thread_name: str | None = None,
) -> LookupController:
    """Compose a controller whose providers are deferred to its worker thread."""

    worker_factory = create_lookup_worker_factory(
        ocr_provider_factory,
        morphology_provider_factory,
        dictionary_provider_factory,
        word_resolver_factory=word_resolver_factory,
        confidence_threshold=confidence_threshold,
    )
    return LookupController(
        worker_factory,
        on_result,
        on_error=on_error,
        result_dispatcher=result_dispatcher,
        thread_name=thread_name,
    )


build_lookup_controller = create_lookup_controller


def _close_providers(providers: tuple[object, ...] | list[object]) -> None:
    first_error: Exception | None = None
    for provider in reversed(tuple(providers)):
        close = getattr(provider, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except Exception as exc:
            # Make a best effort to close every provider.  Teardown failures
            # should not strand a SQLite connection because another provider
            # happened to fail its own cleanup.
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


__all__ = [
    "LookupWorker",
    "ProviderFactory",
    "ResolverFactory",
    "Worker",
    "build_lookup_worker_factory",
    "build_lookup_controller",
    "create_lookup_controller",
    "create_lookup_worker_factory",
]
