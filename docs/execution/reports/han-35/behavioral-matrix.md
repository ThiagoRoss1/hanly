# HAN-35 Behavioral and Correctness Matrix

Date: 2026-08-23  
Revision: `24ed285bd8cc33390875917d602a3a8526e77128` plus the uncommitted
HAN-35 benchmark harness  
Evidence classes: local automated tests and Windows development runtime only

## Fresh focused result

```text
.venv\Scripts\python.exe -m pytest <17 focused engine/desktop/resource files> -q
181 passed in 3.40s
```

The machine-readable result is retained at
`artifacts/benchmarks/evidence/behavioral-tests.xml`. It is raw, gitignored evidence;
this document is the durable classification. Passing a simulated behavior does
not convert it into frozen or cross-platform evidence.

## Matrix

| Scenario | Current result | Evidence and boundary |
| --- | --- | --- |
| Normal Korean lookup | **Pass** | Real Windows development lookup recognized `책을 읽습니다.`, selected `읽습니다.`, resolved `읽다`, and returned `to read`; engine E2E and pipeline tests repeat the normalized path. |
| ROI-local targeting and screen edges | **Pass (automated)** | Capture tests cover centered/clipped ROI, local target translation, negative/non-primary monitor geometry, malformed bytes, explicit regions, and nearest-monitor fallback. Actual mixed-DPI behavior remains unavailable. |
| Tilted/rotated OCR geometry | **Pass (automated)** | Resolver tests cover true-quad hit testing, tilted lines, every starting corner/winding, boundary points, thin/sliver regions, and deterministic provider order. |
| Punctuation | **Pass (automated, narrow)** | Pipeline ignores a later punctuation analysis when the selected word's first usable lemma is `읽다`; punctuation-rich real OCR is not a corpus result. |
| Spacing and line-level multi-word OCR | **Pass for current fixture** | Resolver narrows `책을 읽습니다.` by target and the real fixture selects the second span. Proportional advance remains explicitly deferred for variable-width/mixed-script/vertical text. |
| Several usable lemmas | **Pass with visible reduction** | Multi-word segments emit a diagnostic when only the first lemma is used; an already narrowed word does not emit the misleading multi-word diagnostic. |
| Unknown dictionary key | **Pass (automated)** | Real SQLite-provider tests return an empty tuple for `없는 단어`; the pipeline converts no entries into `NOT_FOUND`, not an exception. |
| Empty OCR | **Pass (automated)** | Pipeline returns `EMPTY` with retained context. |
| Unresolved target / low confidence / empty morphology | **Pass (automated)** | Each returns `UNUSABLE`; OCR evidence is retained and confidence policy remains optional/configured. |
| Provider or resolver failure | **Pass (automated)** | Failures at OCR, resolution, morphology, and dictionary boundaries become normalized `ERROR` results and retain stage diagnostics. |
| Rapid movement and latest-wins | **Pass (automated)** | Hover and controller tests cover timer replacement, one pending item, running-work supersession, post-dispatch currency checks, and stale-result suppression. |
| Pause/invalidate/shutdown in flight | **Pass (automated)** | Tests cover pending-delay cancellation, queued callback suppression, non-blocking UI shutdown, running worker completion, pending-work cancellation, and idempotent lifecycle. |
| Popup placement/presentation | **Pass (automated)** | Formatting covers every lookup status; placement flips/clamps at screen edges and non-zero virtual origins. Actual frozen paint latency and DPI are unavailable. |
| Hotkey registration/rebind | **Pass (automated)** | Tests cover normalization, duplicate collision rejection, live rebind, rollback, queued-trigger suppression, listener shutdown, and missing backend diagnostics. Actual global shortcut collisions remain a human runtime check. |
| Resource validation/update | **Pass (automated/local resources)** | Tests cover invalid/missing/wrapped models, SQLite validation, HTTPS, checksums, staging, atomic activation, rollback, and interrupted downloads. Production-sized KRDICT and real release assets are unavailable. |
| First and repeat offline launch | **Pass only through fake transport** | Repeat launch skips provisioning after resources validate; partial provisioning remains retryable. Frozen clean-profile/offline UX is still a human check. |
| Control Center / Qt event loop | **Pass (automated and historical Windows development)** | Tests cover bridge state/actions, main-thread constraints, Qt preparation order, asset purity, and live settings. macOS/Linux and frozen coexistence remain unavailable. |
| Frozen Windows/macOS/Linux runtime | **Unavailable** | Real Actions builds completed on all three OSes, but a build is not launch, OCR, input permission, tray, Wayland, or popup evidence. |

## Correctness gate used by the real fixture

The retained real-development sample is successful only because all observable
facts agree: the target lies inside the returned OCR region, OCR text and
confidence are present, selected text is `읽습니다.`, lemma/dictionary key is
`읽다`, dictionary status is `SUCCESS`, and the delivered controller request
was current. The committed image is deterministic regression evidence, not a
representative OCR-accuracy or latency corpus.

## Remaining behavioral triggers

- Retain and add any real variable-width, mixed-script, vertical, heavily
  tilted, shared-edge, or punctuation-rich OCR failure before changing target
  resolution.
- Run current frozen artifacts on actual Windows, macOS, Linux/X11, and
  Wayland; label every platform result separately.
- Exercise a production-sized KRDICT, real release resources, clean-profile
  provisioning, offline repeat launch, global hotkey collisions, mixed DPI,
  and popup interaction before publication.
