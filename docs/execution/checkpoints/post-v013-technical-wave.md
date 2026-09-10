# Post-v0.1.3 technical wave — execution checkpoint

## Authority and working state

- Approved plan: `docs/execution/post-v013-technical-wave.md`.
- Execution order for this run: HAN-42 reconciliation, then HAN-40 only.
  HAN-41 is outside the authorized boundary.
- Branch: `codex/post-v013-technical-wave`, created without disturbing the
  inherited uncommitted HAN-42 work.
- Baseline HEAD: `ed51a6a`.
- Sol orchestrates and reviews; production implementation is delegated to
  explicitly configured GPT-5.6 Luna xhigh workers.
- No commit is planned: the effective repository Git identity is unset, so a
  local commit cannot be verified to preserve the human identity. Never push,
  create a PR, or mutate Linear in this run.

### Continuation run (2026-09-10)

- The first HAN-40 block was committed as `4e2301d`, reviewed, and returned
  **CONTINUE HAN-40**. The human accepted that verdict and authorized one
  bounded continuation: the review's correctness and tooling fixes, then two
  isolated Qt experiments, then stop.
- Executor: Claude Opus, directly. HAN-41 remains outside the boundary.
- Continuation changes are uncommitted working-tree state. Nothing was pushed,
  no PR was opened, and Linear was not touched.

## Checkpoints

| Checkpoint | Status | Evidence | Next step |
|---|---|---|---|
| C-HAN42-RECONCILED | COMPLETE | Current diff matches the handoff; no blocking regression. Full suite 1033 passed, 2 skipped with LaunchServices access; Ruff clean; mypy clean (177 files). | HAN-40 Block A. |
| C-HAN40-A | COMPLETE | Existing inventory now measures optional ZIP compression, distinct EasyOCR-weight and Kiwi families, and bounded duplicate candidates. Focused tests: 29 passed; Ruff clean. Fresh constrained macOS build, inventory, real OCR/Kiwi/KRDICT worker smoke, frozen Control Center/bridge, and codesign verification passed. | Review evidence for the first safe, measurable pruning experiment. |
| C-HAN40-EASYOCR | ACCEPTED | Replaced blanket EasyOCR collection with the official hook constrained to `ko`; explicit weights remain. Same environment: 164 files and 15,774,192 tree bytes removed; ZIP shrank 2,969,156 bytes. Real Korean frozen OCR, Kiwi, KRDICT, inventory, Control Center/bridge, and codesign passed. Explicit EasyOCR metadata copying was added after smoke exposed its loss. | Build and measure the separately reviewed torchvision collection experiment. |
| C-HAN40-TV | REVERT | Removing blanket torchvision collection saved only 14 files, 3,768,778 tree bytes, and 1,270,976 ZIP bytes; the removed content was `_C_stable.so`, `image_stable.so`, and six native dylibs while essentially all Python modules remained. Risk outweighed the 1.21 MiB download gain. | Restore torchvision collection and build the final accepted candidate. |
| C-HAN40-GATE | COMPLETE | Final same-environment result: 157 files and 15,725,852 tree bytes removed; ZIP shrank 2,943,899 bytes and DMG shrank 5,292,888 bytes. Reconstructed ZIP inventory, mounted DMG, real frozen Korean OCR/Kiwi/KRDICT, EasyOCR 1.7.2 metadata, Control Center/bridge, strict codesign, and a native baseline-to-optimized macOS updater handoff passed. Full suite: 1,038 passed, 2 skipped; Ruff clean; mypy clean (177 files). | Write the HAN-40 Review Handoff and stop. |
| C-HAN40-HANDOFF | STOP | `docs/execution/review-handoffs/han-40-packaged-size.md` records the implementation, exact artifacts, accepted/reverted experiments, and native-platform limits. | Human-selected Phase B review. Do not start HAN-41 in this run. |
| C-HAN40-REVIEW | CONTINUE | Phase B review found the accepted cut honest and well-evidenced, but the QtWebEngine locale catalogues and Qt `.qm` translations were never examined, and five correctness/tooling findings stood. | Apply the fixes, then run the two Qt experiments in isolation. |
| C-HAN40-FIXES | ACCEPTED | EasyOCR constrained to `ko`,`en`; `easyocr/character/ko_char.txt` added to the frozen inventory guard; analyzer taught the macOS `.app` layout; `same_size`/duplicate-hash/parameter-alias additions removed; three misleading comments corrected. Fresh build, inventory, real frozen OCR/Kiwi/KRDICT, Control Center/bridge, ZIP and DMG reconstruction, strict codesign all passed. | Build and measure the locale experiment. |
| C-HAN40-LOCALES | ACCEPTED | Kept `en-US.pak` and `ko.pak` of 53. Incremental: 51 files, 44,336,655 tree bytes, 11,155,474 compressed member bytes, 11,192,784 ZIP bytes, 14,308,286 DMG bytes. Frozen boundary passed with zero stderr; the removed-locale fallback was exercised for real, this host being `pt_BR`. Native HAN-42 handoff swapped a fresh baseline bundle for the candidate. | Build and measure the `.qm` experiment separately. |
| C-HAN40-QM | ACCEPTED | All 157 `.qm` catalogues dropped; nothing in the shipped process installs a `QTranslator`, so no string changes. Incremental: 157 files, 9,459,015 tree bytes, 2,636,985 compressed member bytes, 2,720,511 ZIP bytes, 8,068,388 DMG bytes. `qtwebengine_locales` verified intact. Frozen boundary passed with zero stderr. | Run the final gate. |
| C-HAN40-FINAL | COMPLETE | Fresh baseline to final: 364 files, 69,521,154 tree bytes (4.89%), 16,648,976 compressed member bytes, 16,857,582 ZIP bytes (2.85%), 27,734,155 DMG bytes (4.11%). ZIP 563.52 -> 547.45 MiB. Full suite: 1,041 passed, 2 skipped; Ruff clean; mypy clean (177 files); `pip check` clean in both venvs. HAN-42 updater regression re-run on the final artifact. | Update the Review Handoff and stop. |
| C-HAN40-COMPLETE | STOP | HAN-40 is complete for this wave: the obvious safe wins are exhausted, the product works, and every remaining candidate has materially worse risk/reward. | Human-selected Phase B review of the continuation. Do not start HAN-41. |

## HAN-40 fresh macOS baseline

- Disposable source/build root:
  `/private/tmp/hanly-han40-baseline.3UfG6d/source`.
- Host: macOS 26.6.2, arm64; Python 3.13.11 (the only local interpreter;
  release CI remains Python 3.10).
- PyInstaller 6.22.2; hooks-contrib 2026.7; EasyOCR 1.7.2; Torch 2.14.0;
  torchvision 0.29.0; OpenCV headless 5.0.0.93; PyQt6/WebEngine 6.11.0
  with Qt 6.11.2; Kiwi 0.23.2/model 0.23.0.
- Package tree: 5,266 regular files; 1,422,843,054 bytes.
- ZIP: 14,835 non-directory members; 1,424,239,137 uncompressed member
  bytes; 586,183,452 compressed member bytes; 590,897,702 archive bytes.
- DMG: 674,651,423 bytes.
- `qtwebengine_devtools_resources.debug.pak` is absent from this clean build.
  The normal `qtwebengine_devtools_resources.pak` remains (11,698,477 bytes).
- Windows-only `opencv_videoio_ffmpeg4100_64.dll` is not testable on this host;
  its clean-environment absence still needs the Windows release lane.
- Detailed bounded inventory:
  `/private/tmp/hanly-han40-baseline.3UfG6d/baseline-package.json`.

## Accepted HAN-40 result

### EasyOCR blanket collection

- Why included: the spec used `collect_all("easyocr")` in addition to the
  constrained PyInstaller 2026.7 hook.
- Removed: exposed EasyOCR source, DBNet development files, and non-Korean
  character data. The hook retains Korean character data and the dynamic
  recognition imports; Hanly still supplies `craft_mlt_25k.pth` and
  `korean_g2.pth` explicitly.
- Baseline to experiment: 5,266 to 5,102 regular files; 1,422,843,054 to
  1,407,068,862 tree bytes; ZIP 590,897,702 to 587,928,546 bytes.
- Evidence report:
  `/private/tmp/hanly-han40-baseline.3UfG6d/easyocr-package.json`.
- Frozen smoke found EasyOCR distribution metadata was no longer incidental;
  the shared spec now copies it explicitly rather than restoring broad
  collection.
- Final accepted package tree: 5,109 regular files and 1,407,117,202 bytes.
  The ZIP has 14,508 non-directory members, 1,408,485,575 uncompressed member
  bytes, 583,327,817 compressed member bytes, and is 587,953,803 bytes on disk.
  The DMG is 669,358,535 bytes.
- Same-environment final savings: 157 regular files, 15,725,852 tree bytes
  (1.11%), 2,943,899 ZIP bytes (0.50%), and 5,292,888 DMG bytes (0.78%).
- Detailed bounded inventory:
  `/private/tmp/hanly-han40-baseline.3UfG6d/accepted-package.json`.
- The reconstructed ZIP and mounted DMG passed inventory; the reconstructed
  application passed real frozen Korean OCR, Kiwi, KRDICT, Control Center,
  rendered controls, JavaScript bridge, package-version reporting, and strict
  signature verification. A real macOS handoff swapped a copied baseline
  bundle for this accepted bundle, received the `0.1.3` acknowledgement,
  cleaned its transaction/backup, and left the optimized signed application at
  the install path.

## HAN-40 continuation result

Same disposable root, same constrained venv, same build command as the
baseline above, so every figure is same-environment.

| Metric | Fresh baseline | EasyOCR (`ko`) | + `ko`,`en` + fixes | + locales | + `.qm` — final |
|---|---:|---:|---:|---:|---:|
| Regular files | 5,266 | 5,109 | 5,110 | 5,059 | 4,902 |
| Package-tree bytes | 1,422,843,054 | 1,407,117,202 | 1,407,117,570 | 1,362,780,915 | 1,353,321,900 |
| ZIP members | 14,835 | 14,508 | 14,510 | 14,408 | 14,091 |
| ZIP uncompressed member bytes | 1,424,239,137 | 1,408,485,575 | 1,408,486,106 | 1,364,141,138 | 1,354,656,165 |
| ZIP compressed member bytes | 586,183,452 | 583,327,817 | 583,326,935 | 572,171,461 | 569,534,476 |
| ZIP bytes on disk | 590,897,702 | 587,953,803 | 587,953,415 | 576,760,631 | 574,040,120 |
| DMG bytes on disk | 674,651,423 | 669,358,535 | 669,293,942 | 654,985,656 | 646,917,268 |

- The `ko` to `ko`,`en` column is the correctness fix, not an optimization: it
  adds `en_char.txt` (104 bytes) and the signature entry naming it. Its
  negative ZIP and DMG figures are compression and image-allocation noise.
- Evidence reports: `fixes-`, `locales-` and `qm-package.json` beside the
  earlier ones, with build logs and per-build `validate-*` directories.
- Both accepted Qt rules act on `a.datas` after `Analysis` and before `PYZ`,
  `COLLECT` and `BUNDLE`. Nothing is removed from a finished or signed bundle.
- The `.qm` rule matches the file suffix, not the `translations` directory,
  because Windows and Linux keep `qtwebengine_locales` inside that directory.

## Rejected or deferred HAN-40 candidates

- `qtwebengine_devtools_resources.debug.pak`: **deferred to the Windows lane.**
  Absent from the tested fresh macOS/Qt 6.11.2 artifact, so no exclusion was
  added. Historically present in the Windows artifact (81,573,852 / 15,334,066
  bytes in the plan's Qt 6.10.2 Windows ZIP). That build differed in both
  platform and Qt version, so the macOS absence attributes the difference to
  neither, and no Windows-only exclusion was written from macOS evidence.
  The normal devtools resource is an upstream-owned hook input and remains.
- `qml/QtQuick3D` (2,875,531 / 605,071 bytes in the final artifact): visible
  once analyzer grouping was fixed, deliberately left alone. A future
  candidate, not approved work.
- Broader QML pruning and the non-debug `qtwebengine_devtools_resources.pak`:
  out of this wave.
- macOS OpenCV FFmpeg dylibs: kept. The wheel owns them and `cv2.abi3.so` has
  non-weak direct and transitive links to the video stack; removing them risks
  breaking import and OCR. A custom OpenCV build is out of scope.
- torchvision blanket collection: measured and reverted as recorded above.
- Torch and Kiwi model assets: kept; no direct evidence makes removal safe.
- Windows OpenCV `4100`/`500` DLL decisions remain native-Windows validation,
  not something inferred from this macOS artifact.

## Native updater evidence and deferred platforms

- macOS: the native handoff script ran against the fresh baseline and accepted
  frozen bundles. Swap, LaunchServices relaunch, version acknowledgement,
  transaction cleanup, accepted-payload identity, and final codesign passed.
- macOS, continuation: re-run twice on real bundles, once for the locale
  candidate and once for the final artifact. Both installed a fresh baseline
  `Hanly.app`, replaced it through the actual `app_update_handoff` script,
  received the exact `0.1.3` acknowledgement, removed the transaction and
  backup, and left a valid signature with the expected payload — `en-US.pak`
  and `ko.pak` only, and no `.qm` files — at the installation path.

- Windows: PowerShell execution, argument quoting, NTFS locking, console-less
  launch, and a frozen old-to-new swap require a real Windows lane.
- Linux: native-kernel extraction/relaunch and a real frozen old-to-new swap
  require a real Linux lane.
- These are final clean-build / CI / release-tag checks by explicit human
  decision. They do not block HAN-40, and neither platform is recorded as
  passed.

## Resume rule

HAN-40 Phase A is complete at its Review Handoff, including the authorized
continuation. The obvious safe wins are exhausted, the product works, and
every remaining candidate has materially worse risk/reward, so no further
package-size search is authorized — not even for candidates the repaired
analyzer now makes visible.

Do not start HAN-41 in this run. Resume only with explicit human authorization
for the separately selected HAN-40 Phase B reviewer or for a later phase.
