# HAN-40 Packaged Size Review Handoff

## Bundle

- Member issues: HAN-40 (Phase 2 of
  `docs/execution/post-v013-technical-wave.md`)
- Implementation ecosystem: first block by GPT-5.6 Sol orchestration with
  GPT-5.6 Luna xhigh workers; this continuation by Claude Opus directly, after
  a Phase B review of the first block returned **CONTINUE HAN-40**
- Date: 2026-09-10
- Branch: `codex/post-v013-technical-wave`; the first block is committed as
  `4e2301d`, this continuation is uncommitted working-tree state
- HAN-41 was not started

## Implemented

Three accepted packaging cuts, each built and validated on its own before the
next was layered on:

1. **EasyOCR collection.** Blanket `collect_all("easyocr")` replaced by the
   PyInstaller hook constrained to the languages the bundled recognition model
   accepts, `lang_codes = ["ko", "en"]`. Hanly's two model weights and the
   EasyOCR distribution metadata are supplied explicitly by the spec.
2. **QtWebEngine locales.** Of the 53 Chromium string catalogues the Qt hook
   collects, only `en-US.pak` and `ko.pak` are kept.
3. **Qt `.qm` translation catalogues.** All 157 are dropped.

Plus the correctness and tooling fixes the review asked for ahead of further
pruning — see *Review findings and their outcome* below.

### Why each cut is safe

- **EasyOCR.** `easyocr/easyocr.py::setLanguageList` is the only reader of
  `character/<lang>_char.txt`, and it reads one per entry in `lang_list`.
  `korean_g2` legally accepts `["ko"]` or `["ko", "en"]`
  (`easyocr.py:131`), and `easyocr.languages` is a supported `runtime.json`
  key, so both character sets stay. The other 99 languages go, of which
  `kn.txt` (11,093,265 B) and `te.txt` (3,950,323 B) are almost the whole
  saving.
- **QtWebEngine locales.** These carry Chromium's own interface text — context
  menus, error pages. The Control Center is app-authored HTML, so English and
  Korean cover what Hanly can present. The fallback path was exercised for
  real rather than assumed: this build host runs `AppleLocale = pt_BR` with
  `AppleLanguages = ("pt-BR", "ko-BR")`, and `pt-BR.pak` is one of the removed
  files. The frozen Control Center still opened, rendered its four controls,
  answered the JavaScript bridge, and wrote nothing at all to stderr. Later
  confirmed at the source: the WebEngine renderer launches with `--lang=pt`
  against `qtwebengine_locales` holding only `en-US.pak` and `ko.pak`, and
  falls back without a complaint.
- **Qt `.qm`.** Qt translates only through a `QTranslator` an application
  constructs and installs. Neither package, nor pywebview, nor pystray does
  (`grep -rn "QTranslator\|installTranslator"` finds nothing outside KRDICT's
  unrelated `translations` SQL table). Every Qt-supplied string therefore
  already renders untranslated today; this removes 157 inert files, not a
  behaviour.

### Where the rules live

All three act at PyInstaller analysis time in `packaging/hanly-desktop.spec`.
`hooksconfig` constrains EasyOCR's own hook; the two Qt rules are one
comprehension each, applied to `a.datas` after `Analysis` and before `PYZ`,
`COLLECT` and `BUNDLE`. Nothing is removed from a finished or signed bundle.

The `.qm` rule matches the `.qm` suffix rather than the `translations`
directory, because on Windows and Linux `qtwebengine_locales` lives *inside*
that directory; matching the directory would have deleted the locales the
first rule deliberately keeps. The macOS build confirms the two rules do not
interfere: the final bundle has 0 `.qm` files and exactly `en-US.pak` and
`ko.pak`.

## Main expected behavior

Unchanged. Fresh packaged Hanly starts through its single executable, opens
the Control Center and JavaScript bridge, reports EasyOCR 1.7.2, recognizes
real Korean text with the bundled CRAFT/Korean weights, performs Kiwi
morphology and external KRDICT lookup, and can replace a baseline installation
through HAN-42's native macOS handoff.

## Measured result

One constrained macOS environment, one disposable source root, one build
command. Every column is the real artifact, not an estimate.

| Metric | Fresh baseline | EasyOCR (`ko`) | + `ko`,`en` and fixes | + WebEngine locales | + Qt `.qm` — **final** |
|---|---:|---:|---:|---:|---:|
| Regular files | 5,266 | 5,109 | 5,110 | 5,059 | **4,902** |
| Package-tree bytes | 1,422,843,054 | 1,407,117,202 | 1,407,117,570 | 1,362,780,915 | **1,353,321,900** |
| ZIP non-directory members | 14,835 | 14,508 | 14,510 | 14,408 | **14,091** |
| ZIP uncompressed member bytes | 1,424,239,137 | 1,408,485,575 | 1,408,486,106 | 1,364,141,138 | **1,354,656,165** |
| ZIP compressed member bytes | 586,183,452 | 583,327,817 | 583,326,935 | 572,171,461 | **569,534,476** |
| ZIP bytes on disk | 590,897,702 | 587,953,803 | 587,953,415 | 576,760,631 | **574,040,120** |
| DMG bytes on disk | 674,651,423 | 669,358,535 | 669,293,942 | 654,985,656 | **646,917,268** |

Incremental saving per accepted cut, so no number is claimed twice:

| Cut | Files | Tree bytes | ZIP compressed | ZIP on disk | DMG |
|---|---:|---:|---:|---:|---:|
| EasyOCR collection | 157 | 15,725,852 | 2,855,635 | 2,943,899 | 5,292,888 |
| `ko` → `ko`,`en` correctness fix | +1 | +368 | −882 | −388 | −64,593 |
| QtWebEngine locales | 51 | 44,336,655 | 11,155,474 | 11,192,784 | 14,308,286 |
| Qt `.qm` catalogues | 157 | 9,459,015 | 2,636,985 | 2,720,511 | 8,068,388 |
| **Fresh baseline → final** | **364** | **69,521,154** | **16,648,976** | **16,857,582** | **27,734,155** |

Against the fresh baseline that is **4.89% of the package tree, 2.85% of the
ZIP on disk, and 4.11% of the DMG**. The published macOS ZIP goes from 563.52
MiB to **547.45 MiB**.

The `ko` → `ko`,`en` row is a correctness fix, not an optimization: it adds
`en_char.txt` (104 B) and the signature manifest entry that names it. Its
negative ZIP and DMG figures are compression and image-allocation noise around
a 368-byte tree change and should not be read as a saving.

**This is not comparable to the plan's 633.19 MiB Windows figure.** That
artifact was a different platform and a different Qt; the 75,989,572-byte gap
between it and this macOS baseline is not attributable to any change here.

## Review findings and their outcome

| Finding | Outcome |
|---|---|
| `lang_codes: ["ko"]` silently broke the supported `["ko","en"]` configuration | **Fixed** — `["ko", "en"]`, 104 B |
| No inventory guard on the file the new rule controls | **Fixed** — `easyocr/character/ko_char.txt` added to `smoke_packaged_runtime.REQUIRED_DATA_FILES`, so all three CI lanes check it before the OCR stage runs |
| Analyzer component grouping inert on the macOS `.app` layout | **Fixed** — `_logical_relative` now strips `Contents/Frameworks`, `Contents/Resources`, `Contents/MacOS` and a nested `_internal` |
| `duplicate_candidates` earned nothing and duplicated an existing field | **Fixed** — `same_size`, the duplicate `hash` field, and the `archive`/`archive_path` alias are gone; the ZIP accounting stayed |
| Spec comment overstated what the explicit Qt module list avoids | **Fixed** — corrected; QtWebEngine's hook brings the QML and multimedia trees in regardless |
| "symlink-aware accounting" wording, and tree-file vs ZIP-member counts | **Fixed** — stated plainly below |
| QtWebEngine locales never investigated | **Fixed** — accepted, 11,192,784 ZIP bytes |
| Qt `.qm` translations never investigated | **Fixed** — accepted, 2,720,511 ZIP bytes |
| `debug.pak` conclusion generalized from macOS | **Fixed** — restated as macOS-only evidence, deferred to the Windows lane |
| `QtQuick3D` visible once grouping was fixed | **Deferred** — out of this continuation's authorized scope; recorded as a future candidate below |

### How the two file counts relate

The package tree counts 4,902 regular files; the ZIP counts 14,091
non-directory members. The difference is macOS bundle symlinks: PyInstaller
cross-links `Contents/Resources` and `Contents/Frameworks`, `ditto` stores
each link as its own ZIP member, and the analyzer's tree walk skips symlinks
so a target is counted once. This is why an accepted cut removes roughly twice
as many ZIP members as regular files.

"Symlink-aware" means exactly that exclusion. The analyzer does **not** report
separate logical and physical sizes; the tree total is real bytes with links
excluded, and the ZIP totals are member metadata with links included as the
few bytes each occupies.

## Architecture / seams touched

- Packaging collection only. `packaging/hanly-desktop.spec` still owns frozen
  dependency/data collection and emits the same application shape, the same
  artifact names, and the same seven-asset release contract.
- `tools/smoke_packaged_runtime.py` gained one required data file.
- Developer-only instrumentation stayed under `benchmarks/dev/`.
- `hanly-app -> hanly`, provider interfaces, OCR behavior, resource ownership,
  updater ownership, and the one-entry-point invariant are unchanged. No
  approved architecture decision or invariant changed.

## Relevant files / diff areas

- `packaging/hanly-desktop.spec`
- `tools/smoke_packaged_runtime.py`
- `tests/test_packaging.py`
- `benchmarks/dev/package_composition.py`, `benchmarks/dev/cli.py`
- `benchmarks/dev/tests/test_probes.py`, `benchmarks/dev/tests/test_cli.py`

## Implementation-side validation already run

- Build environment, unchanged from the first block and re-confirmed: macOS
  26.6.2 arm64, Python 3.13.11, PyInstaller 6.22.2, hooks-contrib 2026.7,
  EasyOCR 1.7.2, Torch 2.14.0, torchvision 0.29.0, OpenCV-headless 5.0.0.93,
  PyQt6/WebEngine 6.11.0 with Qt 6.11.2, Kiwi 0.23.2 and `kiwipiepy_model`
  0.23.0. `pip check` passes in both the build venv and the repository venv.
- Project gates: `pytest` → **1,041 passed, 2 skipped**; Ruff → clean; mypy →
  no issues in 177 source files.
- **Three fresh builds**, each with the full frozen boundary below: the fixes
  build, the locale build, the `.qm` build. Nothing was layered on an
  unvalidated predecessor.
- Per build: strict-signing package build producing `Hanly.app`,
  `hanly-desktop-macos.zip` and `hanly-desktop-macos.dmg`; the real ZIP
  reconstructed into an empty directory; the real DMG mounted read-only;
  inventory on the reconstructed application; real frozen Korean OCR
  (`책울 읽습니다.`), Kiwi (`한국어`) and a one-entry KRDICT lookup; frozen
  Control Center with document title, four rendered controls and the
  JavaScript bridge; `codesign --verify --deep --strict`.
- Both frozen runs wrote **zero bytes to stderr** on the locale and `.qm`
  builds — no missing-resource, missing-locale or ICU complaint.
- **HAN-42 updater regression, run twice on real bundles**: the fresh baseline
  `Hanly.app` was installed, then replaced by the candidate through the actual
  `app_update_handoff` script. Both the locale candidate and the final
  artifact swapped in, relaunched through LaunchServices, returned the exact
  `0.1.3` acknowledgement, removed their transaction and backup, and left a
  valid signature and the expected payload — `en-US.pak` and `ko.pak` only,
  and no `.qm` files — at the installation path.
- Analyzer re-checked after the grouping fix: the final report's
  `unexpected_large_components` is empty because every component at or above
  the 50 MB threshold is a recognized family (`torch` 477,025,775; `PyQt6`
  441,033,104; `cv2` 123,557,451; `kiwipiepy_model` 109,042,347; `hanly_app`
  99,269,822). The next largest unrecognized component is the application's
  own 49,762,928-byte executable.
- Evidence reports: `baseline`, `accepted`, `fixes`, `locales` and `qm`
  `-package.json` under `/private/tmp/hanly-han40-baseline.3UfG6d/` — **expired,
  since purged by the operating system; every figure above is inline here** — with
  build logs and per-build `validate-*` directories beside them.

## Reverted or rejected experiments

- **torchvision blanket collection** (first block). Removing it saved 14 files,
  3,768,778 tree bytes and 1,270,976 ZIP bytes beyond the EasyOCR cut while
  dropping `_C_stable.so`, `image_stable.so` and six native dylibs, and
  retaining essentially all torchvision Python modules. Reverted.
- **macOS OpenCV FFmpeg dylibs.** Kept, on direct evidence: `otool -L
  cv2.abi3.so` shows non-weak `@loader_path/.dylibs/` links to `libavcodec`,
  `libavformat`, `libavdevice` and `libswscale`. Removing them breaks import.
  A custom OpenCV build is outside HAN-40.
- **`qtwebengine_devtools_resources.debug.pak`.** No filter added — see the
  deferral below.
- **Torch and Kiwi model assets.** Kept; no direct evidence makes a removal
  safe, and no experiment was run.

## Known limitations / intentionally unvalidated areas

- **Platform.** The accepted builds are macOS arm64 on Python 3.13.11. Release
  packaging uses Python 3.10, and clean native Windows, Linux and
  release-Python builds remain final CI/release validation by explicit human
  decision. No untested platform is recorded as passed. Both accepted Qt rules
  are platform-independent by construction, but only macOS has executed them.
- **`qtwebengine_devtools_resources.debug.pak` is deferred to the Windows
  lane.** It is absent from the tested fresh macOS/Qt 6.11.2 artifact, so no
  filter was added. It was historically present in the Windows artifact
  (81,573,852 / 15,334,066 bytes, measured in the plan's Qt 6.10.2 Windows
  ZIP). That build differed from this one in **both** platform and Qt version,
  so the macOS absence cannot attribute the difference to either, and no
  Windows-only exclusion has been written from macOS evidence. Decide it on a
  real Windows artifact. The normal `qtwebengine_devtools_resources.pak`
  (11,698,477 B) is retained per the approved plan.
- **Windows OpenCV FFmpeg is deferred to the Windows lane.** The stale `4100`
  DLL and the current `500` DLL cannot be decided from this clean macOS wheel.
  Note for whoever does: on Windows that file is a videoio *plugin* loaded on
  demand, not an import-time link, so the macOS linkage evidence above does
  not transfer either way. Validate wheel ownership and frozen OCR/import
  behavior there.
- **Windows and Linux updater lanes.** PowerShell execution, argument quoting,
  NTFS locking, console-less launch and a real Linux-kernel frozen swap remain
  HAN-42 release-lane checks. The macOS handoff passed on real bundles.
- **Popup, hide/restore, hotkey, tray and capture are still not exercised in a
  frozen artifact.** The packaged self-check has only `worker` and `ui` modes,
  so there is no automated frozen popup or hide/restore path; this limitation
  is unchanged by HAN-40. Source and integration tests pass, and the final
  native lanes retain that product smoke. Neither accepted Qt rule can reach
  the popup, which is a `QtWidgets` surface drawing app-authored text.
- **No warm-OCR before/after campaign.** Dependency versions and collection
  logic for the compute path are unchanged, and the frozen stage diagnostics
  moved within run-to-run noise. Performance is HAN-41 scope.
- **The signature is ad hoc build validity**, not Developer ID trust or
  notarization.
- One DMG mount failed once with `hdiutil: couldn't eject "disk10" - Resource
  busy`. Two of the developer's own Hanly DMGs were mounted at `/Volumes/Hanly`
  and `/Volumes/Hanly 1` at the time. Detaching only this run's own image and
  retrying passed. Environment collision, not a product defect.

## Explicitly out of this wave

Recorded as future candidates, not investigated and not to be treated as
approved work:

- `qml/QtQuick3D`, 2,875,531 uncompressed / 605,071 compressed bytes in the
  final artifact. Visible now that component grouping works; left alone by
  instruction.
- Broader QML pruning, the non-debug `qtwebengine_devtools_resources.pak`, the
  Torch native payload, Kiwi models, and a custom OpenCV build. Each has
  materially worse risk/reward than anything accepted here.

## Suggested review targets

- The two `a.datas` comprehensions in `packaging/hanly-desktop.spec`: that
  they run after `Analysis` and before the bundle is assembled and signed,
  that the `.qm` rule cannot reach `qtwebengine_locales` on Windows or Linux,
  and that both are exact rather than pattern-broad.
- The claim that no `QTranslator` is installed anywhere in the shipped
  process, since the whole `.qm` cut rests on it.
- Whether `en-US.pak` plus `ko.pak` is the right locale set for the product's
  intended users, which is a product decision rather than a packaging one.
- The EasyOCR language contract on a native Windows and Linux lane.
- Fresh Windows and Linux reports, rather than transferring macOS file names
  or savings across platforms.

## Review assignment

Human-selected after implementation. Not started.
