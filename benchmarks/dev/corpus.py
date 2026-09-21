"""A small, versioned OCR corpus that can mix committed and private cases.

Two kinds of evidence have to coexist without contaminating each other. Licensed
or generated fixtures can live in Git and be compared across machines. Real
frozen captures are somebody's screen: they stay on the machine that made them,
and a manifest in Git must not so much as name their paths or quote their text.

A manifest declares which kind it is, and validation enforces the difference. A
committed manifest may not carry an absolute path, may not reference a private
case, and may not be loaded from outside the repository's fixture tree.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any

SCHEMA_VERSION = 1

#: Where a case may be referenced from. ``local_*`` cases exist only on the
#: machine that produced them.
COMMITTED_PROVENANCE = frozenset({"committed_synthetic", "committed_fixture"})
LOCAL_PROVENANCE = frozenset({"local_private", "local_synthetic"})
PROVENANCE = COMMITTED_PROVENANCE | LOCAL_PROVENANCE

#: A manifest says which of the two it is, so validation is not guesswork.
DISTRIBUTIONS = frozenset({"committed", "local"})

#: The vocabulary a case may be tagged with. Closed on purpose: a typo would
#: otherwise silently produce a tag nothing ever selects, and a report would
#: quietly describe a slice that does not exist.
TAGS = frozenset(
    {
        "light",
        "dark",
        "small_text",
        "medium_text",
        "large_text",
        "regular_weight",
        "bold_weight",
        "mixed_script",
        "punctuation",
        "scaled",
        "blurred",
        "compressed",
        "horizontal",
        "rotated",
        "browser",
        "chat",
        "native",
        "raster",
        "real",
        "synthetic",
    }
)

_CASE_FIELDS = frozenset(
    {
        "id",
        "image",
        "provenance",
        "tags",
        "expected_text",
        "expected_surface",
        "expected_target",
        "expected_regions",
        "source",
        "notes",
    }
)
_REGION_FIELDS = frozenset({"text", "left", "top", "right", "bottom"})
_MANIFEST_FIELDS = frozenset({"schema_version", "distribution", "description", "cases"})


class CorpusError(ValueError):
    """Raised when a manifest is malformed or breaks the privacy boundary."""


@dataclass(frozen=True)
class ExpectedRegion:
    """One annotated text region, in image pixel coordinates."""

    text: str
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        if self.left >= self.right or self.top >= self.bottom:
            raise CorpusError(f"region {self.text!r} has no positive extent")


@dataclass(frozen=True)
class CorpusCase:
    """One scoreable image and whatever ground truth is actually known for it.

    Every expectation is optional and separately absent. A metric with no
    ground truth reports ``not_applicable`` rather than a zero, so an
    unannotated case must not look like a failed one.
    """

    case_id: str
    image: Path
    relative_image: str
    provenance: str
    tags: tuple[str, ...] = ()
    expected_text: str | None = None
    expected_surface: str | None = None
    expected_target: tuple[float, float] | None = None
    expected_regions: tuple[ExpectedRegion, ...] = ()
    source: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None

    @property
    def is_committed(self) -> bool:
        return self.provenance in COMMITTED_PROVENANCE

    @property
    def is_private(self) -> bool:
        """Whether this case holds real screen content that must stay local."""

        return self.provenance == "local_private"


@dataclass(frozen=True)
class Corpus:
    """One manifest's cases, in a stable order."""

    schema_version: int
    distribution: str
    manifest_path: Path
    cases: tuple[CorpusCase, ...]
    description: str | None = None

    def case(self, case_id: str) -> CorpusCase:
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise KeyError(case_id)

    def tagged(self, *tags: str) -> tuple[CorpusCase, ...]:
        """Cases carrying every one of ``tags``."""

        wanted = set(tags)
        return tuple(case for case in self.cases if wanted <= set(case.tags))

    def counts_by_provenance(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.cases:
            counts[case.provenance] = counts.get(case.provenance, 0) + 1
        return counts

    def counts_by_tag(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.cases:
            for tag in case.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return counts


def load_corpus(manifest_path: str | Path, *, require_assets: bool = True) -> Corpus:
    """Read and validate one manifest, resolving image paths against it.

    Paths resolve against the manifest's own directory rather than the process
    working directory, so a corpus can be enumerated from anywhere.
    """

    path = Path(manifest_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise CorpusError(f"could not read corpus manifest {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise CorpusError(f"corpus manifest {path} is not valid JSON: {error}") from error
    return build_corpus(payload, path, require_assets=require_assets)


def build_corpus(
    payload: Any, manifest_path: Path, *, require_assets: bool = True
) -> Corpus:
    """Validate an already-decoded manifest payload."""

    if not isinstance(payload, dict):
        raise CorpusError("a corpus manifest must be a JSON object")
    _reject_unknown(payload, _MANIFEST_FIELDS, "manifest")

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CorpusError(
            f"unsupported corpus schema_version {payload.get('schema_version')!r}; "
            f"expected {SCHEMA_VERSION}"
        )
    distribution = payload.get("distribution")
    if distribution not in DISTRIBUTIONS:
        raise CorpusError(
            f"manifest distribution must be one of {sorted(DISTRIBUTIONS)}, "
            f"got {distribution!r}"
        )

    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise CorpusError("a corpus manifest must carry a list of cases")

    root = manifest_path.parent
    cases = [
        _build_case(entry, root, distribution, require_assets=require_assets)
        for entry in raw_cases
    ]
    _reject_duplicates(cases)
    return Corpus(
        schema_version=SCHEMA_VERSION,
        distribution=str(distribution),
        manifest_path=manifest_path,
        # Sorted by identifier so two runs over one manifest score the same
        # cases in the same order, whatever the file happens to list first.
        cases=tuple(sorted(cases, key=lambda case: case.case_id)),
        description=_optional_text(payload.get("description"), "description"),
    )


def _build_case(
    entry: Any, root: Path, distribution: str, *, require_assets: bool
) -> CorpusCase:
    if not isinstance(entry, dict):
        raise CorpusError("each corpus case must be a JSON object")
    _reject_unknown(entry, _CASE_FIELDS, "case")

    case_id = entry.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise CorpusError("each corpus case needs a non-empty string id")

    provenance = entry.get("provenance")
    if provenance not in PROVENANCE:
        raise CorpusError(
            f"case {case_id!r} provenance must be one of {sorted(PROVENANCE)}, "
            f"got {provenance!r}"
        )
    if distribution == "committed" and provenance in LOCAL_PROVENANCE:
        raise CorpusError(
            f"case {case_id!r} is {provenance} and cannot appear in a committed "
            "manifest; local cases belong in a manifest under the gitignored "
            "artifact root"
        )

    image = _case_image(case_id, entry.get("image"), root, distribution, require_assets)
    tags = _case_tags(case_id, entry.get("tags"))
    target = _case_target(case_id, entry.get("expected_target"))
    regions = _case_regions(case_id, entry.get("expected_regions"))

    source = entry.get("source", {})
    if not isinstance(source, dict):
        raise CorpusError(f"case {case_id!r} source metadata must be an object")
    if provenance in COMMITTED_PROVENANCE and not source:
        raise CorpusError(
            f"case {case_id!r} is committed and must record where it came from "
            "and under what licence"
        )

    return CorpusCase(
        case_id=case_id,
        image=image,
        relative_image=str(entry.get("image")),
        provenance=str(provenance),
        tags=tags,
        expected_text=_optional_text(entry.get("expected_text"), "expected_text"),
        expected_surface=_optional_text(entry.get("expected_surface"), "expected_surface"),
        expected_target=target,
        expected_regions=regions,
        source=dict(source),
        notes=_optional_text(entry.get("notes"), "notes"),
    )


def _case_image(
    case_id: str, raw: Any, root: Path, distribution: str, require_assets: bool
) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise CorpusError(f"case {case_id!r} needs an image path")
    candidate = Path(raw)
    if distribution == "committed":
        _require_portable_path(case_id, raw, candidate)
    resolved = candidate if candidate.is_absolute() else root / candidate
    if distribution == "committed":
        _require_inside(case_id, raw, resolved, root)
    if require_assets and not resolved.is_file():
        raise CorpusError(f"case {case_id!r} references a missing image: {resolved}")
    return resolved


def _require_portable_path(case_id: str, raw: str, candidate: Path) -> None:
    """Refuse anything that names one machine rather than this repository.

    ``Path.is_absolute`` answers for the host it runs on, so a Windows drive
    letter or a UNC share reads as an ordinary relative name on POSIX -- and
    those are exactly the paths that carry somebody's user name.
    """

    if candidate.is_absolute() or PureWindowsPath(raw).is_absolute():
        raise CorpusError(
            f"case {case_id!r} uses the absolute path {raw!r}; a committed "
            "manifest must stay machine-independent"
        )
    if raw.startswith("~"):
        raise CorpusError(
            f"case {case_id!r} uses the home-relative path {raw!r}; a committed "
            "manifest must stay machine-independent"
        )


def _require_inside(case_id: str, raw: str, resolved: Path, root: Path) -> None:
    """Keep a committed manifest pointing at its own fixture tree.

    Without this, ``../`` walks out of the fixtures and a committed manifest can
    reference a real frozen capture under the gitignored artifact root -- which
    is the one thing the committed/local split exists to prevent. The export
    path is contained the same way; this is the input side of that rule.
    """

    base = root.resolve()
    target = resolved.resolve()
    if target != base and base not in target.parents:
        raise CorpusError(
            f"case {case_id!r} points at {raw!r}, which resolves outside the "
            f"manifest's own directory ({base}); a committed manifest may not "
            "reference anything beyond its fixture tree"
        )


def _case_tags(case_id: str, raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(tag, str) for tag in raw):
        raise CorpusError(f"case {case_id!r} tags must be a list of strings")
    unknown = sorted(set(raw) - TAGS)
    if unknown:
        raise CorpusError(
            f"case {case_id!r} uses unknown tag(s) {unknown}; the vocabulary is "
            "closed so a typo cannot become a slice nothing selects"
        )
    return tuple(sorted(set(raw)))


def _case_target(case_id: str, raw: Any) -> tuple[float, float] | None:
    if raw is None:
        return None
    if (
        not isinstance(raw, list)
        or len(raw) != 2
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in raw)
    ):
        raise CorpusError(f"case {case_id!r} expected_target must be [x, y]")
    x, y = (float(value) for value in raw)
    if x < 0 or y < 0:
        raise CorpusError(f"case {case_id!r} expected_target must lie inside the image")
    return x, y


def _case_regions(case_id: str, raw: Any) -> tuple[ExpectedRegion, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise CorpusError(f"case {case_id!r} expected_regions must be a list")
    regions: list[ExpectedRegion] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise CorpusError(f"case {case_id!r} regions must be objects")
        _reject_unknown(entry, _REGION_FIELDS, f"case {case_id!r} region")
        try:
            regions.append(
                ExpectedRegion(
                    text=str(entry["text"]),
                    left=int(entry["left"]),
                    top=int(entry["top"]),
                    right=int(entry["right"]),
                    bottom=int(entry["bottom"]),
                )
            )
        except KeyError as error:
            raise CorpusError(
                f"case {case_id!r} region is missing {error.args[0]!r}"
            ) from error
        except (TypeError, ValueError) as error:
            raise CorpusError(f"case {case_id!r} has an invalid region: {error}") from error
    return tuple(regions)


def validate_case_geometry(case: CorpusCase, width: int, height: int) -> None:
    """Check a case's annotations against the image it actually describes.

    Kept apart from manifest validation because it needs the image decoded,
    which a plain manifest listing should not have to pay for.
    """

    target = case.expected_target
    if target is not None and not (0 <= target[0] < width and 0 <= target[1] < height):
        raise CorpusError(
            f"case {case.case_id!r} expected_target {target} lies outside its "
            f"{width}x{height} image"
        )
    for region in case.expected_regions:
        if region.left < 0 or region.top < 0 or region.right > width or region.bottom > height:
            raise CorpusError(
                f"case {case.case_id!r} region {region.text!r} lies outside its "
                f"{width}x{height} image"
            )


def inventory(corpus: Corpus) -> dict[str, Any]:
    """Summarize a corpus by provenance and tag, naming nothing private."""

    return {
        "schema_version": corpus.schema_version,
        "distribution": corpus.distribution,
        "case_count": len(corpus.cases),
        "by_provenance": corpus.counts_by_provenance(),
        "by_tag": corpus.counts_by_tag(),
        "annotated_text": sum(case.expected_text is not None for case in corpus.cases),
        "annotated_target": sum(case.expected_target is not None for case in corpus.cases),
        "annotated_regions": sum(bool(case.expected_regions) for case in corpus.cases),
    }


def _reject_duplicates(cases: list[CorpusCase]) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise CorpusError(f"duplicate corpus case id {case.case_id!r}")
        seen.add(case.case_id)


def _reject_unknown(payload: dict[str, Any], allowed: frozenset[str], what: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise CorpusError(f"{what} carries unknown field(s) {unknown}")


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CorpusError(f"{field_name} must be a string when present")
    return value


__all__ = [
    "COMMITTED_PROVENANCE",
    "DISTRIBUTIONS",
    "LOCAL_PROVENANCE",
    "PROVENANCE",
    "SCHEMA_VERSION",
    "TAGS",
    "Corpus",
    "CorpusCase",
    "CorpusError",
    "ExpectedRegion",
    "build_corpus",
    "inventory",
    "load_corpus",
    "validate_case_geometry",
]
