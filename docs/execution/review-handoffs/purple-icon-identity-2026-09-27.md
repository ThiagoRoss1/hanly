# Purple Icon Identity Review Handoff

Phase B outcome and the Windows continuation are appended below. The Phase A
sections retain their original measurements and chronology.

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

## Post-Bundle Review Outcome — Phase B, 2026-09-27

**Verdict: Accept with test/documentation hardening.** Reviewed on macOS
26.6.2 arm64, Python 3.13.11, Xcode Icon Composer `ictool` 27.0. No product
behavior or artwork was changed during review. Windows visual acceptance
remains outstanding; the automated macOS gates pass. This review does not
claim an independent live Dock/Cmd+Tab/tray confirmation: see the visual
limitation below.

### Fixed now

1. `c464029` — the runtime/bundle comparison used
   `ImageChops.difference(...).getbbox()` on RGBA images. Pillow's default
   alpha-only bounding-box behavior could accept different RGB values when
   alpha matched. An opaque center-pixel color mutation passed the old
   assertion and failed the new full-channel byte comparison. The real
   runtime PNG and decoded 1024 px `.icns` image pass. Dimensions remain
   explicitly checked.
2. The pink rollback manifest omitted the purple-only geometry assertion.
   Assets plus `MACOS_ICON_SIZE` alone would leave a failing test. The
   instructions now include the measured pink alpha bounds
   `(124, 124, 1124, 1124)`, retain full-channel comparison, and require tests
   and a rebuild.

### Independently reproduced

- Two native 824 px `TintedLight` renders were byte-identical. Centering the
  rendered artwork on 1024 px reproduced the committed runtime RGBA pixels;
  rebuilding all ten `.icns` slots reproduced the committed `.icns` bytes.
- The native 1024 px rendition reproduced the approved preview pixel for
  pixel. The delivered effect is baked into static images, not a runtime
  appearance-dependent Liquid Glass icon.
- All 13 copied Windows assets match the approved asset package byte for
  byte. All 15 pink rollback assets match both their manifest SHA-256 and
  their original files at `0901b62`.
- Decoding the generated Control Center page's inline favicon reproduces
  the committed purple face ICO bytes exactly.
- Both reconstructed applications contain byte-identical active icon assets.
  No archived pink hash occurs in bundled PNG/ICO/ICNS files, and no
  `design/` source or rollback tree is collected.

### Gates and fresh macOS release artifacts

Built from clean `c464029cf9048d4dda2024355f6cfe527b9ccdd0`, version
0.5.3, arm64. Subsequent changes in this review are documentation only.

| Gate | Result |
|---|---|
| Portable suite | 2333 passed, 2 skipped |
| Native suite, required | 122 passed |
| Ruff | clean |
| mypy | clean, 301 source files |
| ZIP reconstructed application, packaged suite | 4 passed, required full commit check |
| DMG reconstructed application, packaged suite | 4 passed, required full commit check |
| DMG structure check | passed |
| `codesign --verify --deep --strict`, ZIP and DMG copies | passed |

Packaged gates include inventory, source identity, the isolated real
OCR/morphology/dictionary worker, and the real Control Center page/bridge
with clean exit. Two harness/environment issues were corrected before final
results: sandboxed process enumeration/Vision calls were blocked (the full
portable rerun outside that sandbox passed); an abbreviated expected hash
was refused by the source-identity gate (both final runs used the full hash).
Neither was dismissed as a product failure or counted as a passing check.

### Visual evidence and limits

- Independently opened the fresh build directory in Finder's icon view:
  the purple continuous-corner icon is visible, with artwork inside the
  container and no legacy grey enclosure.
- Launched the ZIP application on a disposable profile, not the user's
  profile. CUA selection of Hanly and of the Dock timed out, so live
  Dock/Cmd+Tab/tray visuals were **not independently confirmed in Phase B**.
  Phase A's screenshots remain historical evidence, not this review's own
  observation. The isolated process was stopped with SIGTERM after the
  inspection attempt; its exit was verified.
- Qt/native tests verify the macOS runtime icon and the mixed Windows/Linux
  size selection. Tray bytes and inline favicon payload are covered by
  identity tests; these are automated evidence, not on-screen inspection.
- Screenshots, build output and temporary profiles were not committed.
  Original commits were not rewritten; no push or merge was performed.

### Deferred / dismissed

- **Deferred:** lower `.icns` slots use Lanczos reductions. Revisit only if
  real small Finder sizes show unacceptable softness; this review found no
  reason to replace approved artwork.
- **Deferred:** independently inspect the live macOS Dock, Cmd+Tab and
  menu-bar tray once computer-use access works, or by a brief human check.
  Trigger: before declaring every icon surface visually accepted. No code
  correction is justified by an automation timeout.
- **Deferred:** all real Windows surfaces below. Trigger: the Windows
  continuation after pulling these commits.
- **Dismissed:** retained pink/blue source appearance data in the editable
  Icon Composer source does not contaminate the selected purple static
  rendition; the native reproduction and packaged hashes establish what
  actually ships.

### Windows continuation — execute after push/pull

Read repository instructions and this handoff first; inspect the branch and
worktree. Keep `visual/interface-update` and its existing commit boundaries.
Do not redesign/recolor icons or rewrite history.

1. Confirm the pulled branch contains `b7c4b8c` and `c464029`, then run
   identity/packaging/Qt-bootstrap tests, required native tests, the portable
   suite, Ruff and mypy. Record every failure; a skipped required check is
   not acceptance.
2. Build from a clean committed tree. Run required packaged tests with
   `HANLY_EXPECTED_SOURCE_COMMIT` set to the **full 40-character hash of the
   build**, and verify the release executable uses the approved purple ICO.
3. Inspect the built executable in Explorer; launch with an isolated profile
   and inspect taskbar, Alt+Tab, tray and title bar. At 100/125/150% expect
   the no-glasses face in the title bar; at 200% expect the documented B2
   app icon there. Do not silently add a DPI workaround.
4. Verify the Control Center's embedded favicon bytes are the purple face.
   If the host does not expose a visible favicon, report that distinction
   rather than claiming on-screen validation.
5. Check bundled active assets against the committed files and confirm no
   archived pink assets/design sources are packaged. If Windows icon caching
   obscures the result, distinguish caching from file/rendering defects;
   do not restart Explorer or alter pinned shortcuts without user approval.
6. Append Windows results, exact build commit, findings and remaining limits
   to this handoff. Commit only authorized, narrow fixes separately, using
   the configured human author and no attribution trailers. No push/merge
   without the human's instruction.

The user owns the next push. Remote CI and real Windows acceptance were not
available in this macOS review and must be checked before final merge.

## Final Windows Review Outcome — Phase B, 2026-09-27

**Verdict: Windows icon identity accepted, with limits.** Every Windows
surface I could inspect shows the approved purple identity. The branch is **not
yet merge-ready**: remote Windows native CI on `674c1e1` failed for a reason
this review could not read.

- Host: Windows 10 Enterprise 19045, two 1920×1080 displays at 100% (96 DPI).
- Reviewed from `674c1e1` (contains `b7c4b8c` and `c464029`). The one code
  commit from this review is `f5b583d`. Nothing was reset, rebased, amended,
  squashed, pushed or merged.
- Accepted build: clean tree at
  `f5b583d7d886a8f3b00c5c3849dab61125523bed`, `hanly-build.json` version
  0.5.3, windows x86_64, build id `606a1faa-eec8-4ed2-b72e-598f71d3b371`.
  Built with `.venv-final-validation` (Python 3.13.11, PyQt6-Qt6 6.11.2,
  PyInstaller 6.22.2, hooks-contrib 2026.7, easyocr 1.7.2). These are the
  pins in `packaging/release-constraints.txt`.

### Gates

Run in `.venv-final-validation` unless noted.

| Gate | Result |
|---|---|
| Identity, packaging, Qt icon and dialog tests | 130 passed, 2 skipped |
| Portable suite | 2232 passed, 103 skipped |
| Native suite, `HANLY_REQUIRE_NATIVE=1` | 118 passed, 33 skipped (other-platform cases) |
| Native suite, CI mirror (Python 3.10, PyQt6 6.11.0, torch 2.14 CPU) | 118 passed, 33 skipped |
| Packaged suite, `HANLY_REQUIRE_PACKAGED=1`, full 40-char `HANLY_EXPECTED_SOURCE_COMMIT` | 4 passed (inventory, commit identity, frozen worker, Control Center page) |
| `ruff check packages packaging tests tools benchmarks` | clean |
| `mypy --platform linux …` (the CI gate) | clean, 301 files |

Host-platform `mypy` still reports the 22 POSIX-only API errors recorded in
the 2026-09-26 Windows validation. They are pre-existing and outside this
update; CI runs mypy on Linux.

### Remote CI

GitHub Actions `CI` run `36343707812` on `674c1e1` had seven jobs. Six passed:
quality py3.10–3.13, native linux and native macos. **`native (windows)`
failed** at "Run the native tests". Job logs need authentication, and this
host has no `gh` and no token, so the failing case is **unknown**. The same
suite passed locally in both environments above. The previous branch run on
`14e9c57` passed. This branch has several earlier failed runs whose causes
were not examined here. The failed check is **not counted as passing**.

### Real Windows visual observations (packaged, isolated profile)

- **Explorer icon:** rendered through the shell's own
  `IShellItemImageFactory` at 16/32/48/256. It shows the purple B2 bubble at
  every size, so no stale pink icon cache was seen for this path.
  Explorer was not restarted and no pinned shortcut was touched.
- **Taskbar:** the running build's button shows the purple B2 bubble.
- **Title bar at 100%:** the purple-outlined face without glasses, per the
  mapping.
- **Not observed:** the primary display was showing the user's full-screen
  video, which hides the taskbar and its tray. I did not interrupt it, so the
  **tray** and **Alt+Tab** were not seen on screen. The same goes for
  **125/150% scaling** and the **200% B2 fallback**: display scaling was left
  at 100% because changing it was not approved. Automated evidence only:
  tray bytes (`hanly-icon-64.png`) are byte-identical in the bundle, and
  native tests pin the Qt size selection.
- The Control Center's pink "한" sidebar mark is the UI accent `#E88CA1`,
  which the Phase A handoff records as UI color, not icon identity.

### Asset and favicon checks (fresh bundle)

- All 13 bundled icon files are byte-identical to
  `packages/hanly-app/src/hanly_app/assets/icons/`.
- The executable carries 7 `RT_ICON` frames (16–256). Each is byte-identical
  to a frame of `packaging/icons/hanly.ico`.
- 371 bundled PNG/ICO/ICNS files were scanned, and none matches any of the
  15 archived pink SHA-256s. No `design/` source, `.icon` package, build
  script or rollback manifest is bundled.
- **Favicon, payload only:** the bundled page links `favicon.ico`, and
  `_inline_assets` inlines it. The bundled `favicon.ico` equals the
  committed purple face: frames 16/32/48, lavender `#C4BBEF` among its
  dominant colors, no pink hash. The Windows pywebview window has no tab
  strip or address bar, so **no visible favicon surface exists** to inspect.
  This is payload validation, not on-screen validation.

### Findings

- **Fixed now — `f5b583d`:** all five `# noqa: N802` in `hanly_dialog.py`
  were dead. Ruff selects only `E,F,I,UP`, and `RUF100` reported each one as
  unused. Only the comments were removed; the Qt/`QMessageBox` method names
  are unchanged. Behavior is unchanged, and existing dialog/prompt native
  tests (6 passed) cover the overrides, so no new test was warranted.
- **Dismissed as a product defect (local environment) — `.venv` is not
  release-constrained:** it carries PyQt6-Qt6 6.10.2 and torch 2.13. A
  bundle built from it failed the packaged worker with `WinError 1114`
  loading `c10.dll`, the conflict `packaging/README.md` documents. The same
  conflict explains 12–13 portable failures in
  `benchmarks/dev/tests/test_easyocr_stages.py` under `.venv`: an access
  violation importing torch after other suites, raising `OSError` that
  `importorskip` does not convert to a skip. Both pass in the constrained
  env. Its editable installs also carried stale 0.5.2 metadata, which gave
  the first build `version 0.5.2`; they were refreshed locally with
  `pip install --no-deps -e`. **Deferred:** re-create `.venv` with
  `-c packaging/release-constraints.txt`. Trigger: the next local Windows
  build or gate run that uses `.venv`.
- **Deferred:** `control_center_process.py:813,898` carry `# noqa: BLE001`,
  also dead under the current rule selection. Trigger: the next change to
  that file. It is outside this update's scope.
- **Deferred:** remote Windows native CI failure. Trigger: the next push.
  Read the job log with an authenticated `gh run view --log-failed`, and
  merge only on a green `native (windows)`.

### `benchmarks/.gitkeep`

This path does not exist in the tree and never existed in any branch's
history (`git log --all -- benchmarks/.gitkeep` is empty). The only tracked
`.gitkeep` is `benchmarks/fixtures/ocr/generated/.gitkeep`, added in
`d66a361`. It holds a two-line note on why that directory is empty.
`benchmarks/` itself always exists through tracked code. The generator
creates `generated/` itself (`write_sample` calls `mkdir(parents=True)`),
and nothing is ignored there. So the file is not needed for tooling, but
removing it would drop the directory and its explanation from checkouts.
**Kept; nothing removed.**

### Continuation

1. Push (human). Read the `native (windows)` log of the new CI run. If it
   fails, fix narrowly with a regression test. Merge only once every CI job
   is green.
2. Brief human check on the primary display, with no full-screen app
   covering it: the tray icon, and Alt+Tab while Hanly runs. Optionally
   switch display scaling to 125/150% (expect the face in the title bar)
   and 200% (expect the B2 icon), then restore it.
3. Re-create `.venv` against the release constraints.

Screenshots, build output and the isolated profile were kept outside the
repository.
