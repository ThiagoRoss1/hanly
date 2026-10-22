"""Exercise real dictionary and morphology data through popup presentation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .identity import REPO_ROOT

CORPUS = REPO_ROOT / "lab" / "fixtures" / "korean" / "popup_content.json"


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    text: str
    target: str
    cursor: int
    lemma: str
    headword: str
    part_of_speech: str
    hanja: str | None
    vocabulary_level: str | None
    gloss_sha256: str
    definition_sha256: str
    analysis: tuple[tuple[str, str], ...] | None
    construction_headword: str | None
    construction_definition_sha256: str | None
    additional_construction_definition_sha256: str | None
    required_sense_definition_sha256: str | None
    note: str | None


def load_corpus(path: Path = CORPUS) -> list[Case]:
    """Load authored cases and reject duplicate or ungrounded target positions."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    references = raw.get("source_references", {}).get("case_urls", {})
    cases: list[Case] = []
    seen: set[str] = set()
    for item in raw["cases"]:
        if item["id"] in seen:
            raise ValueError(f"duplicate case id: {item['id']}")
        seen.add(item["id"])
        text, target = item["text"], item["target"]
        if target not in text or not 0 <= item["cursor"] < len(target):
            raise ValueError(f"{item['id']}: invalid target or cursor")
        urls = references.get(item["id"], ())
        if not urls or any(not url.startswith("https://krdict.korean.go.kr/") for url in urls):
            raise ValueError(f"{item['id']}: missing official KRDICT source reference")
        cases.append(Case(
            id=item["id"], category=item["category"], text=text, target=target,
            cursor=int(item["cursor"]), lemma=item["lemma"], headword=item["headword"],
            part_of_speech=item["part_of_speech"], hanja=item["hanja"],
            vocabulary_level=item["vocabulary_level"],
            gloss_sha256=item["gloss_sha256"],
            definition_sha256=item["definition_sha256"],
            analysis=(
                tuple((text, role) for text, role in item["analysis"])
                if "analysis" in item else None
            ),
            construction_headword=(
                item["construction"]["headword"] if "construction" in item else None
            ),
            construction_definition_sha256=(
                item["construction"]["definition_sha256"]
                if "construction" in item else None
            ),
            additional_construction_definition_sha256=(
                item["construction"].get("additional_definition_sha256")
                if "construction" in item else None
            ),
            required_sense_definition_sha256=item.get("required_sense_definition_sha256"),
            note=item.get("note"),
        ))
    return cases


def selection_for(case: Case) -> Any:
    """Build the sentence selection and cursor used by the language stage."""

    from hanly import TextSelection

    start = case.text.index(case.target)
    end = start + len(case.target)
    before = case.text[:start].split()
    after = case.text[end:].split()
    return TextSelection(
        case.target,
        case.cursor,
        context_before=before[-1] if before else "",
        context_after=after[0] if after else "",
    )


def run(dictionary_path: Path) -> list[dict[str, Any]]:
    """Run one local provider lifecycle and return popup-model evidence."""

    from hanly.kiwi_provider import KiwiProvider
    from hanly.krdict_provider import KRDICTProvider
    from hanly.language_pipeline import LanguagePipeline
    from hanly_app.config import TechnicalDetailLevel
    from hanly_app.popup.presentation import format_lookup_result
    from hanly_app.service.application import _plain

    dictionary = KRDICTProvider(dictionary_path)
    try:
        recorded_dictionary = _RecordingDictionary(dictionary)
        pipeline = LanguagePipeline(KiwiProvider(), recorded_dictionary)
        rows: list[dict[str, Any]] = []
        for case in load_corpus():
            selection = selection_for(case)
            recorded_dictionary.queries.clear()
            result = pipeline.lookup(selection)
            content = format_lookup_result(result, TechnicalDetailLevel.OFF)
            entry = content.entry
            context = result.context
            gold_entries = dictionary.lookup(case.headword)
            gold_entry = next((
                candidate for candidate in gold_entries
                if candidate.part_of_speech == case.part_of_speech
                and candidate.senses
                and hashlib.sha256(candidate.senses[0].definition.encode("utf-8")).hexdigest()
                == case.definition_sha256
            ), None)
            rows.append({
                "id": case.id,
                "category": case.category,
                "note": case.note,
                "status": content.status.value,
                "popup_content": _plain(content),
                "surface": content.surface,
                "lemma": content.lemma,
                "headword": entry.headword if entry else None,
                "part_of_speech": entry.part_of_speech if entry else None,
                "source": content.source,
                "hanja": entry.hanja if entry else None,
                "vocabulary_level": entry.vocabulary_level if entry else None,
                "gloss": entry.senses[0].gloss if entry and entry.senses else None,
                "definition": entry.senses[0].definition if entry and entry.senses else None,
                "senses": [
                    {"gloss": sense.gloss, "definition": sense.definition}
                    for sense in (entry.senses if entry else ())
                ],
                "expected_headword": case.headword,
                "expected_entry_available": gold_entry is not None,
                "expected_entry": (
                    {
                        "headword": gold_entry.headword,
                        "part_of_speech": gold_entry.part_of_speech,
                        "hanja": gold_entry.hanja,
                        "vocabulary_level": gold_entry.vocabulary_level,
                        "gloss": gold_entry.senses[0].gloss,
                        "definition": gold_entry.senses[0].definition,
                    }
                    if gold_entry is not None else None
                ),
                "entry_matches_expected": bool(entry and entry.headword == case.headword),
                "selection": {
                    "text": selection.text,
                    "cursor_index": selection.cursor_index,
                    "context_before": selection.context_before,
                    "context_after": selection.context_after,
                },
                "dictionary_queries": list(recorded_dictionary.queries),
                "normalized_analysis": [
                    {
                        "token": token.token,
                        "lemma": token.lemma,
                        "part_of_speech": token.part_of_speech,
                        "start": token.start,
                        "length": token.length,
                    }
                    for token in (context.analyses if context is not None else ())
                ],
                "components": [
                    [component.surface, component.lemma, component.grammatical]
                    for component in content.components
                ],
                "analysis": [[piece.text, piece.role] for piece in content.analysis],
                "construction": (
                    {
                        "headword": content.construction.headword,
                        "gloss": content.construction.gloss,
                        "definition": content.construction.definition,
                        "senses": [
                            {"gloss": sense.gloss, "definition": sense.definition}
                            for construction_entry in context.construction.entries
                            for sense in construction_entry.senses
                        ] if context is not None and context.construction is not None else [],
                    }
                    if content.construction is not None else None
                ),
            })
        return rows
    finally:
        dictionary.close()


def score_rows(rows: Sequence[dict[str, Any]], cases: Sequence[Case]) -> dict[str, Any]:
    """Score source-backed dictionary and popup expectations without hiding misses."""

    by_id = {str(row["id"]): row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != {case.id for case in cases}:
        raise ValueError("popup evidence rows must contain each authored case exactly once")

    scored: list[dict[str, Any]] = []
    for case in cases:
        row = by_id[case.id]
        gold = row.get("expected_entry") or {}
        actual = {
            "lemma": row.get("lemma"),
            "headword": row.get("headword"),
            "part_of_speech": row.get("part_of_speech"),
            "hanja": row.get("hanja"),
            "vocabulary_level": row.get("vocabulary_level"),
            "gloss_sha256": _digest(row.get("gloss")),
            "definition_sha256": _digest(row.get("definition")),
        }
        expected = {
            "lemma": case.lemma,
            "headword": case.headword,
            "part_of_speech": case.part_of_speech,
            "hanja": case.hanja,
            "vocabulary_level": case.vocabulary_level,
            "gloss_sha256": case.gloss_sha256,
            "definition_sha256": case.definition_sha256,
        }
        checks = [
            _check("source_entry_available", row.get("expected_entry_available") is True),
            _check("source_headword", gold.get("headword") == case.headword),
            _check("source_part_of_speech", gold.get("part_of_speech") == case.part_of_speech),
            _check("source_hanja", gold.get("hanja") == case.hanja),
            _check(
                "source_vocabulary_level",
                gold.get("vocabulary_level") == case.vocabulary_level,
            ),
            _check("source_first_gloss", _digest(gold.get("gloss")) == case.gloss_sha256),
            _check(
                "source_first_definition",
                _digest(gold.get("definition")) == case.definition_sha256,
            ),
            _check("lookup_success", row.get("status") == "SUCCESS"),
            _check("selected_surface", row.get("surface") == case.target),
            _check("dictionary_source", row.get("source") == "krdict"),
        ]
        for field, value in expected.items():
            checks.append(_check(f"popup_{field}", actual[field] == value))

        if case.analysis is not None:
            checks.append(_check(
                "popup_read_as", row.get("analysis") == [list(x) for x in case.analysis]
            ))

        construction = row.get("construction")
        if case.construction_headword is None:
            checks.append(_check("popup_construction_absent", construction is None))
        else:
            construction = construction or {}
            checks.extend((
                _check(
                    "popup_construction_headword",
                    construction.get("headword") == case.construction_headword,
                ),
                _check(
                    "popup_construction_first_definition",
                    _digest(construction.get("definition"))
                    == case.construction_definition_sha256,
                ),
            ))
            if case.additional_construction_definition_sha256 is not None:
                senses = construction.get("senses", [])
                checks.append(_check(
                    "popup_construction_additional_sense",
                    any(
                        _digest(sense.get("definition"))
                        == case.additional_construction_definition_sha256
                        for sense in senses
                    ),
                ))

        if case.required_sense_definition_sha256 is not None:
            checks.append(_check(
                "popup_required_sense",
                any(
                    _digest(sense.get("definition")) == case.required_sense_definition_sha256
                    for sense in row.get("senses", [])
                ),
            ))

        failures = [check["name"] for check in checks if not check["passed"]]
        scored.append({
            "id": case.id,
            "category": case.category,
            "target": case.target,
            "outcome": "passed" if not failures else "failed",
            "expected": expected,
            "actual": actual,
            "checks": checks,
            "failure_reasons": failures,
        })

    passed = sum(item["outcome"] == "passed" for item in scored)
    return {
        "scope": "language_to_presentation_model",
        "status": "passed" if passed == len(scored) else "failed",
        "total_cases": len(scored),
        "passed_cases": passed,
        "failed_cases": len(scored) - passed,
        "score": f"{passed}/{len(scored)}",
        "cases": scored,
    }


def run_campaign(
    dictionary_path: Path,
    output_root: Path,
    *,
    repo_root: Path = REPO_ROOT,
) -> tuple[Path, dict[str, Any]]:
    """Run once through Kiwi, KRDICT and popup formatting, retaining scoped evidence."""

    from .metadata import build_metadata, source_identity, write_metadata

    dictionary_path = Path(dictionary_path)
    if not dictionary_path.is_file():
        raise FileNotFoundError(f"local KRDICT resource is missing: {dictionary_path}")

    cases = load_corpus()
    resource_version = _resource_version(dictionary_path)
    metadata = build_metadata(
        repo_root=repo_root,
        kind="popup_content",
        config={
            "scope": "language_to_presentation_model",
            "morphology_provider": "KiwiProvider",
            "dictionary_provider": "KRDICTProvider",
            "ocr": "not_run",
            "capture": "not_run",
            "dictionary_resource_version": resource_version,
        },
        scenario={
            "name": "popup_content_language_to_presentation",
            "case_ids": [case.id for case in cases],
            "case_count": len(cases),
            "corpus_sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
            "endpoint": "source_gold_dictionary_entry_and_popup_model",
        },
        versions={"hanly": "local", "hanly-app": "local"},
    )
    run_dir = Path(output_root) / str(metadata["run_id"])
    run_dir.mkdir(parents=True, exist_ok=False)
    write_metadata(run_dir / "metadata.json", metadata)

    rows = run(dictionary_path)
    summary = score_rows(rows, cases)
    end_source = source_identity(repo_root)
    provenance = metadata["lab_provenance"]
    provenance["source_at_end"] = end_source
    source_start = provenance["source"]
    provenance["source_changed"] = (
        source_start.get("commit") != end_source.get("commit")
        or source_start.get("state") != end_source.get("state")
    )
    write_metadata(run_dir / "metadata.json", metadata)
    _write_campaign_artifacts(run_dir, metadata, rows, summary)
    return run_dir, summary


def _write_campaign_artifacts(
    run_dir: Path,
    metadata: dict[str, Any],
    rows: Sequence[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    """Keep full dictionary payloads in results, outside the compact score report."""

    (run_dir / "results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "summary.md").write_text(
        campaign_markdown(metadata, summary), encoding="utf-8"
    )


def campaign_markdown(metadata: dict[str, Any], summary: dict[str, Any]) -> str:
    """Render a compact scope, provenance and source-gold score without definitions."""

    provenance = metadata["lab_provenance"]
    source = provenance["source"]
    rows = [
        "# Popup content campaign",
        "",
        f"- Run: `{metadata['run_id']}` ({metadata['timestamp']}).",
        f"- Checkout: `{source['commit']}`, {source['state']} at start.",
        f"- Host: {provenance['platform']['system']} / {provenance['platform']['machine']}.",
        f"- KRDICT: `{metadata['config']['dictionary_resource_version']}`.",
        f"- Corpus SHA-256: `{metadata['scenario']['corpus_sha256']}`.",
        "- Scope: language pipeline through the Qt-independent popup presentation model.",
        "- OCR, capture, native UI and desktop process launch: not run.",
        "- Reproduction: `python -m lab popup-content`.",
        "- Authored case sources and sense hashes: `lab/fixtures/korean/popup_content.json`.",
        f"- Score: **{summary['score']}** ({summary['passed_cases']} passed, "
        f"{summary['failed_cases']} failed).",
        "",
        "| Case | target | expected entry | actual popup | score |",
        "|---|---|---|---|---|",
    ]
    for case in summary["cases"]:
        rows.append(
            f"| {case['id']} | {case['target']} | "
            f"{case['expected']['headword']} / {case['expected']['part_of_speech']} | "
            f"{case['actual']['headword']} / {case['actual']['part_of_speech']} | "
            f"{case['outcome']} |"
        )
    failures = [case for case in summary["cases"] if case["outcome"] == "failed"]
    if failures:
        rows.extend(("", "## Failed source-gold cases", ""))
        for case in failures:
            rows.append(
                f"- **{case['id']}**: expected {case['expected']['headword']}/"
                f"{case['expected']['part_of_speech']}; observed "
                f"{case['actual']['headword']}/{case['actual']['part_of_speech']}. "
                f"Failed checks: {', '.join(case['failure_reasons'])}."
            )
    rows.extend((
        "",
        "Full normalized analyses, queries, senses and popup data are in `results.json`; "
        "dictionary definitions are kept only in that ignored run artifact.",
        "",
    ))
    return "\n".join(rows)


def _check(name: str, passed: bool) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed)}


def _digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _resource_version(dictionary_path: Path) -> str:
    try:
        with sqlite3.connect(dictionary_path) as connection:
            row = connection.execute(
                "SELECT value FROM resource_metadata WHERE key = 'resource_version'"
            ).fetchone()
    except sqlite3.Error:
        return "unknown"
    return str(row[0]) if row else "unknown"


class _RecordingDictionary:
    """Capture real provider query keys without changing returned entries."""

    def __init__(self, dictionary: Any) -> None:
        self.dictionary = dictionary
        self.queries: list[str] = []

    def lookup(self, lemma: str) -> Any:
        self.queries.append(lemma)
        return self.dictionary.lookup(lemma)
