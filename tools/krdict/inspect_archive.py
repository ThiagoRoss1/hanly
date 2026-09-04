"""Inspect the official KRDICT ZIP without extracting or mutating it."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path
from xml.etree import ElementTree

if __package__ in (None, ""):
    # Run as a plain script rather than ``python -m``, so the repository root
    # is not on the path and ``tools.krdict`` cannot be imported without it.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.krdict import configure_utf8_output
from tools.krdict.source import (
    _children,
    _direct_features,
    _feature,
    _name,
    _SanitizingStream,
    _source_id,
)

_SAMPLE_LIMIT = 3


def _selected_translation(
    sense: ElementTree.Element, language: str
) -> dict[str, str | None] | None:
    for equivalent in _children(sense, "Equivalent"):
        if _feature(equivalent, "language") != language:
            continue
        return {
            "language": language,
            "lemma": _feature(equivalent, "lemma"),
            "definition": _feature(equivalent, "definition"),
        }
    return None


def _pronunciation(node: ElementTree.Element) -> str | None:
    """Return the entry's pronunciation from wherever the archive records it.

    The official source usually carries it directly on a ``WordForm`` whose
    ``type`` is 발음, and only sometimes on a nested ``FormRepresentation``.
    Requiring the nested form, as this inspector once did, reported no
    pronunciation for most of the dictionary.
    """

    word_forms = _children(node, "WordForm")
    nested = [
        representation
        for word_form in word_forms
        for representation in _children(word_form, "FormRepresentation")
    ]
    for candidate in (*word_forms, *nested, *_children(node, "FormRepresentation")):
        value = _feature(candidate, "pronunciation")
        if value is not None:
            return value
    return None


def _compact_entry(node: ElementTree.Element, language: str) -> dict[str, object]:
    lemmas = _children(node, "Lemma")
    senses: list[dict[str, object]] = []
    for sense_node in _children(node, "Sense"):
        examples = [
            value
            for example in _children(sense_node, "SenseExample")
            for value in _direct_features(example, "example")
        ]
        senses.append(
            {
                "sense_id": str(_source_id(sense_node)),
                "korean_definition": _feature(sense_node, "definition"),
                "examples": examples,
                "translation": _selected_translation(sense_node, language),
            }
        )
    return {
        "entry_id": str(_source_id(node)),
        "headword": _feature(lemmas[0], "writtenForm") if lemmas else None,
        "homonym": _feature(node, "homonym_number"),
        "part_of_speech": _feature(node, "partOfSpeech"),
        "pronunciation": _pronunciation(node),
        "level": _feature(node, "vocabularyLevel"),
        # Categories are entry-level features, not a SubjectField element, and
        # the two kinds are kept apart because the source keeps them apart.
        # "subjectCategiory" is misspelled in the official XML; matching the
        # correct spelling would silently report no subject categories.
        "semantic_categories": _direct_features(node, "semanticCategory"),
        "subject_categories": _direct_features(node, "subjectCategiory"),
        "senses": senses,
    }


def inspect(
    path: Path,
    *,
    compact: bool = False,
    language: str = "영어",
    samples: int = _SAMPLE_LIMIT,
) -> int:
    compact_samples: list[dict[str, object]] = []
    files_scanned = entries_scanned = senses_scanned = sanitized = 0
    try:
        with zipfile.ZipFile(path) as archive:
            names = sorted(
                name for name in archive.namelist() if name.casefold().endswith(".xml")
            )
            if not names:
                print(f"no XML found in {path}", file=sys.stderr)
                return 1
            for name in names:
                with archive.open(name) as raw:
                    stream = _SanitizingStream(raw)
                    context = ElementTree.iterparse(stream, events=("start", "end"))
                    _event, root = next(context)
                    for event, element in context:
                        if event != "end" or _name(element.tag) != "lexicalentry":
                            continue
                        entries_scanned += 1
                        senses_scanned += len(_children(element, "Sense"))
                        if len(compact_samples) < samples:
                            compact_samples.append(_compact_entry(element, language))
                        element.clear()
                        root.clear()
                    sanitized += stream.replacements
                files_scanned += 1
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError, ValueError) as error:
        print(f"unable to inspect {path}: {error}", file=sys.stderr)
        return 1

    if compact:
        print(
            json.dumps(
                {
                    "language": language,
                    "samples": compact_samples,
                    "validation": {
                        "files_scanned": files_scanned,
                        "entries_scanned": entries_scanned,
                        "senses_scanned": senses_scanned,
                        "sanitized_0x08_bytes": sanitized,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"reading {files_scanned} XML source(s) from {path}")
        print(f"LexicalEntry: {entries_scanned}")
        print(f"Sense: {senses_scanned}")
        print(f"sanitized 0x08 bytes: {sanitized}")
        for sample in compact_samples:
            print(json.dumps(sample, ensure_ascii=False, indent=2))
    return 0 if entries_scanned else 1


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--language", default="영어")
    parser.add_argument("--samples", type=int, default=_SAMPLE_LIMIT)
    args = parser.parse_args(argv)
    if args.samples < 0:
        parser.error("--samples must be zero or greater")
    return inspect(
        args.path,
        compact=args.compact,
        language=args.language,
        samples=args.samples,
    )


if __name__ == "__main__":
    raise SystemExit(main())
