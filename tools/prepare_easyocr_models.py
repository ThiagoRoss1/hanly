"""Fetch the two EasyOCR weights a packaged Hanly carries.

A frozen build reads its models from ``hanly_app/assets/easyocr_models`` and
cannot download anything, so the files must be there before PyInstaller
collects them. This helper is deliberately fixed: two names, two URLs, and the
two MD5 digests from the EasyOCR 1.7.2 model tables. Those digests are
EasyOCR's own and identify the content it re-checks on load; they are not a
claim of cryptographic authenticity.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

#: Where a packaged build looks for its weights, and where these land.
MODEL_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "packages"
    / "hanly-app"
    / "src"
    / "hanly_app"
    / "assets"
    / "easyocr_models"
)

#: One request per model, and no retries: a failed fetch is reported, not
#: worked around.
REQUEST_TIMEOUT_SECONDS = 120.0

#: Both archives are well under this; it exists so a redirected or replaced URL
#: cannot stream unbounded data into the build tree.
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024

_CHUNK_BYTES = 1 << 20

Opener = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class Weight:
    """One EasyOCR weight file, and the archive it is published in."""

    name: str
    url: str
    md5: str


#: EasyOCR 1.7.2: the CRAFT detector and the Korean generation-2 recognizer are
#: exactly what Hanly's Korean CPU configuration loads.
WEIGHTS = (
    Weight(
        "craft_mlt_25k.pth",
        "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip",
        "2f8227d2def4037cdb3b34389dcf9ec1",
    ),
    Weight(
        "korean_g2.pth",
        "https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/korean_g2.zip",
        "befecf7b1ca2fffb5af814a51443682d",
    ),
)


class ModelPreparationError(RuntimeError):
    """Raised when a weight cannot be obtained as the exact expected content."""


def prepare_models(
    directory: Path | str = MODEL_DIRECTORY,
    *,
    opener: Opener = urllib.request.urlopen,
) -> tuple[Path, ...]:
    """Ensure both weights exist in ``directory``, and return their paths."""

    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    return tuple(_prepare_one(weight, destination, opener) for weight in WEIGHTS)


def _prepare_one(weight: Weight, directory: Path, opener: Opener) -> Path:
    """Reuse an already-correct file, or fetch and verify a fresh one."""

    target = directory / weight.name
    if target.is_file() and file_md5(target) == weight.md5:
        return target

    with TemporaryDirectory(dir=directory) as scratch:
        archive = _download(weight, Path(scratch) / "archive.zip", opener)
        extracted = _extract_expected_member(archive, weight, Path(scratch))
        digest = file_md5(extracted)
        if digest != weight.md5:
            raise ModelPreparationError(
                f"{weight.name} does not match the expected EasyOCR content: "
                f"got {digest}, expected {weight.md5}"
            )
        extracted.replace(target)
    return target


def _download(weight: Weight, archive: Path, opener: Opener) -> Path:
    """Read one bounded HTTPS response into a local archive file."""

    if not weight.url.startswith("https://"):
        raise ModelPreparationError(f"{weight.name} must be fetched over HTTPS")

    with _opened(opener, weight.url) as response:
        with archive.open("wb") as stream:
            written = 0
            for chunk in iter(lambda: response.read(_CHUNK_BYTES), b""):
                written += len(chunk)
                if written > MAX_ARCHIVE_BYTES:
                    raise ModelPreparationError(
                        f"{weight.name} archive exceeds {MAX_ARCHIVE_BYTES} bytes"
                    )
                stream.write(chunk)
    return archive


@contextmanager
def _opened(opener: Opener, url: str) -> Iterator[Any]:
    """Open one response, closing it even when the opener returns a bare file."""

    response = opener(url, timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        yield response
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _extract_expected_member(archive: Path, weight: Weight, into: Path) -> Path:
    """Extract only the one file this weight is, never the whole archive."""

    with zipfile.ZipFile(archive) as bundle:
        members = [
            info
            for info in bundle.infolist()
            if not info.is_dir() and Path(info.filename).name == weight.name
        ]
        if len(members) != 1:
            raise ModelPreparationError(
                f"{archive.name} does not contain exactly one {weight.name}"
            )
        extracted = into / weight.name
        with bundle.open(members[0]) as source, extracted.open("wb") as target:
            shutil.copyfileobj(source, target, _CHUNK_BYTES)
    return extracted


def file_md5(path: Path) -> str:
    """Digest a file incrementally; these weights are tens of megabytes."""

    # MD5 because that is the digest EasyOCR publishes and re-checks; it
    # identifies content here, it does not authenticate it.
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``python tools/prepare_easyocr_models.py``."""

    parser = argparse.ArgumentParser(
        description="Download the EasyOCR weights a packaged Hanly carries"
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=MODEL_DIRECTORY,
        help="where to place the weights (defaults to the packaged asset directory)",
    )
    arguments = parser.parse_args(argv)

    try:
        prepared = prepare_models(arguments.directory)
    except (ModelPreparationError, OSError, zipfile.BadZipFile) as error:
        print(f"Hanly packaging: {error}", file=sys.stderr, flush=True)
        return 1

    for path in prepared:
        print(f"Hanly packaging: EasyOCR weight ready at {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
