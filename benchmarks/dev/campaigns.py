"""Real-seam lookup campaigns for performance and correctness evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any

from hanly import (
    DictionaryEntry,
    LookupPipeline,
    LookupResult,
    OCRResult,
    Point,
    ROIImage,
    TokenAnalysis,
)
from hanly.providers import DictionaryProvider, MorphologyProvider, OCRProvider
from hanly.word_resolver import TargetResolver, WordResolver

from .probes import observe_stage
from .run_store import RunStore
from .statistics import StatisticsError, summarize


@dataclass(frozen=True)
class CampaignPlan:
    """Number of retained first, warm-up, and warm inference samples."""

    warmup_samples: int = 2
    warm_samples: int = 30

    def __post_init__(self) -> None:
        for name, value in (
            ("warmup_samples", self.warmup_samples),
            ("warm_samples", self.warm_samples),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    def conditions(self) -> tuple[str, ...]:
        """Return one cold inference followed by configured warm-up/warm samples."""

        return (
            "cold",
            *("warmup" for _ in range(self.warmup_samples)),
            *("warm" for _ in range(self.warm_samples)),
        )


@dataclass(frozen=True)
class ExpectedLookup:
    """Observable correctness facts required from each timed lookup."""

    status: str
    text: str | None = None
    lemma: str | None = None
    headword: str | None = None


@dataclass
class _SampleContext:
    scenario: str = "unconfigured"
    iteration: int = 0
    condition: str = "cold"


class _StoreSink:
    """Translate generic probe records into the strict, flushed run ledger."""

    def __init__(self, store: RunStore, context: _SampleContext) -> None:
        self._store = store
        self._context = context
        self.latest_duration_ns: dict[str, int] = {}

    def __call__(self, record: Mapping[str, Any]) -> None:
        stage = str(record.get("stage", "unknown"))
        duration = record.get("duration_ns", 0)
        status = str(record.get("correctness_status", "unknown"))
        extra = {
            key: value
            for key, value in record.items()
            if key
            not in {
                "schema_version",
                "run_id",
                "timestamp",
                "evidence_class",
                "scenario",
                "stage",
                "iteration",
                "condition",
                "duration_ns",
                "correctness_status",
            }
        }
        normalized_duration = int(duration)
        self.latest_duration_ns[stage] = normalized_duration
        self._store.append_sample(
            evidence_class="measured",
            scenario=self._context.scenario,
            stage=stage,
            iteration=self._context.iteration,
            condition=self._context.condition,
            duration_ns=normalized_duration,
            correctness_status=status,
            **extra,
        )


class _ObservedOCR:
    def __init__(self, provider: OCRProvider, owner: ObservedLookupPipeline) -> None:
        self._provider = provider
        self._owner = owner

    def recognize(self, image: ROIImage) -> Sequence[OCRResult]:
        return self._owner.observe("ocr", self._provider.recognize, image)


class _ObservedMorphology:
    def __init__(self, provider: MorphologyProvider, owner: ObservedLookupPipeline) -> None:
        self._provider = provider
        self._owner = owner

    def analyze(self, text: str) -> Sequence[TokenAnalysis]:
        return self._owner.observe("morphology", self._provider.analyze, text)


class _ObservedDictionary:
    def __init__(self, provider: DictionaryProvider, owner: ObservedLookupPipeline) -> None:
        self._provider = provider
        self._owner = owner

    def lookup(self, lemma: str) -> Sequence[DictionaryEntry]:
        return self._owner.observe("dictionary", self._provider.lookup, lemma)


class _ObservedResolver:
    def __init__(self, resolver: TargetResolver, owner: ObservedLookupPipeline) -> None:
        self._resolver = resolver
        self._owner = owner

    def resolve_target(
        self, results: Sequence[OCRResult] | None, target: Point | None
    ) -> tuple[OCRResult, str] | None:
        return self._owner.observe(
            "token_selection", self._resolver.resolve_target, results, target
        )


class ObservedLookupPipeline:
    """Wrap the four existing pipeline seams while retaining its real algorithm."""

    def __init__(
        self,
        ocr_provider: OCRProvider,
        morphology_provider: MorphologyProvider,
        dictionary_provider: DictionaryProvider,
        *,
        store: RunStore,
        word_resolver: TargetResolver | None = None,
        confidence_threshold: float | None = None,
    ) -> None:
        self.store = store
        self._context = _SampleContext()
        self._sink = _StoreSink(store, self._context)
        self.last_results: dict[str, Any] = {}
        resolver = word_resolver or WordResolver()
        self._pipeline = LookupPipeline(
            _ObservedOCR(ocr_provider, self),
            _ObservedMorphology(morphology_provider, self),
            _ObservedDictionary(dictionary_provider, self),
            _ObservedResolver(resolver, self),
            confidence_threshold=confidence_threshold,
        )

    def begin_sample(self, *, scenario: str, iteration: int, condition: str) -> None:
        """Set correlation fields before one single-threaded pipeline call."""

        self._context.scenario = scenario
        self._context.iteration = iteration
        self._context.condition = condition

    def observe(self, stage: str, operation: Any, *args: Any) -> Any:
        """Measure one real seam and flush its record immediately."""

        result = observe_stage(
            stage,
            operation,
            self._sink,
            *args,
            run_id=self.store.run_id,
            scenario=self._context.scenario,
            iteration=self._context.iteration,
            condition=self._context.condition,
            evidence_class="measured",
            correctness={"status": "success"},
        )
        self.last_results[stage] = result
        return result

    @property
    def latest_duration_ns(self) -> Mapping[str, int]:
        """Durations for the latest invocation of every observed stage."""

        return dict(self._sink.latest_duration_ns)

    def lookup(self, image: ROIImage, target: Point) -> LookupResult:
        """Run the unchanged production pipeline."""

        return self._pipeline.lookup(image, target)


def run_lookup_campaign(
    pipeline: ObservedLookupPipeline,
    image: ROIImage,
    target: Point,
    *,
    store: RunStore,
    scenario: str,
    plan: CampaignPlan,
    expected: ExpectedLookup,
) -> tuple[LookupResult, ...]:
    """Run first/warm-up/warm lookups and retain stage plus total timings."""

    if pipeline.store is not store:
        raise ValueError("pipeline and campaign must use the same run store")
    results: list[LookupResult] = []

    for iteration, condition in enumerate(plan.conditions()):
        pipeline.begin_sample(
            scenario=scenario,
            iteration=iteration,
            condition=condition,
        )
        started = perf_counter_ns()
        result = pipeline.lookup(image, target)
        duration = perf_counter_ns() - started
        correctness, facts = evaluate_lookup(result, expected)
        store.append_sample(
            evidence_class="measured",
            scenario=scenario,
            stage="total_pipeline",
            iteration=iteration,
            condition=condition,
            duration_ns=duration,
            correctness_status=correctness,
            correctness=facts,
        )
        results.append(result)

    return tuple(results)


def evaluate_lookup(
    result: LookupResult, expected: ExpectedLookup
) -> tuple[str, dict[str, Any]]:
    """Compare observable normalized result facts without hiding mismatches."""

    context = result.context
    actual = {
        "status": result.status.value,
        "text": context.text if context is not None else None,
        "lemma": context.lemma if context is not None else None,
        "headword": result.entries[0].headword if result.entries else None,
        "ocr_regions": len(context.ocr_results) if context is not None else 0,
    }
    required = {
        "status": expected.status,
        "text": expected.text,
        "lemma": expected.lemma,
        "headword": expected.headword,
    }
    mismatches = {
        key: {"expected": value, "actual": actual[key]}
        for key, value in required.items()
        if value is not None and actual[key] != value
    }
    facts = {"actual": actual, "required": required, "mismatches": mismatches}
    return ("success" if not mismatches else "failed"), facts


def summarize_stages(samples: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return derived warm-success summaries independently for every stage."""

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for sample in samples:
        stage = sample.get("stage")
        if isinstance(stage, str):
            grouped.setdefault(stage, []).append(sample)

    summaries: dict[str, dict[str, Any]] = {}
    for stage, stage_samples in grouped.items():
        try:
            summaries[stage] = summarize(stage_samples)
        except StatisticsError:
            continue
    return summaries


__all__ = [
    "CampaignPlan",
    "ExpectedLookup",
    "ObservedLookupPipeline",
    "evaluate_lookup",
    "run_lookup_campaign",
    "summarize_stages",
]
