"""Small deterministic fixtures shared by Hanly tests."""

from pathlib import Path

from .korean import (
    KOREAN_DICTIONARY_ENTRIES,
    KOREAN_OCR_RESULTS,
    KOREAN_TEXT,
    KOREAN_TOKEN_ANALYSES,
)

#: Named once, so a test that moves between suite directories does not have to
#: recount how far it sits from the checkout it reads fixtures and builds from.
REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ASSETS = Path(__file__).resolve().parent / "assets"

__all__ = [
    "FIXTURE_ASSETS",
    "KOREAN_DICTIONARY_ENTRIES",
    "KOREAN_OCR_RESULTS",
    "KOREAN_TEXT",
    "KOREAN_TOKEN_ANALYSES",
    "REPO_ROOT",
]
