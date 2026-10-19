"""Measure a supplied ROI with the native desktop's real hover and popup path."""

from __future__ import annotations

import json
import math
import statistics
import tempfile
from pathlib import Path
from typing import Any


def run_real_hover(args: Any) -> int:
    """Create a temporary private corpus and supervise a native stress run."""

    from ..cli import Point, prepare_roi
    from .runner import SessionOptions, run_session

    if not args.expected_text or not any(_is_hangul(char) for char in args.expected_text):
        raise SystemExit("lab: --expected-text must state the Korean surface under the pointer")
    if not 20 <= args.dwell_ms <= 2000:
        raise SystemExit("lab: --dwell-ms must be between 20 and 2000")
    if args.warmup < 0 or args.samples < 1:
        raise SystemExit("lab: use zero or more warm-ups and at least one measured sample")
    if args.timeout <= 0:
        raise SystemExit("lab: --timeout must be positive")

    image, target, prepared, _transformation = prepare_roi(
        args.image,
        target=Point(args.target_x, args.target_y),
        size=args.roi_size,
    )
    output_root = args.output_root.expanduser().resolve()
    before = set(output_root.glob("*-stress")) if output_root.is_dir() else set()
    total = args.warmup + args.samples
    try:
        with tempfile.TemporaryDirectory(prefix="hanly-real-hover-") as temporary:
            fixture_root = Path(temporary)
            prepared.save(fixture_root / "input.png", format="PNG")
            manifest = fixture_root / "manifest.json"
            _write_private_manifest(
                manifest,
                image="input.png",
                width=image.width,
                height=image.height,
                target=(target.x, target.y),
                surface=args.expected_text,
            )
            exit_code = run_session(
                SessionOptions(
                    mode="stress",
                    runtime_config=args.config,
                    desktop=args.desktop,
                    output_root=output_root,
                    roi_size=(image.width, image.height),
                    hover_delay_ms=round(args.dwell_ms),
                    cpu_threads=args.cpu_threads,
                    hover_timeout=args.timeout,
                    corpus=manifest,
                    repeats=total,
                    open_report=False,
                )
            )
    finally:
        prepared.close()

    runs = sorted(
        output_root.glob("*-stress"),
        key=lambda path: path.name,
    ) if output_root.is_dir() else []
    created = [path for path in runs if path not in before and (path / "events.jsonl").is_file()]
    if not created:
        print("lab: native hover run did not produce a trace recording")
        return exit_code or 1

    run_dir = created[-1]
    rows = _stress_records(run_dir / "events.jsonl")
    measured = rows[args.warmup :]
    visible = [
        float(row["hover_to_popup_ms"])
        for row in measured
        if row.get("popup") == "SUCCESS"
        and isinstance(row.get("hover_to_popup_ms"), (int, float))
    ]
    matching = sum(row.get("verdict") == "target_selected" for row in measured)
    summary = {
        "measurement": "native_tauri_popup_trace",
        "planned": total,
        "warmup": args.warmup,
        "measured": len(measured),
        "target_selected": matching,
        "visible_popup_samples": len(visible),
        "popup_latency_ms": _latency_summary(visible),
        "correctness": "passed" if measured and matching == len(measured) else "failed",
    }
    (run_dir / "real_hover_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    latency = summary["popup_latency_ms"]
    if latency is None:
        print(
            f"lab: native hover produced {matching}/{len(measured)} expected selections; "
            "no visible popup timing"
        )
    else:
        print(
            "lab: native popup hover-to-visible p50={p50:.1f} ms p95={p95:.1f} ms; "
            "expected selections {matching}/{measured}; evidence {_path}".format(
                p50=latency["p50"],
                p95=latency["p95"],
                matching=matching,
                measured=len(measured),
                _path=run_dir,
            )
        )
    return 0 if exit_code == 0 and summary["correctness"] == "passed" and visible else 1


def _write_private_manifest(
    path: Path,
    *,
    image: str,
    width: int,
    height: int,
    target: tuple[float, float],
    surface: str,
) -> None:
    """Write one local-only case; the temporary image and text are never retained."""

    payload = {
        "schema_version": 2,
        "distribution": "local",
        "description": "Temporary controlled ROI for native hover measurement.",
        "cases": [
            {
                "id": "real-hover",
                "image": image,
                "provenance": "local_private",
                "expected_surface": surface,
                "expected_target": [target[0], target[1]],
                "truth": {
                    "text_present": True,
                    "korean_present": True,
                    "target": "surface",
                    "regions": "missing",
                },
                "notes": f"{width}x{height} private input; see no pixels in the report.",
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def _stress_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "stress_result" and event.get("family") == "corpus":
            records.append(event)
    return records


def _latency_summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "p50": round(statistics.median(ordered), 3),
        "p95": round(ordered[p95_index], 3),
    }


def _is_hangul(character: str) -> bool:
    return "\u1100" <= character <= "\u11ff" or "\uac00" <= character <= "\ud7a3"
