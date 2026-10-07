"""Load a versioned OCR corpus of committed fixtures or private captures.

Committed fixtures must be licensed or generated. Private captures stay local;
committed manifests cannot quote their text, name absolute/private paths, or
load from outside the repository fixture tree.

Schema 2 adds, per case, an explicit ``truth`` (is there text, is it Korean,
what should the pointer select, are the regions fully annotated), the
``generation`` identity that reproduces a synthetic image, and its ``family``.
Schema 1 manifests still load; their cases simply carry no stated truth.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

SCHEMA_VERSION = 2
#: Every schema this module still reads.
SCHEMA_VERSIONS = frozenset({1, 2})
#: What the pointer is annotated to find: a Korean word, provably no Korean, or nothing stated.
TARGETS = frozenset({"surface", "no_korean", "none"})
FAMILIES = frozenset({"positive", "negative", "mixed"})

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
        "golden",
        "seeded",
        "difficult",
        "blank",
        "latin",
        "number",
        "icon",
        "border",
        "texture",
        "noise",
        "supersampled",
        "low_contrast",
        "kana",
        "han",
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
        "truth",
        "generation",
        "family",
    }
)
_TRUTH_FIELDS = frozenset({"text_present", "korean_present", "target", "regions"})
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
class CaseTruth:
    """Ground truth stated by whoever made the image, never inferred from OCR."""

    text_present: bool
    korean_present: bool
    #: ``surface``: the pointer should select ``expected_surface``;
    #: ``no_korean``: nothing Korean is there to select; ``none``: not stated.
    target: str
    #: ``complete`` when ``expected_regions`` lists every text region (none for
    #: text-free images); ``missing`` when regions were not annotated.
    regions: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "text_present": self.text_present,
            "korean_present": self.korean_present,
            "target": self.target,
            "regions": self.regions,
        }


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
    #: Schema 2: what is true of the image; ``None`` when a manifest never said.
    truth: CaseTruth | None = None
    generation: dict[str, Any] = field(default_factory=dict)
    family: str | None = None

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

    schema = payload.get("schema_version")
    if schema not in SCHEMA_VERSIONS:
        raise CorpusError(
            f"unsupported corpus schema_version {schema!r}; expected one of "
            f"{sorted(SCHEMA_VERSIONS)}"
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
        _build_case(entry, root, distribution, int(schema), require_assets=require_assets)
        for entry in raw_cases
    ]
    _reject_duplicates(cases)
    return Corpus(
        schema_version=int(schema),
        distribution=str(distribution),
        manifest_path=manifest_path,
        # Sorted by identifier so two runs over one manifest score the same
        # cases in the same order, whatever the file happens to list first.
        cases=tuple(sorted(cases, key=lambda case: case.case_id)),
        description=_optional_text(payload.get("description"), "description"),
    )


def _build_case(
    entry: Any, root: Path, distribution: str, schema: int, *, require_assets: bool
) -> CorpusCase:
    if not isinstance(entry, dict):
        raise CorpusError("each corpus case must be a JSON object")
    _reject_unknown(entry, _CASE_FIELDS, "case")
    if schema == 1 and {"truth", "generation", "family"} & set(entry):
        raise CorpusError("truth, generation and family need corpus schema_version 2")

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

    case = CorpusCase(
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
        truth=_case_truth(case_id, entry.get("truth")),
        generation=_case_mapping(case_id, entry.get("generation"), "generation"),
        family=_case_family(case_id, entry.get("family")),
    )
    _require_consistent_truth(case)
    return case


def _case_truth(case_id: str, raw: Any) -> CaseTruth | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != _TRUTH_FIELDS:
        raise CorpusError(f"case {case_id!r} truth must state exactly {sorted(_TRUTH_FIELDS)}")
    if not isinstance(raw["text_present"], bool) or not isinstance(raw["korean_present"], bool):
        raise CorpusError(f"case {case_id!r} truth presence values must be booleans")
    if raw["target"] not in TARGETS or raw["regions"] not in {"complete", "missing"}:
        raise CorpusError(f"case {case_id!r} truth has an unknown target or region state")
    return CaseTruth(raw["text_present"], raw["korean_present"], raw["target"], raw["regions"])


def _case_mapping(case_id: str, raw: Any, name: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CorpusError(f"case {case_id!r} {name} must be an object")
    return dict(raw)


def _case_family(case_id: str, raw: Any) -> str | None:
    if raw is not None and raw not in FAMILIES:
        raise CorpusError(f"case {case_id!r} family must be one of {sorted(FAMILIES)}")
    return raw


def _require_consistent_truth(case: CorpusCase) -> None:
    """A stated truth must agree with the case's own expectations."""

    truth = case.truth
    if truth is None:
        return
    problems = []
    if not truth.text_present and (truth.korean_present or case.expected_text):
        problems.append("an image without text cannot expect text or Korean")
    if truth.target == "surface" and (not case.expected_surface or case.expected_target is None):
        problems.append("a surface target needs expected_surface and expected_target")
    if truth.target == "surface" and not truth.korean_present:
        problems.append("a Korean surface target needs Korean in the image")
    if truth.regions == "complete" and truth.text_present and not case.expected_regions:
        problems.append("complete region annotation needs the regions")
    if problems:
        raise CorpusError(f"case {case.case_id!r} truth is inconsistent: {'; '.join(problems)}")


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

    ``Path.is_absolute`` answers for the host it runs on: a drive letter or UNC
    share is relative on POSIX, and ``/Users/name`` is relative on Windows --
    and those are exactly the paths that carry somebody's user name.
    """

    if (
        candidate.is_absolute()
        or PureWindowsPath(raw).is_absolute()
        or PurePosixPath(raw).is_absolute()
    ):
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
        "stated_truth": sum(case.truth is not None for case in corpus.cases),
        "by_family": dict(
            sorted(Counter(case.family or "unstated" for case in corpus.cases).items())
        ),
        "fingerprint": fingerprint(corpus),
    }


def fingerprint(corpus: Corpus) -> str | None:
    """The exact images and truths a run scored; ``None`` if an image is missing."""

    digest = hashlib.sha256()
    for case in corpus.cases:
        try:
            image = hashlib.sha256(case.image.read_bytes()).hexdigest()
        except OSError:
            return None
        truth = None if case.truth is None else case.truth.as_dict()
        digest.update(json.dumps([case.case_id, image, truth], sort_keys=True).encode("utf-8"))
    return "sha256:" + digest.hexdigest()[:16]


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
    "FAMILIES",
    "SCHEMA_VERSION",
    "SCHEMA_VERSIONS",
    "TAGS",
    "TARGETS",
    "CaseTruth",
    "Corpus",
    "CorpusCase",
    "CorpusError",
    "ExpectedRegion",
    "build_corpus",
    "fingerprint",
    "inventory",
    "load_corpus",
    "validate_case_geometry",
]
