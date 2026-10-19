# Hanly V2 Visual Redesign Review Handoff

## Bundle

- Human-authorized workstream: `design/hanlyV2`; no new Linear issue or lifecycle transition was inferred from the completed V1 issues.
- Implementation: GPT, with two configured Luna xhigh workers for persisted preferences, popup presentation and artwork components.
- Date: 2026-10-19. Phase A complete; deep review has not started.
- Baseline: clean branch at `43ba8d6`, identical to local `main` and to the migration branch's tree. Existing branches and OCR research remain separate.

## Implemented

- The six real Control Center tabs use the approved pixel composition, nine-slice panels, original button states, semantic icons, chunky slider, measured progress track and custom pointer.
- Original layered village with uniform cover scaling, visible sun/moon, day/night transition, old idle/computer sprites and current sleeping sprites. Animation pauses when hidden or reduced motion is requested; sprite timers wake for frame changes.
- Normal/Compact navigation, including automatic compact layout at 760 logical pixels; short rails scroll and retain Quit.
- Persisted `popup_font` (`pixel`/`normal`, default `pixel`) and `sidebar_layout` (`normal`/`compact`, default `normal`), using the existing config manager, validated bridge and snapshots. Legacy settings receive defaults. Popup events carry the font preference.
- Classic popup: larger Korean word, readable Hanja fallback, adjacent Korean/English tags, two senses with descriptions and Details for additional meanings and analysis. Native sequence authority, measurement handshake, height limits and font-ready remeasurement remain in use.
- 141 supplied media/font/cursor files retained, about 15 MiB, with original bytes verified against the approved delivery. Unused alternatives remain in the external reference package. No art was regenerated.

## Main expected behavior / seams

All existing settings and actions continue through the current restricted Tauri bridge and Python service. Provider readiness and residency remain distinct. Engine, OCR, capture, updater installation, native focus/presentation policy and signing configuration are unchanged.

UI source was adapted after comparing the reference snapshot with the current implementation. Prototype service/domain copies, DOM decorators, demo iframe, simulator, preview controls and localStorage preferences were not imported. The existing development preview was extended separately and remains excluded from the production entry point.

## Relevant files

- `apps/desktop/src/pages/ControlCenterPage.tsx`, `PopupPage.tsx`, `components/`, and the pixel/popup styles.
- `apps/desktop/public/design/`: selected original artwork and fonts.
- `packages/hanly-app/src/hanly_app/config.py`, `control_center/bridge.py`, `service/protocol.py`, `service/application.py`: cosmetic configuration and popup propagation only.
- `apps/desktop/src/contracts/desktop.ts`, `features/desktopState.ts`: compatible preference fields and validation.
- Relevant config/service/contrast and React tests; `apps/desktop/README.md` documents preferences and preview options.

## Implementation-side validation

| Check | Result |
| --- | --- |
| Full portable suite using `.venv` | 2,691 passed, 2 skipped; skips are opt-in real EasyOCR and the non-macOS Vision path |
| Ruff / mypy | Passed; 365 Python source files checked by mypy |
| TypeScript / Node bridge tests / React tests | Passed; 12 Node tests and 51 React tests |
| Vite production build / debug native build | Passed; final Tauri debug app bundle also built |
| Contrast after final style corrections | 36 tests passed |
| Asset integrity / production entry point | 141 original files match delivery; literal URLs resolve; no prototype/mock/preview-server markers or preview HTML in the production bundle |
| Git whitespace check | Passed |

The first sandbox portable run could not inspect two processes; the complete final portable gate passed with host process access. A test tied to the previous popup's token names was replaced by contrast checks against the actual new palettes. React tests use jsdom and do not render canvas; animation evidence comes from visual inspection.

## Visual and native evidence

The supplied package's prompts and all four guides were read, its integrity check passed (482 file hashes), and its interactive six tabs, states, settings and popup were explored. The integrated views were then checked in the browser, including long/expanded popup content, both typefaces, themes, compact navigation, slider and download progress. A visible browser viewport at 720×560 reported no horizontal document overflow.

On this Mac, the actual Tauri/WebKit Control Center and Python service were inspected across all six tabs. The isolated profile saved Dark, Compact and Normal font; those selections survived quitting and reopening. Three temporary shortcuts were registered, and permission/status displays remained real. No permissions were requested/reset and no update was installed.

An ignored, opt-in Lab fixture injected authored dictionary results into the debug service for native popup presentation checks. The real native popup measured **380×236**, expanded through its actual Details control to **460×366**, and collapsed back to 380×236. The retained anchor stayed at `(616, 246)` and `presented` was true. Close worked; native screenshots show the complete frame. This proves presentation and controls, not native text acquisition or OCR.

Local evidence: `artifacts/lab/runs/20261019-hanly-v2/` (compact summary, provenance, logs, measured rectangles and owned-window screenshots). Recordings were made from dirty source on baseline `43ba8d6`; the final binary hash identifies the final Control Center build. Popup screenshots precede the last Control Center-only label/progress adjustments; popup source was unchanged. No baseline performance comparison is claimed.

The final debug app is left open for review with the normal service, capture stopped and `/tmp/hanly-v2-native/config.json`; fixture injection is absent from that final instance. The installed `/Applications/Hanly.app` and existing packaged release products were not replaced. The previous debug bundle was preserved under the ignored evidence directory. Temporary preview servers were stopped.

## Known limitations / acceptance still required

- Windows and Linux native rendering, CJK fallback metrics, DPI/acquisition and packaged checks require those hosts. macOS evidence does not establish them.
- The official frozen product was not rebuilt or accepted in this workstream; the inspected app is a source-development debug bundle, not a distributable product.
- Real hover acquisition, reader focus under ordinary use, word-to-popup crossing/retention and the historical capture/permission-identity issues remain manual acceptance work. An authored popup and successful debug permission display do not establish installed-app grants or repair the recorded MSS latency.
- No live updater installation, exhaustive blank-frame/focus sampling, performance campaign or deep review was performed. Existing native policies were preserved; no new claim is made about every real application/cursor scenario.
- Floral/Ornamental frames and green comparison remain experimental external references, not new product settings.

## Suggested review targets / assignment

Inspect preference compatibility and propagation, popup font/geometry changes, long Korean/Hanja content, button states and compact layout at platform-specific font metrics. Review assignment remains human-selected. Phase B is not started.
