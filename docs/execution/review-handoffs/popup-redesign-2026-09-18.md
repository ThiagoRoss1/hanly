# Popup Redesign Review Handoff

## Bundle

- Member issues: none — human-directed implementation of the approved popup prototype
- Implementation ecosystem: Codex, Windows, Python 3.13 venv, native PyQt6
- Date: 2026-09-18

## Implemented

- Replaced the fixed one-line popup with the approved native compact/expanded dictionary card.
- Added light, dark, and live system-theme palettes, the rose accent, restrained fade-in motion,
  natural content sizing, bounded scrolling, and edge-aware repositioning.
- Made success, empty, not-found, unusable, and processing-error outcomes visible in the same
  non-activating popup lifecycle.
- Retained normalized morphology and the exact selected OCR evidence through the engine pipeline.
- Surfaced real KRDICT source, vocabulary level, and Hanja derived conservatively from `origin`.
- Added persisted default-density and technical-detail preferences to the Control Center and
  applied appearance/detail changes to a running popup.
- Kept hover retention synchronized when a visible popup expands, collapses, or reveals entries.

## Main expected behavior

A successful lookup opens as a meaning-first learner card: lemma and real Hanja, part of speech,
KRDICT level when available, ordered senses, then the surface-to-lemma explanation and normalized
morphology. Compact opens at 340 px and expanded at 386 px; either measures its content, stays in
the current screen's available geometry, and uses one internal vertical scroll area only when the
screen is shorter than the content. Alternate entries, density, theme, and optional technical
evidence are backed by real normalized state. Normal non-success and error outcomes remain visible
without exposing raw provider exceptions by default.

## Architecture / seams touched

- `LookupContext` now carries `selected_ocr` and normalized `analyses`; `LookupPipeline` populates
  both without exposing EasyOCR or Kiwi objects.
- `DictionaryEntry` now carries optional `source`, `hanja`, and `vocabulary_level`; the KRDICT
  adapter remains the only component that knows the SQLite schema and mixed `origin` field.
- `PopupController` still owns lifecycle and pure placement; `QtPopupView` owns native measurement,
  density, theme, rendering, and interaction.
- `ManualLookupRuntime` applies popup preferences live and updates `RetainedTarget.popup` after
  interactive resizing. Request-currency behavior and the final presentation gate are unchanged.
- Control Center uses the existing `update_settings` bridge and `AppConfig` persistence path; no
  new bridge operation or entry point was introduced.

## Relevant files / diff areas

```text
packages/hanly/src/hanly/{contracts.py,lookup_pipeline.py,krdict_provider.py}
packages/hanly-app/src/hanly_app/{config.py,popup.py,qt_popup.py,manual_lookup.py}
packages/hanly-app/src/hanly_app/{control_center.py,assets/control_center/}
tests/test_{core_contracts,lookup_pipeline,krdict_provider,kiwi_provider,popup}.py
tests/test_{app_config,control_center,hover_target,engine_e2e}.py
tests/krdict/{test_pipeline.py,test_runtime_schema.py}
tests/native/shared/test_qt_popup_window.py
```

## Implementation-side validation already run

- Focused popup/engine/config/native set → 232 passed, 1 optional OCR fixture skipped.
- Broad non-native set with four unrelated host/artifact checks deselected → 1473 passed,
  82 skipped, 4 deselected.
- Native set excluding the two legacy Control Center WebView probes → 37 passed, 27 skipped,
  2 unrelated host failures (CIM process inspection denied; QtWebEngine DirectComposition unsupported).
- `python -m ruff check packages packaging tests tools benchmarks` → clean.
- Full mypy command → 20 Windows/POSIX-stub errors in six pre-existing updater/inventory files.
  The same command excluding only those six files → clean across 238 files.
- Native dark popup rendered from real `QtPopupView` and visually inspected: hierarchy, Hanja,
  metadata, senses, analysis, footer, palette, and bounds were intact without clipping.
- `git diff --check` → clean apart from Git's expected LF-to-CRLF notices.

## Known limitations / intentionally unvalidated areas

- A complete `python -m pytest` run is not green on this host. The independent failures are a
  stale/broken frozen bundle (`torch` DLL and WebView startup), denied Windows CIM inspection, a
  timeout-child file handle that remains locked, stale editable metadata (0.5.2 vs 0.5.3), and
  QtWebEngine/DirectComposition failures. The slow Control Center lifecycle probe was interrupted;
  its layout probe separately returned no JavaScript result. None is in the popup code path.
- The full desktop was not manually launched because the same QtWebEngine host failure prevents a
  reliable Control Center startup. The native popup itself was rendered and inspected directly.
- macOS no-activation behavior was not exercised on macOS; the existing window flags, attributes,
  and Cocoa visibility hook are preserved and covered by platform-independent contract tests.
- Korean examples and semantic categories are not shown. The current normalized dictionary
  contract has no reliable learner-facing bilingual shape for them, so the redesign does not infer
  or invent those fields.
- Expansion/collapse is immediate; only presentation fades in. This deliberately avoids motion that
  could disturb pointer retention until native resize animation has cross-platform evidence.
- Mixed-DPI behavior is covered through Qt screen geometry and negative-origin placement tests, not
  by a physical multi-DPI monitor session.
- `.design-reference/popup/` remains untracked and was not modified or added to the implementation.

## Suggested review targets

- Verify the new normalized contract fields remain adequate for future clients without becoming
  desktop-shaped, especially `selected_ocr` identity and the optional KRDICT metadata.
- Inspect the conservative CJK filtering of KRDICT `origin` values containing mixed scripts.
- Exercise expand/collapse and alternate entries near every edge on mixed-DPI Windows and macOS,
  confirming the retained hover union follows the final frame.
- Confirm keyboard/mouse interaction never activates the host application on macOS and Windows.
- Check compact/expanded information density against the prototype with long definitions, many
  senses, and tall technical output.

## Review assignment

Human-selected after implementation. Not started.
