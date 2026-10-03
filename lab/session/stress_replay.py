"""Replay a stress campaign's failing regions through the production lookup worker.

A campaign run with ``--retain-fixture-images`` keeps, for each failing verified
hover, the region the app captured, re-grabbed from the lab's own static page
after the popup closed. Feeding that image through the same worker the lookup
child builds -- presence gate, cache, sensitive retry, the real recognizer,
Kiwi and KRDICT -- separates what OCR and the language stages do with those
pixels from anything live capture or presentation did.

Labelled as a lab re-capture replay: the pixels are the lab's re-grab of an owned
static page, not the app's own frame, and the replay is not the live invocation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPLAY_LABEL = "lab_recapture_production_worker_replay"


def replay_run(run_dir: Path, runtime_config: Path) -> dict[str, Any]:
    """Replay every saved region of one run; write and return ``replay.json``."""

    from hanly import PixelFormat, Point, ROIImage
    from hanly_app.lookup.controller import LookupRequest
    from hanly_app.runtime import load_runtime
    from PIL import Image

    results, points = _recorded(run_dir)
    runtime = load_runtime(runtime_config)
    worker = runtime.create_worker_factory()()
    rows = []
    try:
        for index, row in enumerate(results, start=1):
            name = row.get("replay_image")
            region = row.get("region")
            point = points.get(str(row.get("target")))
            if not name or not region or point is None:
                continue
            with Image.open(run_dir / "replay" / name) as source:
                rgb = source.convert("RGB")
                image = ROIImage(
                    width=rgb.width,
                    height=rgb.height,
                    pixel_format=PixelFormat.RGB_888,
                    data=rgb.tobytes(),
                )
            target = Point(point[0] - region[0], point[1] - region[1])
            outcome: Any = worker(LookupRequest(index, image, target))
            rows.append(_compare(row, outcome))
    finally:
        worker.close()
    from .runner import _git

    report = {
        "label": REPLAY_LABEL,
        "run": run_dir.name,
        # The code that replayed, which need not be the code that recorded the run.
        "commit": _git("rev-parse", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "rows": rows,
        "same_as_live": sum(1 for row in rows if row["same_as_live"]),
        "same_recognition": sum(1 for row in rows if row["same_recognition"]),
        "replayed": len(rows),
    }
    (run_dir / "replay.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def _recorded(run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, tuple[int, int]]]:
    results: list[dict[str, Any]] = []
    points: dict[str, tuple[int, int]] = {}
    with (run_dir / "events.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            if event.get("event") == "tour_target":
                points[str(event.get("target"))] = (int(event["x"]), int(event["y"]))
            elif event.get("event") == "stress_result":
                results.append(event)
    return results, points


def _compare(row: dict[str, Any], outcome: Any) -> dict[str, Any]:
    status = getattr(getattr(outcome, "status", None), "name", None)
    context = getattr(outcome, "context", None)
    entries = getattr(outcome, "entries", ()) or ()
    headword = getattr(entries[0], "headword", None) if entries else None
    selected = getattr(context, "text", None)
    recognized = [result.text for result in getattr(context, "ocr_results", ()) or ()]
    return {
        "target": row.get("target"),
        "family": row.get("family"),
        "expected": row.get("expected"),
        "live": {
            "verdict": row.get("verdict"),
            "status": row.get("status"),
            "selected": row.get("selected"),
            "headword": row.get("headword"),
            "recognized": row.get("recognized"),
        },
        "replay": {
            "status": status,
            "selected": selected,
            "headword": headword,
            "recognized": recognized,
        },
        # Same selection and status: the pixels alone produce the live outcome.
        "same_as_live": status == row.get("status") and selected == row.get("selected"),
        # Stricter: the recognizer read the same lines, not only the same word.
        "same_recognition": sorted(recognized) == sorted(row.get("recognized") or []),
        "replay_correct": headword is not None and headword == row.get("expected"),
    }


__all__ = ["REPLAY_LABEL", "replay_run"]
