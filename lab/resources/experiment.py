"""Plan, run and record one resource-attribution experiment.

Inputs are Lab-authored: minibook lines rendered in an installed Hangul face.
Their pixels live only in a temporary file the children read and are deleted
with it; the run keeps digests, counts and measurements.
"""

from __future__ import annotations

import hashlib
import json
import platform
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

from ..metadata import build_metadata
from .metrics import UNAVAILABLE_REASONS, primary_memory_name
from .stages import PROTOCOL, aggregate, attribute, run_child

#: What a run's scenario is called; ``identity`` recognizes it by this name.
SCENARIO = "resource_attribution"

#: Libraries whose versions decide whether two experiments measured the same code.
VERSIONED_PACKAGES = (
    "hanly", "hanly-app", "kiwipiepy", "kiwipiepy_model", "easyocr", "torch",
    "numpy", "Pillow", "psutil", "pyobjc-framework-Vision",
)


#: Pillow modes the renderer produces, as the ROI pixel formats Hanly accepts.
_PIXEL_FORMATS = {"L": "GRAYSCALE_8", "RGB": "RGB_888"}


@dataclass(frozen=True)
class ExperimentPlan:
    """Everything that decides what an experiment measures."""

    runtime_config: Path | None
    ocr_backend: str
    lookups: int = 12
    idle_seconds: float = 5.0
    repeats: int = 3
    inputs: int = 8
    #: ``sequence`` alone, or isolated components measured one per process.
    components: tuple[str, ...] = ()
    calibrate: bool = True
    #: Unrecorded children run first, so every recorded repeat meets the same
    #: warm file cache and a cold disk is never mistaken for a code change.
    warmup_runs: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "ocr_backend": self.ocr_backend,
            "lookups": self.lookups,
            "idle_seconds": self.idle_seconds,
            "repeats": self.repeats,
            "inputs": self.inputs,
            "components": list(self.components),
            "calibrate": self.calibrate,
            "warmup_runs": self.warmup_runs,
        }


@dataclass(frozen=True)
class RenderedInputs:
    path: Path
    texts: tuple[str, ...]
    lemmas: tuple[str, ...]
    digest: str
    face: str


def render_inputs(count: int, directory: Path) -> RenderedInputs:
    """Render ``count`` minibook lines with the pointer on a known target."""

    from ..minibook import load_minibook
    from ..synthetic_ocr import SampleSpec, discover_faces, render_sample

    faces = discover_faces()
    if not faces:
        raise RuntimeError("no installed face draws Hangul; resource inputs cannot be rendered")
    face = faces[0]
    book = load_minibook()
    targets = [
        target for target in book.targets
        if not target.refuse and all("가" <= ch <= "힣" for ch in target.surface)
    ][:count]
    if not targets:
        raise RuntimeError("the minibook has no Korean target to render")

    index: list[dict[str, Any]] = []
    blob = bytearray()
    digest = hashlib.sha256(f"{face.family}:{face.index}".encode())
    for number, target in enumerate(targets):
        line = book.lines[target.line]
        sample = render_sample(SampleSpec(
            case_id=f"resource-{number}",
            text=line,
            font=face.spec(),
            font_size=20,
            target_index=target.start + target.cursor,
        ))
        point = sample.metadata.get("target_point") or (sample.width / 2, sample.height / 2)
        pixel_format = _PIXEL_FORMATS.get(sample.mode)
        if pixel_format is None:
            raise RuntimeError(f"rendered mode {sample.mode} has no ROI pixel format")
        index.append({
            "width": sample.width, "height": sample.height, "pixel_format": pixel_format,
            "target_x": float(point[0]), "target_y": float(point[1]),
            "offset": len(blob), "length": len(sample.data),
        })
        blob.extend(sample.data)
        digest.update(sample.data)
    path = directory / "inputs.bin"
    with path.open("wb") as stream:
        stream.write(json.dumps(index).encode("utf-8") + b"\n")
        stream.write(bytes(blob))
    lemmas = tuple(target.lemma or target.surface for target in targets)
    return RenderedInputs(
        path=path,
        texts=tuple(book.lines[target.line] for target in targets),
        lemmas=lemmas,
        digest="sha256:" + digest.hexdigest()[:16],
        face=f"{face.family}#{face.index}",
    )


def versions() -> dict[str, str | None]:
    found: dict[str, str | None] = {"python": platform.python_version()}
    for name in VERSIONED_PACKAGES:
        try:
            found[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            found[name] = None
    return found


def run_experiment(
    plan: ExperimentPlan,
    output_root: Path,
    *,
    report: Callable[[str], None] = print,
) -> Path:
    """Run every planned child, write the evidence, and return the run directory."""

    with tempfile.TemporaryDirectory(prefix="hanly-resources-") as scratch:
        scratch_dir = Path(scratch)
        inputs = render_inputs(plan.inputs, scratch_dir) if plan.runtime_config else None
        run_dir = output_root / f"{datetime.now():%Y%m%d-%H%M%S}-resources"
        run_dir.mkdir(parents=True, exist_ok=False)
        metadata = build_metadata(
            run_id=run_dir.name,
            kind=SCENARIO,
            repo_root=Path.cwd(),
            config={
                **plan.as_dict(),
                "protocol": PROTOCOL,
                "primary_memory": primary_memory_name(),
                "input_digest": inputs.digest if inputs else None,
                "input_face": inputs.face if inputs else None,
            },
            scenario={"name": SCENARIO, "experiments": _labels(plan)},
            versions=versions(),
        )
        (run_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        experiments: dict[str, list[dict[str, Any]]] = {}
        for label, child_plan in _child_plans(plan, inputs):
            for warmup in range(plan.warmup_runs):
                report(f"{label}: warm-up {warmup + 1}/{plan.warmup_runs} (not recorded)")
                run_child(
                    child_plan, scratch_dir / f"{label}.json", run_dir / "children.log",
                    label=label,
                )
            for repeat in range(plan.repeats):
                report(f"{label}: repeat {repeat + 1}/{plan.repeats}")
                record = run_child(
                    child_plan,
                    scratch_dir / f"{label}.json",
                    run_dir / "children.log",
                    label=label,
                )
                result = attribute(record)
                result["repeat"] = repeat
                experiments.setdefault(label, []).append(result)
                if result["error"]:
                    report(f"{label}: {result['error']}")

    produced = {
        key
        for runs in experiments.values()
        for run in runs
        for key, present in run["available"].items()
        if present
    }
    summary = {
        "protocol": PROTOCOL,
        "primary_memory": primary_memory_name(),
        "unavailable": {
            key: reason for key, reason in UNAVAILABLE_REASONS.items() if key not in produced
        },
        "plan": plan.as_dict(),
        "input_digest": metadata["config"]["input_digest"],
        "experiments": {
            label: {"repeats": runs, "aggregate": aggregate(runs)}
            for label, runs in experiments.items()
        },
        "interaction": _interaction(experiments),
        "correctness": _correctness(experiments.get("sequence", [])),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    from .report import write_summary

    write_summary(run_dir, metadata, summary)
    return run_dir


def _labels(plan: ExperimentPlan) -> list[str]:
    labels = ["calibration"] if plan.calibrate else []
    if plan.runtime_config is not None:
        labels.append("sequence")
        labels += [f"component:{name}" for name in plan.components]
    return labels


def _child_plans(
    plan: ExperimentPlan, inputs: RenderedInputs | None
) -> list[tuple[str, dict[str, Any]]]:
    base = {
        "runtime_config": str(plan.runtime_config) if plan.runtime_config else None,
        "ocr_backend": plan.ocr_backend,
        "inputs_path": str(inputs.path) if inputs else None,
        "lookups": plan.lookups,
        "idle_seconds": plan.idle_seconds,
    }
    plans: list[tuple[str, dict[str, Any]]] = []
    if plan.calibrate:
        plans.append(("calibration", {
            **base, "mode": "component", "component": "synthetic",
            "runtime_config": None, "inputs_path": None, "synthetic_bytes": 64 * 2**20,
        }))
    if inputs is None:
        return plans
    plans.append(("sequence", {**base, "mode": "sequence"}))
    for component in plan.components:
        texts: Sequence[str] = inputs.lemmas if component == "dictionary" else inputs.texts
        plans.append((f"component:{component}", {
            **base, "mode": "component", "component": component, "texts": list(texts),
        }))
    return plans


def _interaction(experiments: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    """Each component's cost to its first operation alone, against the whole.

    Providers may defer loading to first use, so the comparison runs through
    the first real operation. The difference is what sharing libraries and
    initialization order move; it is reported, never redistributed.
    """

    sequence = experiments.get("sequence")
    isolated = {
        label.split(":", 1)[1]: runs
        for label, runs in experiments.items()
        if label.startswith("component:")
    }
    if not sequence or not isolated:
        return None
    rows: dict[str, Any] = {}
    for component, runs in isolated.items():
        alone = aggregate(runs)["derived"].get("ready_cost")
        rows[component] = alone["median"] if alone else None
    together = aggregate(sequence)["derived"].get("ready_cost")
    known = [value for value in rows.values() if value is not None]
    return {
        "components": rows,
        "isolated_sum": sum(known) if len(known) == len(rows) else None,
        "sequence": together["median"] if together else None,
    }


def _correctness(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Whether every repeat returned the same decisions for the same inputs."""

    signatures: list[list[str | None]] = []
    statuses: set[str] = set()
    for run in runs:
        signature: list[str | None] = []
        for row in run["stages"]:
            if row["stage"] == "first_lookup":
                signature.append(row["detail"].get("digest"))
                statuses.add(str(row["detail"].get("status")))
            signature.extend(row.get("digests", []))
            statuses.update(row.get("statuses", []))
        signatures.append(signature)
    return {
        "signature": signatures[0] if signatures else None,
        "stable_across_repeats": (
            all(item == signatures[0] for item in signatures) if signatures else None
        ),
        "statuses": sorted(statuses),
    }
