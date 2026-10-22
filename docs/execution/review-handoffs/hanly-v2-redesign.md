# Hanly V2 Visual Redesign Review Handoff

## Bundle

- Human-authorized workstream: `design/hanlyV2`; no new Linear issue or lifecycle transition was inferred from completed V1 work.
- Updated: 2026-10-22. Phase A implementation and bounded follow-up are closed; native acceptance is still blocked. Phase B deep review has not started.
- Original baseline: `43ba8d6`, identical to local `main` and the migration branch's tree. Correction baseline: `15b87a8`.
- GPT implementation with bounded Luna xhigh workers for scene rendering, presentation components and preferences. Commit authorized by the human; no push or merge.

## Implemented

- Six real Control Center sections use the supplied frames, button states, icons, slider, progress artwork and cursor. Normal/Compact navigation and Pixel/Normal popup font persist through the existing validated Python settings bridge.
- Sun/moon use the gallery's 1.5-second entrance/exit and rotation. Each day/night layer blends on an isolated transparent canvas before composition in scene order, preventing night textures from adding into the house/tree beneath them. Original assets and uniform village scaling remain in use.
- Compact mascot poses fit inside the plaque, including the automatic <=760px fallback. The cloud and clean compact plaque carry their own interior fills and transparent outer edges; the older rectangular paper overlay is removed.
- Removed legacy logo/slider backgrounds, rectangular pseudo-element fills, selected-row shadows and obsolete interface styles. Panel rows have side and bottom insets; runtime Permissions is fully inside the frame. Titles, capture icons and disclosure copy are centered. Content scrolls and resets to the top when changing sections.
- `panel-popup-clean-v2` and `panel-cloud-clean-v2` now use integer-grid SVG redraws of the supplied stepped/scalloped artwork. Contours are mirrored horizontally and vertically, with three uniform one-pixel rim bands, flat interiors and no cast shadow or texture noise. The panel's bottom corners now use the same 16px geometry as the top. `tools/design/build_clean_frames.mjs` regenerates both variants; references, palettes and slice geometry are recorded beside the assets. Original files remain untouched.
- Preference saves track pending state per setting/command. Appearance choices retain artwork while saving and guard duplicate clicks; unrelated controls and the scene stay mounted.
- The brand uses the supplied book artwork alone. The overlaid system-font `한` and its paper square were removed after human feedback; normal navigation displays the 32px source at 2x and compact navigation at 1x. Earlier offline OCR evidence for the overlaid glyph is historical and does not establish acquisition acceptance for this restored artwork.
- Popup title is 38px/46px and primary translation 21px/28px (previously 40px/48px and 22px/29px). Details, sequence currency, native measurement and expansion contracts are preserved.
- macOS Control Center reserves a 40px titlebar above the pixel frame, retaining native close/minimize/fullscreen controls with clear space around them. The drag region starts after the controls. A dedicated capability permits only this window to start dragging. Windows/Linux retain their native titlebars. Popup window policy is unchanged.

## Latest artwork follow-up — 2026-10-20

Baseline `10ef95b`. At commit `7b46915`, the human had explicitly deferred
automated tests and manual app testing; only isolated artwork was inspected.
That revision had not rebuilt or relaunched the native app. The completion
below supersedes that validation status.

The two revised frames were rendered and inspected as isolated assets in light
and dark palettes. Evidence: `artifacts/lab/runs/20261020-artwork-polish/`.
The inspection covers contour symmetry, corner joins, flat interiors and the
original logo at integer scale; it is not real-app acceptance.

The runtime card uses a contained 80px mascot canvas and a separate full-width
detail row for active/error states. Stopped shows the short status plus runtime,
engine and version facts; its longer detail remains in the card tooltip. Compact
poses remain inside the plaque, including the sleeping pose's baseline. Camera
icons receive integer optical offsets for the lower visual mass of their body.
Native titlebar spacing and the updated card were subsequently inspected in the
completion run below.

## Native integration completion — 2026-10-20

Baseline `7b46915`. The human requested completion in the actual application.
Rebuilt the embedded frontend, unbundled source executable and local debug
`Hanly.app`, then retired the older running debug instance and opened the final
bundle through the normal Python launcher with the real service. Evidence:
`artifacts/lab/runs/20261020-app-integration/`.

Native inspection covered all six sections, both themes, Normal/Compact
navigation, expanded capture settings, the slider, hover activation selection,
runtime Permissions spacing, restored logo, camera alignment, contained mascot
and the 40px native titlebar clearance. Two integration gaps were corrected:
compact navigation now uses `panel-plaque-clean-v2` without a separate paper
rectangle, and Logs filters use button artwork with a visible selected state.
Logs All/Error filtering was exercised. Theme/navigation saves persisted across
the final restart. Original Dark/Normal/Normal-font/always-active preferences
were restored; capture remained stopped. No blank remount was observed during
these setting changes; this is not exhaustive frame-by-frame acceptance.

Current revision passed TypeScript, 12 Node bridge tests, 52 React tests, 36
contrast tests and production frontend/Tauri debug bundle builds. The React
suite includes the Lab's focused Control Center and popup DOM probes; it does
not establish native acquisition or OCR acceptance. Historical full Python and
Rust results below were not rerun for these presentation-only changes.

The final open build is
`apps/desktop/src-tauri/target/debug/bundle/macos/Hanly.app`; source `hanly` also
resolves the rebuilt unbundled debug executable. Existing open apps do not
reload an embedded frontend automatically. `/Applications/Hanly.app` and official
release packages were not replaced. Existing popup/acquisition limitations
below remain in effect. No capture backend, signing, permission or domain
contract was changed.

## Source organization and boundaries

`ControlCenterPage.tsx` owns the shell; six sections live in `pages/controlCenter/`, with shared controls in `components/controlCenter/`. Popup presentation and formatting live in `components/popup/`; `PopupPage.tsx` retains native event and measurement lifecycle. Village layer metadata lives separately from its renderer.

Layout, spacing and typography use Tailwind. Focused styles own palettes, nine-slice artwork, native range parts, animation and responsive artwork fitting. The previous Control Center stylesheet fell from about 1,250 to 247 lines, popup CSS from 507 to 162, and the large pixel stylesheet was pruned and split into focused files under 350 lines each.

All 141 supplied media/font/cursor files retain their original bytes. Prototype mocks, DOM decorators, simulator and preview controls remain excluded from the product. Engine, OCR selection, acquisition, signing, updater installation and configuration contracts were not replaced. No OCR research was merged.

## Implementation-side checks

| Check | Result |
| --- | --- |
| Full portable suite | 2,691 passed, 2 skipped (opt-in real EasyOCR; non-macOS Vision path) |
| Ruff / mypy | Passed; 365 Python files checked |
| TypeScript / Node bridge / React | Passed; 12 Node and 52 React tests |
| Contrast | 36 passed against actual palettes |
| Vite production build / Tauri debug app | Passed |
| Rust tests / fmt / clippy | 23 tests passed; fmt and clippy with warnings denied passed |
| Lab CC-CONTROLS / HOVER-POPUP / SETTINGS | All passed; DOM/mock IPC and simulated-service evidence only |
| Offline real lookup of the native logo crop | EasyOCR + morphology + KRDICT; zero correctness failures for `한` |
| Whitespace | Passed |

The deferred-save regression verifies that a pending preference save keeps other groups usable and the active section mounted. React tests use jsdom and do not validate canvas pixels. No new performance benchmark comparison is claimed.

## Visual and native evidence

The approved delivery, editable preview and gallery were consulted. This correction also used the seven screenshots supplied in chat. The three supplied MOV paths had already disappeared from their temporary directories; their contents were not viewed.

All six native Control Center sections were inspected on macOS, along with saved Compact/Dark/Normal preferences, frame insets, the slider and native titlebar controls. Browser validation at 720x560 reported document width 720 with an 88px compact fallback rail. The scene transition was inspected in the app/browser; no exhaustive frame-by-frame acceptance is claimed.

An ignored, opt-in Lab fixture supplied authored dictionary results to the real debug service solely for popup presentation. The native popup measured **380x232**, expanded through Details to **460x362**, and collapsed back to 380x232. Both measured states retained `(616,246)`, with `presented=true`. Close worked. This is presentation evidence, not acquisition evidence.

The focused panel-asset follow-up passed TypeScript, 52 React tests, 36 contrast tests and frontend/debug app builds. Both themes were inspected in the browser and the final native app; evidence is under `artifacts/lab/runs/20261019-panel-cleanup/`.

Current correction evidence: `artifacts/lab/runs/20261019-v2-corrections/` (summary, provenance, native screenshots, measurements and check logs). Source was dirty on `15b87a8`; the final executable hash is recorded. Earlier integration evidence remains under `20261019-hanly-v2/`.

## Concrete limitations / acceptance still required

- The LaunchServices Lab smoke tour (`20261019-144656-tour`) aborted after `capture_start_failed` with `permission_required`: zero hovers/captures/OCR results. It is **not** a passing tour. Baseline inspection confirmed the older tour used a different measurement protocol, so no comparison was made.
- A separate terminal-launched debug session reported 2/2 grants and allowed capture to start. CUA pointer/shortcut attempts over the logo did not produce a confirmed popup. The offline logo crop passed real EasyOCR lookup, but continuous hover and Push to Hover over the logo still require manual acceptance. Terminal-inherited grants do not establish the LaunchServices or installed app's grants.
- No OS permission was requested/reset, signing identity changed, or capture backend substituted. Historical MSS latency and application-identity issues are not declared resolved.
- Windows/Linux native rendering, DPI, native acquisition, reader focus and word-to-popup crossing/retention still need those hosts and real manual acceptance. Existing native policies and portable tests do not establish every product scenario.
- The inspected bundle is a source-development debug app. The installed `/Applications/Hanly.app` and official packaged releases were not replaced or accepted. No updater installation or deep review was performed.
- Floral/Ornamental alternatives remain experimental external references.

Review assignment remains human-selected. The earlier native correction run used the normal service with capture stopped and an isolated temporary profile; fixture injection was absent. No push or merge was performed.


## UI and popup-content follow-up — 2026-10-22

This section supersedes earlier validation counts and completion assumptions for
the follow-up batch. Baseline `0554d96`; local implementation commits
`ea849c4`, `7cd1191`, `6363f6a` and `8a7d276`. Human authorized the QA/fix campaign
and local batch commits; no push or merge. Coordinator plus Luna implementation,
popup-content and primary-source workers; this was not Phase B review.

The Region, Dictionary/resources and Update activity disclosures now expand
visibly; a competing zero-row Tailwind utility had overridden the open state.
Invalid region feedback lives in the open Region panel even when Capture
settings is closed. Insets keep actions, validation and footer text inside the
artwork. The capture target dialog has title clearance, forward/reverse Tab
containment and Escape focus restoration, including Safari pointer activation.
Native checks confirmed these behaviors on the rebuilt debug app.

A new Lab `popup-content` command drives real Kiwi/KRDICT through production
popup formatting and checks source-backed lemma/POS, senses, Hanja, level,
Read as roles and constructions. Learner labels improve XSV and reviewed VX
forms. Full dictionary text stays in ignored evidence; tracked gold uses hashes.
Six exact serialized real-provider popup models also pass through React in an
opt-in jsdom integration test with simulated event delivery. This proves neither
native geometry nor text acquisition.

Current gates: portable Python **2,709 passed, 2 skipped, 1 strict known xfail**;
Ruff passed; mypy **368 files**; React **54 passed/1 opt-in skip**; six-model
integration passed; Node **12 passed**; frontend/debug builds passed. Source was
unchanged during final artifact consolidation, so green gates were not repeated.
Real-provider content is **11/12**, with `먹지를 깔고 써요` still misresolved to
먹다 instead of 먹지. No word-specific workaround was added. Existing grammar
coverage matches **698/706 headwords** and **74/76 construction checks**; remaining
rows expose bounded context, ambiguity and OCR/direct punctuation-selection
policy differences. Expectations were preserved. Revisit triggers and evidence
are in the single [follow-up report](../reports/hanly-v2-popup-content-qa.md).

The official frozen-service package built at `f724fef` in the attached
`hanly-v2-packaged-qa` worktree passed inventory, deep/strict signature verification
and native window/React bridge smoke checks. A 180.6s disposable-profile Lab run
reached Ready, compatible KRDICT and three shortcuts, then exited cleanly with
no dropped events or surviving children. Both grants remained missing after
Recheck; Start capture refused and stayed stopped. No installed app was replaced.
The earlier requested 3h15m debug observation ended normally after 77.5 minutes,
with zero captures/OCR/lookups. Its early exit is unexplained; background build
load and dirty source preclude a controlled performance comparison.

Normal grants must be established for the exact app/service identity before
live hover, reader focus, cursor-to-popup retention and captured-text acceptance.
The human must complete OS authentication directly. No broad Python/Terminal
permission, TCC reset, signing-policy change, OCR backend/model tuning or capture
substitution was used. Windows/Linux/DPI and full packaged-provider execution
remain unverified. Four hours of active QA are not established: the blocked
System Settings call, usage-limit gap, heartbeats and automated sampling are not
counted as hands-on testing. User config matches its initial parsed JSON; Lab
apps exited, the pre-existing source app was left untouched, and the continuation
heartbeat remains paused.

Suggested human-selected review targets: disclosure/validation ownership and
modal focus, learner-facing role mappings, source-gold assertions and the exact
popup event model. The report records unresolved language/selection cases for a
future scoped decision. This handoff is the last implementation edit; no deep
review or automatic acceptance is implied.
