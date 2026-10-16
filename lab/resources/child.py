"""One resource experiment, run in a fresh interpreter and measured from outside.

``python -m lab.resources.child <plan.json>`` executes the plan's stages in
order. After each stage it writes one JSON line and blocks until the parent
answers, so the parent reads this process at an exact boundary while it is
idle. The child measures nothing about itself except latency and what it
returned; recognized text and pixels never leave it, only digests and counts.
"""

from __future__ import annotations

import gc
import hashlib
import json
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

#: The order every sequence experiment follows; components stop where the
#: plan says. Stage names are the report's vocabulary.
SEQUENCE_STAGES = (
    "interpreter",
    "import_runtime",
    "runtime_validation",
    "load_ocr",
    "load_kiwi",
    "load_dictionary",
    "assemble_worker",
    "first_lookup",
    "repeated_varied",
    "repeated_same",
    "idle",
    "unload",
    "after_unload_idle",
)
COMPONENT_STAGES = (
    "interpreter",
    "import_runtime",
    "runtime_validation",
    "load",
    "first_use",
    "repeated_varied",
    "repeated_same",
    "idle",
    "unload",
    "after_unload_idle",
)
COMPONENTS = ("ocr", "kiwi", "dictionary", "synthetic")


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


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _result_digest(result: Any) -> tuple[str, str]:
    """(status, digest) of a lookup result: what it decided, never its text."""

    status = str(result.status.value)
    shape = {
        "status": status,
        "entries": [
            [entry.entry_id or entry.headword, entry.part_of_speech]
            for entry in result.entries
        ],
    }
    return status, _digest(shape)


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
) -> None:
    for index in range(count):
        started = time.perf_counter_ns()
        detail = work(index)
        handshake.tick(stage, index, time.perf_counter_ns() - started, **detail)
    handshake.report(stage, count=count)


@contextmanager
def _collected() -> Iterator[None]:
    yield
    gc.collect()


def run(plan: dict[str, Any]) -> None:
    handshake = _Handshake()
    handshake.report("interpreter")

    from dataclasses import replace

    from hanly import PixelFormat, Point, ROIImage
    from hanly_app.config import OCRBackend
    from hanly_app.lookup.controller import LookupRequest
    from hanly_app.lookup.process import _ocr_provider_factory
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
    lookups = int(plan["lookups"])
    idle = float(plan["idle_seconds"])

    if plan["mode"] == "component":
        _run_component(plan, handshake, settings, _ocr_provider_factory, images, lookups, idle)
        return

    from hanly.kiwi_provider import KiwiProvider
    from hanly.krdict_provider import KRDICTProvider
    from hanly_app.composition import create_lookup_worker_factory

    # One owner for everything loaded, so unloading is one visible clear.
    held: dict[str, Any] = {}
    held["ocr"] = _ocr_provider_factory(settings)()
    handshake.report("load_ocr", backend=settings.ocr_backend.value)
    held["kiwi"] = KiwiProvider()
    handshake.report("load_kiwi")
    held["dictionary"] = KRDICTProvider(settings.krdict_path)
    handshake.report("load_dictionary")

    # The app's child hands the worker factories; these return the instances
    # already measured, so assembly is the pipeline, caches and prewarming.
    held["worker"] = create_lookup_worker_factory(
        lambda: held["ocr"], lambda: held["kiwi"], lambda: held["dictionary"],
        confidence_threshold=settings.confidence_threshold,
        skip_flat_rois=settings.skip_flat_rois,
        ocr_backend=settings.ocr_backend.value,
    )()
    provider_types = tuple(
        type(held[name]) for name in ("ocr", "kiwi", "dictionary")
    )
    handshake.report("assemble_worker", instances=_instances(provider_types))

    request_ids = iter(range(1, 1_000_000))

    def lookup(index: int) -> dict[str, Any]:
        request = LookupRequest(next(request_ids), images[index], targets[index])
        status, digest = _result_digest(held["worker"](request))
        return {"status": status, "digest": digest, "input": index}

    def varied(index: int) -> dict[str, Any]:
        # Index 0 is the first lookup's input and already cached, so varied
        # work cycles through the rest; only the first pass is fresh.
        others = max(1, len(images) - 1)
        cache = "fresh" if index < others else "repeat"
        return lookup(1 + index % others if len(images) > 1 else 0) | {"cache": cache}

    handshake.report("first_lookup", **lookup(0))
    _repeat(handshake, "repeated_varied", varied, lookups)
    _repeat(handshake, "repeated_same", lambda _i: lookup(0) | {"cache": "hit"}, lookups)

    time.sleep(idle)
    handshake.report("idle", seconds=idle, instances=_instances(provider_types))

    with _collected():
        # The worker closes the providers it was handed.
        held.pop("worker").close()
        held.clear()
    handshake.report("unload", instances=_instances(provider_types))
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
    settings: Any,
    ocr_factory: Callable[[Any], Callable[[], Any]],
    images: Sequence[Any],
    lookups: int,
    idle: float,
) -> None:
    component = plan["component"]
    texts: list[str] = list(plan.get("texts") or [])
    held: dict[str, Any] = {}
    use: Callable[[int], dict[str, Any]]

    if component == "ocr":
        held["provider"] = ocr_factory(settings)()

        def use(index: int) -> dict[str, Any]:
            regions = held["provider"].recognize(images[index % len(images)])
            return {"regions": len(regions)}

    elif component == "kiwi":
        from hanly.kiwi_provider import KiwiProvider

        held["provider"] = KiwiProvider()

        def use(index: int) -> dict[str, Any]:
            analysis = held["provider"].analyze(texts[index % len(texts)])
            tokens = getattr(analysis, "tokens", analysis)
            return {"tokens": len(tokens)}

    elif component == "dictionary":
        from hanly.krdict_provider import KRDICTProvider

        held["provider"] = KRDICTProvider(settings.krdict_path)

        def use(index: int) -> dict[str, Any]:
            return {"entries": len(held["provider"].lookup(texts[index % len(texts)]))}

    elif component == "synthetic":
        # Calibrates the method itself: a known allocation must be attributed
        # to its stage, and its release must be visible. An anonymous mapping
        # is returned to the system on close, unlike allocator-cached blocks.
        import mmap

        size = int(plan.get("synthetic_bytes", 64 * 2**20))
        mapping = mmap.mmap(-1, size)
        for offset in range(0, size, mmap.PAGESIZE):
            mapping[offset] = 1
        held["provider"] = mapping

        def use(index: int) -> dict[str, Any]:
            return {"bytes": len(held["provider"])}

    else:
        raise SystemExit(f"unknown component {component!r}")

    handshake.report("load", component=component)
    handshake.report("first_use", **use(0))
    _repeat(handshake, "repeated_varied", lambda i: use(1 + i), lookups)
    _repeat(handshake, "repeated_same", lambda _i: use(0), lookups)
    time.sleep(idle)
    handshake.report("idle", seconds=idle)

    with _collected():
        close = getattr(held["provider"], "close", None)
        if callable(close):
            close()
        held.clear()
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
