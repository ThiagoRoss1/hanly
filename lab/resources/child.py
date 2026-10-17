"""One resource experiment, run in a fresh interpreter and measured from outside.

``python -m lab.resources.child <plan.json>`` executes the plan's stages in
order. After each stage it writes one JSON line and blocks until the parent
answers, so the parent reads this process at an exact boundary while it is
idle. The child measures nothing about itself except latency, how many calls
reached the recognizer, and what it returned.

Providers are built, used and closed on one thread named like the lookup
child's worker, never on the main thread: native frameworks such as Vision
behave differently on a thread without an autorelease pool, and that is the
thread the application runs them on. Recognized text and pixels never leave
the child; geometry, confidence and digests do.
"""

from __future__ import annotations

import gc
import hashlib
import json
import queue
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, TypeVar

#: The lookup child's provider thread, as ``hanly_app.lookup.process`` names it.
WORKER_THREAD = "hanly-lookup-worker"

COMPONENTS = ("ocr", "kiwi", "dictionary", "synthetic")

T = TypeVar("T")


class _Handshake:
    """Report a finished stage and wait until the parent has measured it."""

    def __init__(self) -> None:
        self._clock = time.perf_counter_ns()

    def report(self, stage: str, **detail: Any) -> None:
        now = time.perf_counter_ns()
        record = {"stage": stage, "duration_ns": now - self._clock, **detail}
        sys.stdout.write(json.dumps(record) + "\n")
        sys.stdout.flush()
        if sys.stdin.readline().strip() != "go":
            raise SystemExit(0)
        # The parent's read is not part of the next stage.
        self._clock = time.perf_counter_ns()

    def tick(self, stage: str, index: int, latency_ns: int, **detail: Any) -> None:
        sys.stdout.write(
            json.dumps({"stage": stage, "tick": index, "latency_ns": latency_ns, **detail}) + "\n"
        )
        sys.stdout.flush()
        if sys.stdin.readline().strip() != "go":
            raise SystemExit(0)


class _Worker:
    """The one thread that owns every provider, as in the lookup child."""

    def __init__(self) -> None:
        self._jobs: queue.Queue[tuple[Callable[[], Any], queue.Queue[Any]] | None] = (
            queue.Queue()
        )
        self._thread = threading.Thread(target=self._run, name=WORKER_THREAD, daemon=True)
        self._thread.start()

    def call(self, work: Callable[[], T]) -> T:
        reply: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._jobs.put((work, reply))
        ok, value = reply.get()
        if not ok:
            raise value
        return value

    def stop(self) -> None:
        self._jobs.put(None)
        self._thread.join(timeout=30)

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            work, reply = job
            try:
                reply.put((True, work()))
            except BaseException as error:  # handed back to the caller
                reply.put((False, error))


class _CountingOCR:
    """Count the calls that really reach the recognizer.

    Wraps the provider under every cache, so a cache hit is visibly not a
    recognition; everything except ``recognize`` passes through untouched.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls = 0

    def recognize(self, image: Any) -> Any:
        self.calls += 1
        return self._inner.recognize(image)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def ocr_record(results: Sequence[Any]) -> dict[str, Any]:
    """What a recognition returned, comparable without keeping its text.

    Order, a digest of each region's text, its confidence and its corners are
    kept; the comparison applies tolerances to the numbers and none to text or
    order.
    """

    regions = []
    for result in results:
        quad = result.quad
        regions.append({
            "text": _digest(result.text),
            "confidence": round(float(result.confidence), 4),
            "quad": [
                round(value, 2)
                for point in (quad.p1, quad.p2, quad.p3, quad.p4)
                for value in (point.x, point.y)
            ],
        })
    return {"regions": regions, "digest": _digest(regions)}


def _result_decision(result: Any) -> dict[str, Any]:
    """Digest the selected entry and its morphological explanation."""

    context = result.context
    selected = None
    if context is not None and context.selected_ocr is not None:
        selected = _digest(context.selected_ocr.text)
    decision = {
        "status": str(result.status.value),
        "surface": _digest(context.text) if context is not None and context.text else None,
        "lemma": _digest(context.lemma) if context is not None and context.lemma else None,
        "selected_line": selected,
        "entries": [
            [entry.entry_id or entry.headword, entry.part_of_speech] for entry in result.entries
        ],
        "candidate": asdict(context.candidate) if context and context.candidate else None,
        "components": [asdict(part) for part in context.components] if context else [],
        "analyses": [asdict(token) for token in context.analyses] if context else [],
        "construction": (
            {"headword": context.construction.headword, "entries": [
                [entry.entry_id or entry.headword, entry.part_of_speech]
                for entry in context.construction.entries
            ]} if context and context.construction else None
        ),
    }
    return {"status": decision["status"], "digest": _digest(decision)}


def _load_inputs(path: Path) -> list[dict[str, Any]]:
    """Inputs the parent rendered: a JSON index line followed by raw pixels."""

    with path.open("rb") as stream:
        index = json.loads(stream.readline())
        blob = stream.read()
    for item in index:
        item["data"] = blob[item["offset"]: item["offset"] + item["length"]]
    return list(index)


def _repeat(
    handshake: _Handshake,
    stage: str,
    work: Callable[[int], dict[str, Any]],
    count: int,
    calls: Callable[[], int] | None,
) -> None:
    before = calls() if calls else None
    for index in range(count):
        started_calls = calls() if calls else None
        started = time.perf_counter_ns()
        detail = work(index)
        latency = time.perf_counter_ns() - started
        if calls and started_calls is not None:
            detail["ocr_calls"] = calls() - started_calls
        handshake.tick(stage, index, latency, **detail)
    handshake.report(
        stage, count=count,
        **({"ocr_calls": calls() - before} if calls and before is not None else {}),
    )


def _ocr_factory(settings: Any, plan: dict[str, Any]) -> Callable[[], Any]:
    """The application's recognizer, or a named Lab variant of it."""

    from hanly_app.lookup.process import _ocr_provider_factory

    variant = plan.get("ocr_variant") or "product"
    if variant == "product":
        return _ocr_provider_factory(settings)
    from .ocr_variants import VARIANTS

    return VARIANTS[variant]


def run(plan: dict[str, Any]) -> None:
    handshake = _Handshake()
    handshake.report("interpreter")

    from dataclasses import replace

    from hanly import PixelFormat, Point, ROIImage
    from hanly_app.config import OCRBackend
    from hanly_app.runtime import load_runtime

    handshake.report("import_runtime", modules=len(sys.modules))

    settings: Any = None
    if plan.get("runtime_config") is not None:
        runtime = load_runtime(plan["runtime_config"])
        settings = replace(
            runtime.lookup_settings(), ocr_backend=OCRBackend(plan["ocr_backend"])
        )
    handshake.report("runtime_validation", skipped=settings is None)

    inputs = _load_inputs(Path(plan["inputs_path"])) if plan.get("inputs_path") else []
    images = [
        ROIImage(
            width=item["width"], height=item["height"],
            pixel_format=PixelFormat(item["pixel_format"]), data=item["data"],
        )
        for item in inputs
    ]
    targets = [Point(item["target_x"], item["target_y"]) for item in inputs]
    worker = _Worker()
    try:
        if plan["mode"] == "component":
            _run_component(plan, handshake, worker, settings, images)
        else:
            _run_sequence(plan, handshake, worker, settings, images, targets)
    finally:
        worker.stop()


def _run_sequence(
    plan: dict[str, Any],
    handshake: _Handshake,
    worker: _Worker,
    settings: Any,
    images: Sequence[Any],
    targets: Sequence[Any],
) -> None:
    from hanly.kiwi_provider import KiwiProvider
    from hanly.krdict_provider import KRDICTProvider
    from hanly_app.composition import create_lookup_worker_factory
    from hanly_app.lookup.controller import LookupRequest

    lookups = int(plan["lookups"])
    idle = float(plan["idle_seconds"])
    # One owner for everything loaded, so unloading is one visible clear.
    held: dict[str, Any] = {}
    factory = _ocr_factory(settings, plan)

    def load_ocr() -> None:
        held["ocr"] = _CountingOCR(factory())

    worker.call(load_ocr)
    handshake.report("load_ocr", backend=settings.ocr_backend.value)
    worker.call(lambda: held.__setitem__("kiwi", KiwiProvider()))
    handshake.report("load_kiwi")
    worker.call(lambda: held.__setitem__("dictionary", KRDICTProvider(settings.krdict_path)))
    handshake.report("load_dictionary")

    # The app's child hands the worker factories; these return the instances
    # already measured, so assembly is the pipeline, caches and prewarming.
    def assemble() -> None:
        held["worker"] = create_lookup_worker_factory(
            lambda: held["ocr"], lambda: held["kiwi"], lambda: held["dictionary"],
            confidence_threshold=settings.confidence_threshold,
            skip_flat_rois=settings.skip_flat_rois,
            ocr_backend=settings.ocr_backend.value,
        )()

    worker.call(assemble)
    provider_types = (
        type(held["ocr"]._inner), type(held["kiwi"]), type(held["dictionary"]),
    )
    handshake.report(
        "assemble_worker", instances=worker.call(lambda: _instances(provider_types)),
        ocr_calls=held["ocr"].calls,
    )

    request_ids = iter(range(1, 10_000_000))
    def calls() -> int:
        return int(held["ocr"].calls)

    def lookup(index: int) -> dict[str, Any]:
        request = LookupRequest(next(request_ids), images[index], targets[index])
        return {**worker.call(lambda: _result_decision(held["worker"](request))),
                "input": index}

    def varied(index: int) -> dict[str, Any]:
        # Index 0 is the first lookup's input and already cached, so varied
        # work cycles through the rest; only the first pass is fresh, and the
        # recorded OCR calls say so rather than the label.
        others = max(1, len(images) - 1)
        return lookup(1 + index % others if len(images) > 1 else 0)

    before = calls()
    first = lookup(0)
    handshake.report("first_lookup", **first, ocr_calls=calls() - before)
    _repeat(handshake, "repeated_varied", varied, lookups, calls)
    _repeat(handshake, "repeated_same", lambda _i: lookup(0), lookups, calls)

    time.sleep(idle)
    handshake.report(
        "idle", seconds=idle, instances=worker.call(lambda: _instances(provider_types)),
    )

    def unload() -> None:
        # The worker closes the providers it was handed.
        held.pop("worker").close()
        held.clear()
        gc.collect()

    worker.call(unload)
    handshake.report("unload", instances=worker.call(lambda: _instances(provider_types)))
    time.sleep(min(idle, 2.0))
    handshake.report("after_unload_idle")


def _instances(types: tuple[type, ...]) -> dict[str, int]:
    """Live objects of each provider type: more than one is a duplicate."""

    counts = dict.fromkeys((kind.__name__ for kind in types), 0)
    for item in gc.get_objects():
        if isinstance(item, types):
            counts[type(item).__name__] = counts.get(type(item).__name__, 0) + 1
    return counts


def _run_component(
    plan: dict[str, Any],
    handshake: _Handshake,
    worker: _Worker,
    settings: Any,
    images: Sequence[Any],
) -> None:
    component = plan["component"]
    lookups = int(plan["lookups"])
    idle = float(plan["idle_seconds"])
    texts: list[str] = list(plan.get("texts") or [])
    held: dict[str, Any] = {}
    records: dict[int, dict[str, Any]] = {}
    unstable: set[int] = set()
    use: Callable[[int], dict[str, Any]]
    calls: Callable[[], int] | None = None

    if component == "ocr":
        factory = _ocr_factory(settings, plan)
        worker.call(lambda: held.__setitem__("provider", _CountingOCR(factory())))
        def ocr_calls() -> int:
            return int(held["provider"].calls)

        calls = ocr_calls

        def use(index: int) -> dict[str, Any]:
            slot = index % len(images)
            record = worker.call(lambda: ocr_record(held["provider"].recognize(images[slot])))
            known = records.setdefault(slot, record)
            if known["digest"] != record["digest"]:
                unstable.add(slot)
            return {"regions": len(record["regions"]), "ocr": record["digest"], "input": slot}

    elif component == "kiwi":
        from hanly.kiwi_provider import KiwiProvider

        worker.call(lambda: held.__setitem__("provider", KiwiProvider()))

        def use(index: int) -> dict[str, Any]:
            analysis = worker.call(lambda: held["provider"].analyze(texts[index % len(texts)]))
            tokens = getattr(analysis, "tokens", analysis)
            return {"tokens": len(tokens)}

    elif component == "dictionary":
        from hanly.krdict_provider import KRDICTProvider

        worker.call(
            lambda: held.__setitem__("provider", KRDICTProvider(settings.krdict_path))
        )

        def use(index: int) -> dict[str, Any]:
            entries = worker.call(lambda: held["provider"].lookup(texts[index % len(texts)]))
            return {"entries": len(entries)}

    elif component == "synthetic":
        # Calibrates the method itself: a known allocation must be attributed
        # to its stage, and its release must be visible. An anonymous mapping
        # is returned to the system on close, unlike allocator-cached blocks.
        import mmap

        size = int(plan.get("synthetic_bytes", 64 * 2**20))

        def mapped() -> Any:
            mapping = mmap.mmap(-1, size)
            for offset in range(0, size, mmap.PAGESIZE):
                mapping[offset] = 1
            return mapping

        worker.call(lambda: held.__setitem__("provider", mapped()))

        def use(index: int) -> dict[str, Any]:
            return {"bytes": len(held["provider"])}

    else:
        raise SystemExit(f"unknown component {component!r}")

    handshake.report("load", component=component, ocr_variant=plan.get("ocr_variant"))
    before = calls() if calls else 0
    first = use(0)
    handshake.report(
        "first_use", **first, **({"ocr_calls": calls() - before} if calls else {}),
    )
    _repeat(handshake, "repeated_varied", lambda i: use(1 + i), lookups, calls)
    _repeat(handshake, "repeated_same", lambda _i: use(0), lookups, calls)
    time.sleep(idle)
    handshake.report(
        "idle", seconds=idle,
        **({"ocr_records": {str(k): v for k, v in sorted(records.items())},
            "ocr_unstable_inputs": sorted(unstable)} if component == "ocr" else {}),
    )

    def unload() -> None:
        close = getattr(held["provider"], "close", None)
        if callable(close):
            close()
        held.clear()
        gc.collect()

    worker.call(unload)
    handshake.report("unload")
    time.sleep(min(idle, 2.0))
    handshake.report("after_unload_idle")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    plan = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    run(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
