"""Compare EasyOCR options and oracle line geometry on authored Lab images.

Oracle boxes isolate crop sensitivity; they are ground truth unavailable to the
product, never a candidate implementation. The runner retains raw answers and
scores separately and refuses private screen inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

from hanly import OCRResult, Point
from hanly.easyocr_provider import (
    EasyOCRConfig,
    EasyOCRProvider,
    easyocr_image_from_roi,
    normalize_easyocr_results,
)
from hanly.word_resolver import WordResolver

from .corpus import CorpusCase, load_corpus
from .easyocr_stages import COMPARISON_REPLAY, compare_to_live, run_staged_easyocr
from .metadata import build_metadata
from .ocr_benchmark import current_rss, load_case_image, peak_rss
from .ocr_metrics import normalize

DEFAULT_VARIANTS = ("product", "sensitive", "beamsearch", "line-oracle")
VARIANTS = (*DEFAULT_VARIANTS, "line-oracle-padded", "model-alphabet")


def select_cases(cases: tuple[CorpusCase, ...], limit: int) -> list[CorpusCase]:
    """Select a deterministic font-balanced diagnostic subset, independent of errors."""

    if limit < 1:
        raise ValueError("limit must be positive")
    if any(case.provenance != "local_synthetic" for case in cases):
        raise ValueError("this audit accepts only local_synthetic Lab images")
    buckets: dict[str, list[CorpusCase]] = defaultdict(list)
    for case in cases:
        buckets[str(case.source.get("font_name", "unknown"))].append(case)
    for bucket in buckets.values():
        bucket.sort(key=lambda case: hashlib.sha256(case.case_id.encode()).hexdigest())

    selected: list[CorpusCase] = []
    while len(selected) < min(limit, len(cases)):
        for name in sorted(buckets):
            if buckets[name] and len(selected) < limit:
                selected.append(buckets[name].pop())
    return selected


def assess(case: CorpusCase, regions: tuple[OCRResult, ...]) -> dict[str, Any]:
    """Keep strict text/token scores distinct from diagnostic error categories."""

    target = None if case.expected_target is None else Point(*case.expected_target)
    resolved = WordResolver.resolve(regions, target)
    text = " ".join(region.text for region in regions)
    token_correct = None if case.expected_surface is None else (
        resolved is not None and normalize(resolved) == normalize(case.expected_surface)
    )
    line_correct = None if case.expected_text is None else (
        normalize(text) == normalize(case.expected_text)
    )
    if token_correct is None:
        category = "unjudged"
    elif token_correct:
        category = "exact_token"
    elif resolved is None:
        category = "no_target_selection"
    else:
        expected_hangul = _hangul(case.expected_surface or "")
        category = "non_hangul_difference" if _hangul(resolved) == expected_hangul else (
            "changed_hangul"
        )
    return {
        "text": text, "resolved": resolved,
        "token_correct": token_correct, "line_correct": line_correct,
        "category": category,
    }


def _hangul(text: str) -> str:
    return "".join(char for char in text if "가" <= char <= "힣")


def alphabet_report(
    cases: list[CorpusCase], model: str, allowed: str,
) -> dict[str, Any]:
    """Distinguish impossible model outputs from characters masked by language policy."""

    model_set, allowed_set = set(model), set(allowed)
    missing: list[dict[str, str]] = []
    masked: list[dict[str, str]] = []
    for case in cases:
        for field in ("expected_surface", "expected_text"):
            text = getattr(case, field) or ""
            characters = set(_hangul(text))
            for difference, rows in (
                (characters - model_set, missing),
                ((characters & model_set) - allowed_set, masked),
            ):
                if difference:
                    rows.append({"case_id": case.case_id, "field": field,
                                 "characters": "".join(sorted(difference))})
    return {
        "model_hangul": len(set(_hangul(model))),
        "missing_from_model": missing, "masked_by_language": masked,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate measured repetitions without hiding failed invocations."""

    output: dict[str, Any] = {}
    for variant in sorted({row["variant"] for row in rows}):
        selected = [row for row in rows if row["variant"] == variant]
        completed = [row for row in selected if row.get("error") is None]
        durations = sorted(row["elapsed_ns"] / 1e6 for row in completed)
        output[variant] = {
            "samples": len(selected), "errors": len(selected) - len(completed),
            "token_correct": sum(row.get("token_correct") is True for row in completed),
            "token_judged": sum(row.get("token_correct") is not None for row in completed),
            "line_correct": sum(row.get("line_correct") is True for row in completed),
            "categories": dict(Counter(row["category"] for row in completed)),
            "latency_ms": None if not durations else {
                "p50": statistics.median(durations),
                "p95": durations[math.ceil(len(durations) * .95) - 1],
            },
        }
    return output


def _oracle(
    reader: Any, case: CorpusCase, image: Any, *, padded: bool = False,
) -> tuple[OCRResult, ...]:
    from easyocr.utils import reformat_input

    if not case.expected_regions:
        raise ValueError("oracle line geometry is missing")
    _, gray = reformat_input(easyocr_image_from_roi(image))
    boxes = []
    for box in case.expected_regions:
        margin = (box.bottom - box.top) * .1 if padded else 0
        boxes.append([
            max(0, math.floor(box.left - margin)),
            min(image.width, math.ceil(box.right + margin)),
            max(0, math.floor(box.top - margin)),
            min(image.height, math.ceil(box.bottom + margin)),
        ])
    return normalize_easyocr_results(reader.recognize(
        gray, horizontal_list=boxes, free_list=[], reformat=False,
    ))


def _prepare_provider(
    args: argparse.Namespace, cases: list[CorpusCase], output: Path,
) -> EasyOCRProvider:
    """Record the exact experiment inputs and the initialized product runtime."""

    config = EasyOCRConfig(
        download_enabled=False, cpu_threads=args.cpu_threads,
        extra_options={"quantize": not args.no_quantize},
    )
    metadata = build_metadata(
        repo_root=Path.cwd(), config={
            "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
            "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "variants": args.variants, "samples": args.samples,
            "selected_cases": [case.case_id for case in cases],
            "cpu_threads": args.cpu_threads,
            "quantize": not args.no_quantize,
        }, scenario={"name": "easyocr_crop_and_decoder_audit"},
        versions={name: version(name) for name in ("easyocr", "torch", "Pillow")},
    )
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    baseline_rss = current_rss()
    started = time.perf_counter()
    provider = EasyOCRProvider(config)
    initialization_s = time.perf_counter() - started
    reader = provider._engine
    import torch

    runtime = {
        "device": str(reader.device), "torch_threads": torch.get_num_threads(),
        "reader_options": config.to_reader_kwargs(),
        "initialization_s": initialization_s, "baseline_rss": baseline_rss,
        "initialized_rss": current_rss(),
        "models": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in Path(reader.model_storage_directory).glob("*.pth")
        },
        "oracle_is_deployable": False,
        "model_characters": reader.character,
        "allowed_characters": reader.lang_char,
        "alphabet": alphabet_report(cases, reader.character, reader.lang_char),
    }
    (output / "runtime.json").write_text(json.dumps(runtime, indent=2) + "\n")
    provider.prewarm()
    return provider


def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    """Write immutable inputs, effective runtime, raw samples and diagnostic stages."""

    corpus = load_corpus(args.manifest)
    cases = select_cases(corpus.cases, args.limit)
    if not cases:
        raise ValueError("the corpus has no cases")
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=False)
    provider = _prepare_provider(args, cases, output)
    reader = provider._engine
    sensitive = provider.sensitive_variant()
    rows: list[dict[str, Any]] = []
    with (output / "samples.jsonl").open("x", encoding="utf-8") as samples:
        for index, case in enumerate(cases):
            image = load_case_image(case)
            live: tuple[OCRResult, ...] | None = None
            for iteration in range(args.samples):
                # Alternate order to avoid assigning every cold/cache effect to one option.
                variants = args.variants if (index + iteration) % 2 == 0 else args.variants[::-1]
                for variant in variants:
                    row: dict[str, Any] = {
                        "case_id": case.case_id, "iteration": iteration, "variant": variant,
                        "image_sha256": hashlib.sha256(case.image.read_bytes()).hexdigest(),
                        "font": case.source.get("font_name"),
                        "expected_surface": case.expected_surface,
                        "expected_text": case.expected_text,
                    }
                    started_ns = time.perf_counter_ns()
                    try:
                        if variant == "product":
                            regions = provider.recognize(image)
                            live = regions
                        elif variant == "sensitive":
                            if sensitive is None:
                                raise ValueError("sensitive options are disabled")
                            regions = sensitive.recognize(image)
                        elif variant == "beamsearch":
                            regions = normalize_easyocr_results(reader.readtext(
                                easyocr_image_from_roi(image), decoder="beamsearch", beamWidth=5,
                            ))
                        elif variant == "model-alphabet":
                            regions = normalize_easyocr_results(reader.readtext(
                                easyocr_image_from_roi(image), allowlist=reader.character,
                            ))
                        else:
                            regions = _oracle(
                                reader, case, image, padded=variant == "line-oracle-padded",
                            )
                        row["elapsed_ns"] = time.perf_counter_ns() - started_ns
                        row.update(assess(case, regions))
                        row["regions"] = [asdict(region) for region in regions]
                    except Exception as error:
                        row.update(error=f"{type(error).__name__}: {error}",
                                   elapsed_ns=time.perf_counter_ns() - started_ns)
                    rows.append(row)
                    samples.write(json.dumps(row, ensure_ascii=False) + "\n")
                    samples.flush()

            if live is not None:
                staged = run_staged_easyocr(reader, image, evidence_class=COMPARISON_REPLAY)
                comparison = compare_to_live(live, staged)
                stage = {
                    "case_id": case.case_id, "matches_live": comparison.matches,
                    "differences": comparison.differences,
                    "detection_ns": staged.detection_ns, "recognition_ns": staged.recognition_ns,
                    "regions": [{
                        "quad": region.quad, "text": region.text,
                        "confidence": region.confidence,
                        "crop_size": None if region.crop is None else (
                            region.crop.width, region.crop.height),
                        "unavailable": region.unavailable_reason,
                    } for region in staged.regions],
                }
                with (output / "stages.jsonl").open("a", encoding="utf-8") as stages:
                    stages.write(json.dumps(stage, ensure_ascii=False) + "\n")
            print(f"{index + 1}/{len(cases)} {case.case_id}", flush=True)
    summary = {
        "cases": len(cases), "variants": summarize(rows),
        "memory": {"steady_rss": current_rss(), "peak_rss": peak_rss()},
        "limits": ["Synthetic authored images, not native capture or Windows acceptance.",
                   "Font-balanced diagnostic subset; not a population accuracy estimate.",
                   "Oracle line boxes are ground truth, not a production detector."],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--cpu-threads", type=int, choices=range(1, 65), default=4)
    parser.add_argument("--no-quantize", action="store_true")
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(DEFAULT_VARIANTS))
    args = parser.parse_args()
    if not 1 <= args.samples <= 10:
        parser.error("samples must be between 1 and 10")
    print(json.dumps(run_audit(args), indent=2))


if __name__ == "__main__":
    main()
