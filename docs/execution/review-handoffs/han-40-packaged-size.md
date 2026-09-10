# HAN-40 Packaged Size Review Handoff

## Bundle

- Member issues: HAN-40 (Phase 2 of
  `docs/execution/post-v013-technical-wave.md`)
- Implementation ecosystem: GPT-5.6 Sol orchestration and implementation-side
  review, with explicitly configured GPT-5.6 Luna xhigh workers for production
  implementation
- Date: 2026-09-10
- Branch: `codex/post-v013-technical-wave`; baseline HEAD `ed51a6a`
- Nothing committed or pushed. The effective repository Git identity is unset,
  so no local commit was created under an unverifiable identity.

## Implemented

- Extended the existing developer package-composition report with optional ZIP
  file/member/compression totals, per-family archive totals, deterministic ten
  largest members, distinct EasyOCR-weight and Kiwi/model families, and bounded
  same-size/hash duplicate evidence.
- Replaced blanket `collect_all("easyocr")` packaging with PyInstaller's EasyOCR
  hook constrained to Korean (`lang_codes = ["ko"]`).
- Kept Hanly's two explicitly provisioned EasyOCR model weights and added
  explicit EasyOCR distribution metadata after the first experiment exposed
  that blanket collection had supplied it incidentally.
- Kept torchvision's explicit collection after a separate measured removal
  experiment yielded little benefit while dropping native modules.
- Preserved the macOS ZIP/DMG names and the wider seven-asset release contract;
  no runtime dependency or application entry point changed.

## Main expected behavior

Fresh packaged Hanly still starts through its single executable, opens the
Control Center and JavaScript bridge, reports EasyOCR 1.7.2, recognizes real
Korean text with the bundled CRAFT/Korean weights, performs Kiwi morphology and
external KRDICT lookup, and can replace a baseline bundle through HAN-42's
native macOS handoff. The exposed EasyOCR payload now contains Korean character
data and metadata instead of the package's blanket source/data tree.

In one constrained macOS environment, the final accepted result is:

| Metric | Fresh baseline | Accepted | Reduction |
|---|---:|---:|---:|
| Regular files | 5,266 | 5,109 | 157 |
| Package-tree bytes | 1,422,843,054 | 1,407,117,202 | 15,725,852 (1.11%) |
| ZIP non-directory members | 14,835 | 14,508 | 327 |
| ZIP uncompressed member bytes | 1,424,239,137 | 1,408,485,575 | 15,753,562 |
| ZIP compressed member bytes | 586,183,452 | 583,327,817 | 2,855,635 |
| ZIP bytes on disk | 590,897,702 | 587,953,803 | 2,943,899 (0.50%) |
| DMG bytes on disk | 674,651,423 | 669,358,535 | 5,292,888 (0.78%) |

The accepted ZIP is 560.72 MiB. The investigation's 633.19 MiB Windows ZIP is
historical cross-platform evidence only; its 75,989,572-byte difference from
this macOS artifact is not attributed to this change.

## Architecture / seams touched

- Packaging collection only: `packaging/hanly-desktop.spec` still owns frozen
  dependency/data collection and still emits the same application shape.
- Developer-only evidence only: package-composition instrumentation remains
  under `benchmarks/dev/`; nothing was added to either production package.
- `hanly-app -> hanly`, provider interfaces, OCR behavior, resource ownership,
  updater ownership, and the one-entry-point invariant are unchanged.
- No approved architecture decision or invariant changed.

## Relevant files / diff areas

- `packaging/hanly-desktop.spec`
- `tests/test_packaging.py`
- `benchmarks/dev/package_composition.py`
- `benchmarks/dev/cli.py`
- `benchmarks/dev/tests/test_probes.py`
- `benchmarks/dev/tests/test_cli.py`

The shared working tree also contains the preceding HAN-42 phase. Its scope and
validation are recorded separately in
`docs/execution/review-handoffs/han-42-updater-reliability.md`.

## Implementation-side validation already run

- Fresh build environment: macOS 26.6.2 arm64, Python 3.13.11, PyInstaller
  6.22.2, hooks-contrib 2026.7, EasyOCR 1.7.2, Torch 2.14.0, torchvision
  0.29.0, OpenCV-headless 5.0.0.93, PyQt6/WebEngine 6.11.0 with Qt 6.11.2,
  Kiwi 0.23.2 and `kiwipiepy_model` 0.23.0. `pip check` passed.
- Analyzer-focused tests: 29 passed; packaging tests after the accepted spec:
  42 passed.
- Final project gates: `.venv/bin/python -m pytest` -> 1,038 passed, 2 skipped;
  Ruff -> clean; mypy -> no issues in 177 source files.
- Strict-signing package build produced `Hanly.app`,
  `hanly-desktop-macos.zip`, and `hanly-desktop-macos.dmg` successfully;
  `codesign --verify --deep --strict` passed before and after updater handoff.
- The actual ZIP was reconstructed into an empty directory and the actual DMG
  mounted read-only. Both passed product/inventory checks. EasyOCR, its 1.7.2
  metadata, both model weights, certifi, Kiwi native/model inputs, and the
  signature were present; KRDICT and developer tooling were absent.
- Reconstructed frozen worker: lookup-worker construction, Korean OCR
  (`책울 읽습니다.`), morphology (`한국어`), and one-entry KRDICT lookup passed.
  The accepted OCR stage was 4,129.8 ms versus 4,107.4 ms in a final baseline
  run (0.55% higher); this is one cold diagnostic sample, not a warm-latency
  benchmark or regression claim.
- Reconstructed frozen UI: main window, document, four controls, and the
  JavaScript bridge passed. Main-window duration was 3,440.9 ms versus 3,415.2
  ms in a final baseline run (0.75% higher), likewise one diagnostic sample.
- Native macOS updater regression: the actual handoff script replaced a copied
  baseline `Hanly.app` with the reconstructed optimized app, relaunched it via
  LaunchServices, received the exact `0.1.3` readiness acknowledgement,
  removed the transaction and backup, and left the accepted payload and valid
  signature at the installation path.
- Accepted inventory report:
  `/private/tmp/hanly-han40-baseline.3UfG6d/accepted-package.json`; fresh
  baseline report:
  `/private/tmp/hanly-han40-baseline.3UfG6d/baseline-package.json`.

## Reverted or rejected experiments

- Removing blanket torchvision collection was reverted. It saved only 14
  files, 3,768,778 tree bytes, and 1,270,976 ZIP bytes beyond the EasyOCR cut,
  while removing `_C_stable.so`, `image_stable.so`, and six native dylibs and
  retaining essentially all torchvision Python modules.
- The fresh Qt 6.11.2 build contains no
  `qtwebengine_devtools_resources.debug.pak`, so no stale filter was added. The
  normal 11,698,477-byte devtools resource is upstream-owned and retained.
- OpenCV FFmpeg dylibs were retained: this wheel owns them, and `cv2.abi3.so`
  has direct/transitive native links into that stack. A custom OpenCV build is
  outside HAN-40.
- Torch and Kiwi model assets were retained because no direct evidence made a
  removal safe.

## Known limitations / intentionally unvalidated areas

- The fresh accepted build is macOS arm64 on Python 3.13.11. Release packaging
  uses Python 3.10; clean native Windows, Linux, and release-Python builds remain
  final CI/release validation by explicit human decision. No untested platform
  is recorded as passed.
- The stale Windows OpenCV `4100` DLL and current Windows `500` DLL candidates
  cannot be decided from this clean macOS wheel. Validate wheel ownership and
  frozen OCR/import behavior on Windows before adding any filter.
- Windows PowerShell/NTFS updater behavior and a real Linux-kernel frozen swap
  remain HAN-42 release-lane checks. The macOS optimized-artifact handoff passed.
- Frozen worker/UI checks do not manually exercise native hotkey, tray,
  capture, popup, or hide/restore behavior in the accepted artifact. Source and
  integration tests pass, but the final native lanes retain that product smoke.
- No repeatable warm-OCR before/after campaign was added. Collection logic and
  dependency versions are unchanged, and the single frozen diagnostics above
  show no material stage movement; performance remains HAN-41 scope.
- The signature is ad hoc build validity, not Developer ID trust or
  notarization.

## Suggested review targets

- Confirm that the EasyOCR 1.7.2 hook's `lang_codes = ["ko"]`, explicit two
  weights, Korean character data, dynamic recognition imports, and copied
  metadata form a stable packaging contract on every native lane.
- Inspect the archive analyzer's ZIP accounting, family classification,
  deterministic largest-member ordering, and both file/byte bounds for
  duplicate evidence.
- Check that keeping torchvision collection is the conservative choice given
  the small measured gain and removed native surfaces.
- Compare fresh Windows/Linux reports rather than transferring macOS file names
  or savings across platforms.

## Review assignment

Human-selected after implementation. Not started.
