# Purple Icon Identity Review Handoff

## Bundle

- Scope: the human's approved purple icon integration — the Windows purple
  asset package, the macOS Icon Composer source and its approved purple visual.
  No Linear issues created or mutated.
- Implementation ecosystem: Claude Opus 5.5, macOS 26.6.2 arm64,
  `.venv/bin/python` 3.13.11, Xcode Icon Composer `ictool` 27.0. No Windows
  host.
- Date: 2026-09-27. Branch `visual/interface-update`, starting at `0901b62`.
  Earlier commits unchanged; nothing pushed, merged, rebased, amended or
  squashed. Phase B has not started.

| Commit | Boundary |
|---|---|
| `b7c4b8c` | `chore: switch Hanly icons to the purple identity` |
| this commit | `docs: record the purple icon handoff` |

## Sources

- Windows: `hanly-windows-purple-assets-v1`. All 17 entries of its
  `reference/checksums.sha256` verified before copying, and the 13 copied files
  re-verified in place afterwards.
- macOS: `hanly-macos-icon-v1/Hanly-macOS-v2.icon`, stored unchanged (without
  `.DS_Store`) in `design/identity/source/macos/`.
- Approved macOS visual: `Hanly-macOS-v2-tinted-light.png`. Icon Composer's
  `ictool` renders the source's `TintedLight` rendition with the default tint
  at design generation 27 **pixel-identical** to it (max channel difference
  0), and its `Default` rendition pixel-identical to `v2-default`. The purple is
  therefore a reproducible rendering of the source, not an approximation.

## Files

**Replaced with the Windows package, filenames unchanged:**
`hanly-icon-{16,24,32,48,64,128,256,512}.png`, `window-face-{16,20,24}.png`,
`favicon.ico` in `packages/hanly-app/src/hanly_app/assets/icons/`, and
`packaging/icons/hanly.ico`. Byte-identical to the package; nothing redrawn,
rescaled or resampled. Every alpha mask equals the archived pink one, including
each embedded `.ico` frame: the package is a pure recolor of the transparent B2
geometry.

**Regenerated from the Icon Composer source:** `hanly-macos-icon.png` and
`packaging/icons/hanly.icns`, by `design/identity/source/macos/build_macos_icon.py`.
It renders the `TintedLight` shape natively at 824 px, centers it on a 1024 px
canvas (Apple's icon grid, 80.5%; the previous runtime icon was 80.1%), saves
that as the runtime PNG and builds the ten `.icns` slots from it (Lanczos
reductions below 1024). Two runs are byte-identical.

**Archived:** all 15 previous pink files in `design/identity/archive/pink-v1/`
with a `MANIFEST.md` giving each original path and SHA-256.

**Added:** `design/identity/README.md`.

**Code and tests:** `app_icon.MACOS_ICON_SIZE` 1248 → 1024 (the macOS image
is now the bundle's own 1024 px master rather than a padded copy).
`tests/test_app_identity.py` now proves the runtime macOS icon equals the
`.icns` artwork and that its alpha stays inside the 824 px grid shape. No
application behavior changed.

## Active palette

Windows, Linux, tray, window face and favicon (from the package's
`palette.json`): primary lavender `#C4BBEF`, secondary light `#C2B9ED`, shadow
purple `#A599DE`, dark outline `#8171D0`, pale highlight `#DED8FA`. The neutral
bubble fill and the mascot's skin, blush, eyes, hair and mouth are unchanged.

macOS: Icon Composer's default `TintedLight` treatment of the same source, with
its continuous mask, white/lavender surface and Liquid Glass depth. Measured
surface `#F5F2FF` / `#EFEBFF` / `#F3F0FF`, outline `#7665CC`. It is baked into
static bitmaps, so every system appearance shows it; no Dark variant ships, and
the blue Dark appearance is not restored.

The Control Center's UI accent `#E88CA1` and `qt_theme` accent are UI color,
not icon identity, and are untouched.

## Surface mapping

| Surface | macOS | Windows / Linux |
|---|---|---|
| Executable / bundle | `hanly.icns` (purple squircle) | `hanly.ico` (purple B2) |
| Dock / taskbar, Cmd+Tab / Alt+Tab | `qt_icon()`: `hanly-macos-icon.png` only | `qt_icon()`: B2 from 32 px up |
| Window title bar | none on macOS | `qt_icon()`: face at 16/20/24 px; B2 at 200% scaling (known limitation) |
| Tray / status item | `hanly-icon-24.png` (purple B2) | `hanly-icon-64.png` (purple B2) |
| Control Center favicon | `favicon.ico` (purple face) | same |

## Automated validation

- Focused identity, packaging, Qt bootstrap and native icon tests: 144 passed.
- Portable suite: 2333 passed, 2 skipped. Native suite: 122 passed.
- `ruff check` and `mypy` over `packages packaging tests tools benchmarks`:
  clean.

## Packaged validation (macOS, built from clean `b7c4b8c`)

- `tools/build_package.py`: success. `hanly-build.json` `source_commit`
  `b7c4b8c078120cdd3b969cbb4df4f732a7b0f939`, version 0.5.3, arm64.
- ZIP reconstruction, DMG check, inventory, window and worker smokes
  (`--expect-version`): all exit 0. DMG-mounted inventory: exit 0.
- `pytest --suite packaged` with `HANLY_EXPECTED_SOURCE_COMMIT` and
  `HANLY_REQUIRE_PACKAGED`: 4 passed against the unpacked ZIP, 4 passed against
  the mounted DMG; the commit-identity case ran.
- `codesign --verify --deep --strict`: passes.
- Every shipped icon is byte-identical to the committed purple set; no archived
  pink SHA-256 occurs in any bundled PNG or ICO, and nothing from `design/`
  is collected.

## Real macOS visual validation

Screenshots were taken on this machine and kept outside the repository.
- Source run: Dock and Cmd+Tab show the purple squircle, aligned with
  neighboring application icons.
- Packaged `.app`: Finder, Dock and Cmd+Tab show the purple squircle. Finder no
  longer draws the grey legacy container the previous full-bleed `.icns` got.
- Rendered (not on-screen) check of what Windows/Linux Qt, the tray and the
  favicon receive: purple B2 from 32 px up, purple face below, purple face
  favicon at 16/32/48.

## Pending real Windows confirmation

Not available on this machine; nothing here is simulated evidence:
executable icon in Explorer, taskbar, Alt+Tab, tray, title-bar face at
100/125/150% and the known 200% B2 fallback, and the Control Center favicon.

## Findings

- **Deferred:** `hanly.icns` slots below 1024 px are Lanczos reductions of the
  master rather than native `ictool` renders. Revisit if small Finder sizes look
  soft on review.
- **Dismissed:** the Windows package's `source/build_assets.py`, preview and
  README are not copied; the package README says it mirrors only the listed
  destinations.
