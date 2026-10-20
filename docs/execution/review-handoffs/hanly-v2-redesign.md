# Hanly V2 Visual Redesign Review Handoff

## Bundle

- Human-authorized workstream: `design/hanlyV2`; no new Linear issue or lifecycle transition was inferred from completed V1 work.
- Date: 2026-10-19. Phase A implementation is complete; Phase B deep review has not started.
- Original baseline: `43ba8d6`, identical to local `main` and the migration branch's tree. Correction baseline: `15b87a8`.
- GPT implementation with bounded Luna xhigh workers for scene rendering, presentation components and preferences. Commit authorized by the human; no push or merge.

## Implemented

- Six real Control Center sections use the supplied frames, button states, icons, slider, progress artwork and cursor. Normal/Compact navigation and Pixel/Normal popup font persist through the existing validated Python settings bridge.
- Sun/moon use the gallery's 1.5-second entrance/exit and rotation. Each day/night layer blends on an isolated transparent canvas before composition in scene order, preventing night textures from adding into the house/tree beneath them. Original assets and uniform village scaling remain in use.
- Compact mascot poses fit inside the plaque, including the automatic <=760px fallback. The cloud and plaque retain their transparent outer edges with an inset paper fill only where the frame needs one.
- Removed legacy logo/slider backgrounds, rectangular pseudo-element fills, selected-row shadows and obsolete interface styles. Panel rows have side and bottom insets; runtime Permissions is fully inside the frame. Titles, capture icons and disclosure copy are centered. Content scrolls and resets to the top when changing sections.
- `panel-popup-clean-v2` replaces the stained panel slices with nine editable SVG derivatives of the supplied native vector. Content and title fills are uniform; the original pixel outline/bevel is retained, with offset shadow and exterior fringe removed. Original files remain untouched. `tools/design/build_clean_panel.mjs` regenerates the variant; its source hash and slice geometry are recorded beside the assets.
- Preference saves track pending state per setting/command. Appearance choices retain artwork while saving and guard duplicate clicks; unrelated controls and the scene stay mounted.
- The supplied book artwork now includes visible, readable `한` text. The preceding integration replaced the old large glyph with a small decorative raster; accessibility labels alone would not fix OCR legibility. No special-case lookup or fake product result was introduced.
- Popup title is 38px/46px and primary translation 21px/28px (previously 40px/48px and 22px/29px). Details, sequence currency, native measurement and expansion contracts are preserved.
- macOS Control Center uses Tauri's overlay titlebar inside the pixel frame, retaining native close/minimize/fullscreen controls. A dedicated capability permits only this window to start dragging. Windows/Linux retain their native titlebars. Popup window policy is unchanged.

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

Review assignment remains human-selected. The final open instance uses the normal service with capture stopped and an isolated temporary profile; fixture injection is absent. No push or merge was performed.
