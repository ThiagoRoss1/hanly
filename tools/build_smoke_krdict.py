"""Build the small KRDICT database the packaged runtime smoke installs.

The production dictionary is licensed and is not redistributable, so a clean
machine has none and a frozen run provisions itself from the release channel
over the network instead. What this writes is a real database built by the
release builder rather than a second dictionary implementation, carrying only
the words the packaged self-check probes.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

if __package__ in (None, ""):
    # Run as a plain script rather than ``python -m``, so the repository root
    # is not on the path and ``tools.krdict`` cannot be imported without it.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.krdict.build_seed import build_database

#: Fixed, so two runs on the same commit produce the same bytes. They name a
#: smoke corpus rather than a KRDICT edition on purpose: nothing built here may
#: be mistaken for the dictionary a release publishes.
SMOKE_RESOURCE_VERSION = "smoke-v1"
SMOKE_SOURCE_DATE = "1970-01-01"
SMOKE_BUILD_DATE = "1970-01-01"

#: The source calls every ordinary headword a 단어, and marks an English gloss
#: with 영어. The builder reads both, so a corpus using anything else is parsed
#: into an empty database.
_LEXICAL_UNIT = "단어"
_ENGLISH = "영어"


@dataclass(frozen=True, slots=True)
class _Word:
    """One headword, in the terms the official source describes one."""

    lemma: str
    part_of_speech: str
    definition: str
    english: str
    english_definition: str
    inflection: str | None = None


#: ``한국어`` is the word ``hanly --self-check worker`` looks up. The other two
#: are the reading in the Korean fixture image the same run recognizes, so the
#: database answers for what the smoke actually puts in front of it.
SMOKE_WORDS = (
    _Word("한국어", "명사", "한국 사람이 쓰는 말.", "Korean", "the Korean language"),
    _Word("책", "명사", "글이나 그림을 인쇄하여 묶은 것.", "book", "a book"),
    _Word(
        "읽다",
        "동사",
        "글을 보고 뜻을 이해하다.",
        "read",
        "to read",
        inflection="읽습니다",
    ),
)

PROBE_LEMMAS = tuple(word.lemma for word in SMOKE_WORDS)


def build_smoke_krdict(destination: str | Path) -> Path:
    """Build the smoke database at ``destination`` and return its path."""

    database = Path(destination).expanduser().resolve()
    with TemporaryDirectory(prefix="hanly-smoke-krdict-") as scratch:
        source = Path(scratch) / "krdict-smoke-source.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("smoke.xml", _source_document(SMOKE_WORDS))
        build_database(
            source,
            database,
            source_date=SMOKE_SOURCE_DATE,
            resource_version=SMOKE_RESOURCE_VERSION,
            build_date=SMOKE_BUILD_DATE,
        )
    return database


def _source_document(words: Sequence[_Word]) -> bytes:
    """Render the corpus as the official-shape XML the builder scans."""

    resource = ElementTree.Element("LexicalResource")
    lexicon = ElementTree.SubElement(resource, "Lexicon")
    for identifier, word in enumerate(words, start=1):
        lexicon.append(_entry_element(identifier, word))
    return ElementTree.tostring(resource, encoding="utf-8", xml_declaration=True)


def _entry_element(identifier: int, word: _Word) -> ElementTree.Element:
    """Build one ``LexicalEntry``: its features, headword, and single sense."""

    entry = ElementTree.Element("LexicalEntry", {"att": "id", "val": str(identifier)})
    _feature(entry, "lexicalUnit", _LEXICAL_UNIT)
    _feature(entry, "homonym_number", "0")
    _feature(entry, "partOfSpeech", word.part_of_speech)
    _feature(ElementTree.SubElement(entry, "Lemma"), "writtenForm", word.lemma)

    if word.inflection is not None:
        form = ElementTree.SubElement(entry, "WordForm")
        _feature(form, "type", "활용")
        _feature(form, "writtenForm", word.inflection)

    sense = ElementTree.SubElement(entry, "Sense", {"att": "id", "val": str(identifier)})
    _feature(sense, "definition", word.definition)
    equivalent = ElementTree.SubElement(sense, "Equivalent")
    _feature(equivalent, "language", _ENGLISH)
    _feature(equivalent, "lemma", word.english)
    _feature(equivalent, "definition", word.english_definition)
    return entry


def _feature(parent: ElementTree.Element, name: str, value: str) -> None:
    """Attach one ``<feat att= val=>``, which is how the source states a fact."""

    ElementTree.SubElement(parent, "feat", {"att": name, "val": value})


def main(argv: Sequence[str] | None = None) -> int:
    """Write the database and print where it landed."""

    parser = argparse.ArgumentParser(
        description="Build the KRDICT database the packaged runtime smoke installs"
    )
    parser.add_argument(
        "destination",
        type=Path,
        help="where to write krdict.sqlite3 (a temporary location, never the bundle)",
    )
    arguments = parser.parse_args(None if argv is None else list(argv))

    print(build_smoke_krdict(arguments.destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PROBE_LEMMAS",
    "SMOKE_BUILD_DATE",
    "SMOKE_RESOURCE_VERSION",
    "SMOKE_SOURCE_DATE",
    "SMOKE_WORDS",
    "build_smoke_krdict",
    "main",
]
