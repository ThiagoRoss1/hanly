"""The architecture invariant lists and their visual and derived companions.

Invariant IDs are cited across documents, so a renumbering on one side silently
breaks every citation. This has regressed once already; nothing else checks it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_ARCHITECTURE = _ROOT / "docs" / "architecture"

#: Markdown source, its visual companion, and the invariant prefix they share.
_PAIRS = (
    ("01-runtime-flow.md", "Hanly Runtime Flow.html", "RF"),
    ("02-component-architecture.md", "Hanly Component Architecture.html", "CA"),
    ("03-implementation-dag.md", "Hanly Implementation DAG.html", "DAG"),
    ("04-agent-execution-flow.md", "Hanly Agent Execution Flow.html", "AEF"),
)


def _markdown_ids(text: str, prefix: str) -> list[str]:
    """The IDs a Markdown file defines: its bolded list entries, in order."""

    return re.findall(rf"^- \*\*({prefix}-INV-\d+)\b", text, flags=re.MULTILINE)


def _visual_ids(bundle: str, prefix: str) -> list[str]:
    """The IDs a visual lists, read from the unescaped page inside its bundle."""

    page = bundle.replace("\\n", "\n").replace('\\"', '"')
    page = page[page.find("<div", page.find("@font-face")) :]
    return re.findall(rf'nowrap">({prefix}-INV-\d+)</div>', page)


@pytest.mark.parametrize(("markdown", "visual", "prefix"), _PAIRS)
def test_each_visual_lists_the_same_invariants_in_the_same_order(
    markdown: str, visual: str, prefix: str
) -> None:
    defined = _markdown_ids((_ARCHITECTURE / markdown).read_text(encoding="utf-8"), prefix)
    drawn = _visual_ids(
        (_ARCHITECTURE / "visual" / visual).read_text(encoding="utf-8"), prefix
    )

    assert defined, f"{markdown} defines no {prefix}-INV entries"
    assert defined == [f"{prefix}-INV-{n:02d}" for n in range(1, len(defined) + 1)]
    assert drawn == defined


def test_the_derived_context_sheet_indexes_the_invariants_it_claims() -> None:
    """The sheet lists every runtime and component invariant, and only the DAG
    invariants that constrain execution; each one it cites must exist."""

    context = (_ROOT / "docs" / "execution" / "CONTEXT.md").read_text(encoding="utf-8")

    for markdown, _visual, prefix in _PAIRS[:3]:
        defined = _markdown_ids((_ARCHITECTURE / markdown).read_text(encoding="utf-8"), prefix)
        indexed = _markdown_ids(context, prefix)
        if prefix == "DAG":
            assert indexed and set(indexed) <= set(defined)
            assert indexed == sorted(indexed)
        else:
            assert indexed == defined, f"CONTEXT.md is out of date for {prefix}-INV"


def test_the_agent_instruction_files_share_one_body() -> None:
    """AGENTS.md and CLAUDE.md differ only in the line naming their reader."""

    def body(name: str) -> list[str]:
        return (_ROOT / name).read_text(encoding="utf-8").splitlines()[3:]

    assert body("AGENTS.md") == body("CLAUDE.md")
