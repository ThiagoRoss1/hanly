"""Run one controlled corpus through each available OCR backend, each in its own process.

Every backend gets a fresh ``python -m lab ocr-campaign --mode ocr-only`` child,
so initialization, memory and failures belong to that backend alone, and each
child scores the same corpus by its own production provider. The parent only
compares what the children recorded: whether both saw identical inputs, which
cases every backend handled alike, and which only one got right. It does not
choose a winner, and it does not require a backend this machine lacks.

Production output is the evidence here. A staged EasyOCR inspection of the
same image is a replay for comparison, never the original invocation's
internals, and is not mixed into this report.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .corpus import fingerprint, load_corpus
from .metadata import build_metadata

BACKENDS = ("easyocr", "vision")
CHILD_TIMEOUT_SECONDS = 1800
_UNAVAILABLE_MARKERS = ("provides no Apple Vision recognizer", "No module named")


def default_backends() -> tuple[str, ...]:
    """Backends worth trying here; a child still decides whether one is usable."""

    return BACKENDS if sys.platform == "darwin" else ("easyocr",)


def run_differential(
    manifest: Path,
    backends: tuple[str, ...],
    *,
    output_root: Path,
    warmup: int,
    samples: int,
    config: Path | None = None,
    cpu_threads: int | None = None,
    timeout: float = CHILD_TIMEOUT_SECONDS,
) -> tuple[Path, dict[str, Any]]:
    """Run every backend's child, then compare what they recorded."""

    corpus = load_corpus(manifest)
    expected = fingerprint(corpus)
    metadata = build_metadata(
        repo_root=Path.cwd(),
        kind="ocr_differential",
        config={
            "mode": "ocr-only",
            "backends": list(backends),
            "manifest": str(manifest),
            "warmup": warmup,
            "samples": samples,
            "cpu_threads": cpu_threads,
        },
        scenario={"name": "ocr_differential", "endpoint": "normalized_ocr_results"},
    )
    run_dir = output_root / str(metadata["run_id"])
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", "utf-8")

    children: dict[str, dict[str, Any]] = {}
    status = "complete"
    try:
        for backend in backends:
            children[backend] = _child(
                backend, manifest, run_dir, warmup, samples, config, cpu_threads, timeout
            )
    except KeyboardInterrupt:
        # subprocess.run has already killed the running child.
        status = "interrupted"
    report = compare(children, expected)
    report.update(status=status, corpus_fingerprint=expected, requested=list(backends))
    (run_dir / "differential.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    (run_dir / "differential.md").write_text(markdown(report), "utf-8")
    (run_dir / "summary.json").write_text(
        json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2) + "\n", "utf-8"
    )
    return run_dir, report


def _child(
    backend: str,
    manifest: Path,
    run_dir: Path,
    warmup: int,
    samples: int,
    config: Path | None,
    cpu_threads: int | None,
    timeout: float,
) -> dict[str, Any]:
    root = run_dir / "backends" / backend
    command = [
        sys.executable,
        "-m",
        "lab",
        "ocr-campaign",
        "--mode",
        "ocr-only",
        "--backend",
        backend,
        "--manifest",
        str(manifest),
        "--warmup",
        str(warmup),
        "--repeats",
        str(samples),
        "--output-root",
        str(root),
    ]
    if config is not None:
        command += ["--config", str(config)]
    if cpu_threads is not None:
        command += ["--cpu-threads", str(cpu_threads)]
    try:
        finished = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"state": "timed_out", "timeout_seconds": timeout}
    runs = sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []
    if finished.returncode != 0 or len(runs) != 1:
        unavailable = any(marker in finished.stderr for marker in _UNAVAILABLE_MARKERS)
        # Only the exception type reaches the report; raw output stays out of it.
        last = finished.stderr.strip().splitlines()[-1:] or [""]
        return {
            "state": "unavailable" if unavailable else "initialization_failed",
            "exit_code": finished.returncode,
            "error_type": last[0].split(":", 1)[0][:80],
        }
    return {"state": "ran", "run": runs[0].relative_to(run_dir).as_posix(), "dir": runs[0]}


def compare(children: dict[str, dict[str, Any]], expected: str | None) -> dict[str, Any]:
    """Shared and backend-specific observations, per case, from the children's records."""

    ran = {name: child for name, child in children.items() if child["state"] == "ran"}
    loaded = {name: _load(child["dir"]) for name, child in ran.items()}
    backends: dict[str, Any] = {}
    for name, child in children.items():
        entry = {key: value for key, value in child.items() if key != "dir"}
        if name in loaded:
            summary, inventory, _ = loaded[name]
            entry.update(
                identical_inputs=inventory.get("fingerprint") == expected and expected is not None,
                initialization=summary.get("latency", {}).get("cold"),
                memory=summary.get("memory"),
                errors=summary.get("errors"),
                stability=summary.get("stability", {}).get("classes"),
            )
        backends[name] = entry

    case_ids = sorted({case for _, _, cases in loaded.values() for case in cases})
    cases = {case: _case(case, loaded) for case in case_ids}
    return {
        "backends": backends,
        "categories": dict(Counter(row["category"] for row in cases.values()).most_common()),
        "cases": cases,
        "note": "production ocr-only output per backend; no winner is chosen",
    }


Loaded = tuple[dict[str, Any], dict[str, Any], dict[str, Any]]


def _case(case: str, loaded: dict[str, Loaded]) -> dict[str, Any]:
    per = {name: cases.get(case) for name, (_, _, cases) in loaded.items()}
    present = {name: row for name, row in per.items() if row is not None}
    judged = {name: row["ok"] for name, row in present.items() if row["ok"] is not None}
    if len(present) < 2:
        category = "single_backend"
    elif len(judged) < len(present):
        category = "not_judged"
    elif all(judged.values()):
        category = "shared_pass"
    elif not any(judged.values()):
        stages = {row["stage"] for row in present.values()}
        category = "shared_failure_same_stage" if len(stages) == 1 else "shared_failure"
    else:
        category = "backend_specific"
    outputs = {row["output"] for row in present.values()}
    return {
        "category": category,
        "passed_by": sorted(name for name, ok in judged.items() if ok),
        "outputs_differ": len(outputs) > 1,
        "backends": present,
    }


def _load(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    summary = json.loads((run_dir / "summary.json").read_text("utf-8"))
    inventory = json.loads((run_dir / "corpus-inventory.json").read_text("utf-8"))
    stability = summary.get("stability", {}).get("cases", {})
    warm: dict[str, list[dict[str, Any]]] = {}
    with (run_dir / "samples.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("condition") == "warm":
                warm.setdefault(str(row["case_id"]), []).append(row)
    cases = {}
    for case, rows in warm.items():
        outputs = Counter(str(row.get("text")) for row in rows)
        stages = Counter(str(row.get("first_bad_stage")) for row in rows)
        state = stability.get(case, {})
        classification = state.get("classification")
        cases[case] = {
            "ok": True
            if classification in {"stable_correct", "correct_with_varying_output"}
            else False
            if classification in {"stable_wrong", "wrong_with_varying_output"}
            else None,
            "classification": classification,
            "output": outputs.most_common(1)[0][0],
            "stage": stages.most_common(1)[0][0],
            "repetitions": len(rows),
        }
    return summary, inventory, cases


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# OCR backend differential",
        "",
        f"- status: {report['status']}; corpus {report['corpus_fingerprint']}",
        f"- {report['note']}",
        "",
        "## Backends",
        "",
    ]
    for name, entry in report["backends"].items():
        detail = (
            f"identical inputs {entry.get('identical_inputs')}, errors {entry.get('errors')}, "
            f"stability {entry.get('stability')}"
            if entry["state"] == "ran"
            else ", ".join(f"{k} {v}" for k, v in entry.items() if k != "state")
        )
        lines.append(f"- {name}: {entry['state']}; {detail}")
    lines += ["", "## Cases", "", f"- categories: {report['categories']}"]
    for category in ("backend_specific", "shared_failure", "shared_failure_same_stage"):
        names = [case for case, row in report["cases"].items() if row["category"] == category]
        if names:
            lines.append(f"- {category}: {', '.join(names[:60])}")
    specific = [
        f"{case} (passed by {', '.join(row['passed_by'])})"
        for case, row in report["cases"].items()
        if row["category"] == "backend_specific"
    ]
    if specific:
        lines += ["", "Passed by only some backends:", ""] + [f"- {item}" for item in specific]
    return "\n".join(lines) + "\n"


__all__ = ["BACKENDS", "compare", "default_backends", "markdown", "run_differential"]
