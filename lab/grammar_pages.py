"""Paired selectable-text and image-only fixtures for native acquisition tests."""

from __future__ import annotations

import hashlib
import html
import json
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .grammar_inventory import GrammarInventory, GrammarTarget, dictionary_inventory
from .metadata import source_identity
from .synthetic_ocr import (
    FontSpec,
    SampleSpec,
    SyntheticFontError,
    SyntheticRenderError,
    corpus_entry,
    render_sample,
    write_sample,
)

FONTS = Path(__file__).parent / "fixtures" / "fonts"
CURSORS = (
    "default", "text", "pointer", "zoom-in", "zoom-out", "grab", "grabbing",
    "crosshair", "col-resize", "row-resize", "not-allowed", "wait", "progress", "help",
)
PROFILES: tuple[dict[str, Any], ...] = (
    {"name": "normal", "font_size": 24},
    {"name": "small", "font_size": 14},
    {"name": "large", "font_size": 36},
    {"name": "dark", "font_size": 24, "background": 24, "foreground": 235},
    {"name": "low-contrast", "font_size": 24, "background": 235, "foreground": 140},
    {"name": "scaled", "font_size": 24, "scale": 1.25},
    {"name": "blurred", "font_size": 24, "blur_radius": 0.4},
    {"name": "compressed-noisy", "font_size": 24, "jpeg_quality": 60, "noise": 2.0},
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for name in ("Pillow", "kiwipiepy"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = "unavailable"
    return versions


def _fonts() -> list[tuple[str, FontSpec]]:
    fonts = []
    for item in json.loads((FONTS / "manifest.json").read_text("utf-8"))["faces"]:
        path = FONTS / item["file"]
        if _digest(path) != item["sha256"]:
            raise ValueError(f"font identity mismatch: {path.name}")
        fonts.append((item["kind"], FontSpec(
            path.stem, item["license"], (path.name,), path=path,
        )))
    return sorted(fonts, key=lambda pair: pair[0] != "normal")


def _render(
    target: GrammarTarget, font: FontSpec, profile: dict[str, Any], case_id: str,
    output: Path,
) -> dict[str, Any]:
    options = {key: value for key, value in profile.items() if key != "name"}
    # The OCR resolver returns a raw whitespace-delimited token. Grammar's
    # target may exclude sentence punctuation; retain both contracts explicitly.
    start, end = target.start, target.start + len(target.target)
    while start > 0 and not target.text[start - 1].isspace():
        start -= 1
    while end < len(target.text) and not target.text[end].isspace():
        end += 1
    sample = render_sample(SampleSpec(
        case_id=case_id, text=target.text, font=font,
        target_index=target.start + len(target.target) // 2,
        expected_surface=target.text[start:end], seed=17, **options,
    ))
    relative = f"images/{case_id}.png"
    write_sample(sample, output / relative)
    # Source examples stay in this local campaign, even with redistributable fonts.
    entry = corpus_entry(sample, relative, redistributable=False)
    entry.update(grammar_case=target.id, profile=profile["name"], font_kind=font.name)
    return entry


def build_pages(output: Path, inventory: GrammarInventory, *, stress_cases: int = 3) -> Path:
    """Write local fixture pages without opening a window or running Hanly."""

    if not 0 <= stress_cases <= 12:
        raise ValueError("stress_cases must be between 0 and 12")
    if not inventory.targets or len(inventory.targets) > 2000:
        raise ValueError("inventory must contain 1–2000 targets")
    if output.exists() and any(output.iterdir()):
        raise ValueError("output must be empty; previous evidence is never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    fonts = _fonts()
    if not fonts or fonts[0][0] != "normal":
        raise ValueError("a pinned normal font is required")
    source = source_identity()
    images = []
    render_omissions = []

    def append(target: GrammarTarget, font: FontSpec, profile: dict[str, Any], name: str) -> None:
        try:
            images.append(_render(target, font, profile, name, output))
        except (SyntheticFontError, SyntheticRenderError) as error:
            render_omissions.append({"case_id": name, "reason": str(error)})

    for target in inventory.targets:
        append(target, fonts[0][1], PROFILES[0], target.id)
    for target in inventory.targets[:stress_cases]:
        for kind, font in fonts:
            for profile in PROFILES:
                case_id = f"{target.id}-{kind}-{profile['name']}"
                append(target, font, profile, case_id)
    normal = fonts[0][1].path
    if normal is None:
        raise ValueError("normal font must have a pinned path")
    (output / "normal.ttf").write_bytes(normal.read_bytes())
    (output / "normal-OFL.txt").write_bytes(
        normal.with_name(f"{normal.stem}-OFL.txt").read_bytes(),
    )
    payload = {
        "schema_version": 1, "source": source, "seed": 17,
        "versions": _versions(),
        "recipe_sha256": {
            path.name: _digest(path) for path in (
                Path(__file__), Path(__file__).with_name("grammar_inventory.py"),
                Path(__file__).with_name("synthetic_ocr.py"),
                Path(__file__).parent / "fixtures" / "korean" / "grammar.json",
            )
        },
        "coverage": inventory.coverage(), "units": inventory.units,
        "omissions": inventory.omissions,
        "render_omissions": render_omissions,
        "targets": [target.to_dict() for target in inventory.targets],
        "cases": images, "cursors": CURSORS,
        "status": (
            "Fixtures only; native acquisition, cursor identity "
            "and semantic accuracy are untested."
        ),
    }
    (output / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8",
    )
    (output / "corpus.json").write_text(json.dumps(
        ocr_corpus(images), ensure_ascii=False, indent=2,
    ), "utf-8")
    for mode in ("text", "ocr"):
        (output / f"{mode}.html").write_text(_page(mode, inventory.targets, images), "utf-8")
    coverage = inventory.coverage()
    (output / "summary.md").write_text(
        "# Korean acquisition fixtures\n\n"
        f"Source: `{source['commit']}` ({source['state']}).\n\n"
        f"{len(inventory.targets)} surface targets; {len(images)} rendered images; "
        f"{len(CURSORS)} OS/browser cursor styles; {len(render_omissions)} render omissions.\n\n"
        f"Coverage: `{json.dumps(coverage, ensure_ascii=False)}`.\n\n"
        "Open text.html for selectable-text acquisition and ocr.html for image-only OCR. "
        "The cursor selector installs native browser cursors; image zoom, drag and link "
        "controls also exercise actual element behavior. Ground truth is kept in the "
        "external manifest, never in image alt/title/accessible text.\n\n"
        "These are generated fixtures, not a native test result. Dictionary examples "
        "are surface ground truth, not independently reviewed morphology answers. "
        "Missing source examples remain explicit omissions.\n", "utf-8",
    )
    return output / "summary.md"


def ocr_corpus(images: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose the same images to the existing strict OCR campaign reader."""

    cases = []
    for image in images:
        case = {key: value for key, value in image.items()
                if key not in {"grammar_case", "profile", "font_kind"}}
        case["notes"] = (
            f"grammar={image['grammar_case']}; profile={image['profile']}; "
            f"font={image['font_kind']}"
        )
        cases.append(case)
    return {"schema_version": 2, "distribution": "local", "cases": cases,
            "description": "Local grammar images; ground truth is external to the page."}


def _page(mode: str, targets: list[GrammarTarget], images: list[dict[str, Any]]) -> str:
    cards = []
    if mode == "text":
        for index, target in enumerate(targets):
            identifier = html.escape(target.id)
            cards.append(f'<article id="{identifier}"><small>{identifier}</small>'
                         f'<p class="sample" data-cursor="{CURSORS[index % len(CURSORS)]}" '
                         f'tabindex="0">{html.escape(target.text)}</p></article>')
    else:
        for index, case in enumerate(images):
            identifier = html.escape(case["id"])
            cards.append(f'<article id="{identifier}"><small>{identifier}</small>'
                         f'<img class="sample" data-cursor="{CURSORS[index % len(CURSORS)]}" '
                         f'draggable="true" alt="" '
                         f'src="{html.escape(case["image"])}"></article>')
    options = '<option value="by-case">Different cursor per case</option>'
    options += "".join(f'<option>{cursor}</option>' for cursor in CURSORS)
    other = "ocr" if mode == "text" else "text"
    return _HTML.replace("$MODE", mode).replace("$OTHER", other).replace(
        "$OPTIONS", options,
    ).replace("$CARDS", "\n".join(cards))


def run(dictionary: Path, output: Path, stress_cases: int) -> Path:
    inventory = dictionary_inventory(dictionary)
    summary = build_pages(output, inventory, stress_cases=stress_cases)
    payload_path = output / "manifest.json"
    payload = json.loads(payload_path.read_text("utf-8"))
    payload["dictionary_sha256"] = _digest(dictionary)
    payload["font_manifest_sha256"] = _digest(FONTS / "manifest.json")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    return summary


_HTML = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Hanly Lab — $MODE acquisition</title><style>
@font-face{font-family:Lab;src:url(normal.ttf)}
*{box-sizing:border-box}body{margin:0;background:#f4f5f7;color:#202630;font:16px system-ui}
header{position:sticky;top:0;background:white;padding:18px 24px;border-bottom:1px solid #ccd2da
;z-index:1}
header>*{margin-right:12px}main{max-width:1120px;margin:auto;padding:24px;display:grid;gap:16px}
article{padding:20px;background:white;border:1px solid #ccd2da;border-radius:12px;overflow:auto}
small{color:#536174}.sample{font:28px Lab;line-height:1.7;cursor:var(--cursor,default)
;max-width:none}
img.sample{display:block;margin-top:12px;user-select:none
}img.zoomed{transform:scale(1.25);transform-origin:top left}
img.dragging{cursor:grabbing!important
}p.sample{margin:12px 0;white-space:pre-wrap}button,select{padding:8px}
</style><header><strong>Hanly Lab · $MODE</strong><a href="$OTHER.html">Other acquisition page</a>
<label>Native cursor <select id="cursor">$OPTIONS</select></label>
<label><input id="behavior" type="checkbox"> Element behavior (image zoom/drag)</label>
<button id="top" type="button">Top</button><span id="state" aria-live="polite">Ready</span></header>
<main>$CARDS</main><script>
const choice=document.querySelector('#cursor'), behavior=document.querySelector('#behavior');
const samples=document.querySelectorAll('.sample');
function update(){samples.forEach(el=>el.style.setProperty('--cursor',
 behavior.checked&&el.tagName==='IMG'?(el.classList.contains('zoomed')?'zoom-out':'zoom-in'):
 choice.value==='by-case'?el.dataset.cursor:choice.value))}
choice.onchange=update;behavior.onchange=update;
samples.forEach(el=>{el.addEventListener('click',()=>{if(behavior.checked&&el.tagName==='IMG'){
 el.classList.toggle('zoomed');update();}});
 el.addEventListener('dragstart',()=>{el.classList.add('dragging');document.querySelector('#state').textContent='Dragging'});
 el.addEventListener('dragend',()=>{el.classList.remove('dragging');document.querySelector('#state').textContent='Ready'});});
document.querySelector('#top').onclick=()=>window.scrollTo({top:0});update();
</script></html>"""
