# Control Center Redesign Review Handoff

## Bundle

- Member issues: none — human-directed redesign against an approved Claude Design prototype
- Implementation ecosystem: Claude Code (Opus 5), Windows 10, Python 3.13 venv
- Date: 2026-09-17

## Implemented

- Replaced the vertically stacked dashboard with the approved sidebar/page shell:
  Capture, Permissions (conditional), Shortcuts, Appearance, Updates, Logs.
- One token set with a `[data-mode]` dark variant, the approved rose accent, the
  quiet neutral scrollbar, and the prototype's motion language.
- Capture page over the real lifecycle: Reading target, the collapsing Region
  card, manual coordinates, Select area, hover-delay slider with an editable
  millisecond field, monitor target, and lookup preload.
- Shortcuts page that keeps stored intent and registered reality separate, with
  a keyboard recorder that Python still validates and registers.
- Appearance page surfacing the existing `Theme` preference, which had no
  control at all before; `system` resolves through `matchMedia` and follows the
  desktop without rewriting the stored value.
- Updates page as five states over the real `UpdateCoordinator` snapshot, with
  the Thinking States stage label, the resources disclosure, and the activity tail.
- Logs page combining derived readiness with the existing diagnostics bridge.
- Two narrow snapshot additions: `runtime.hover_delay_bounds` and
  `runtime.app_version`.

## Main expected behavior

Every visible value comes from `ControlCenterBridge`. The page stays usable
while the bridge is absent, while the runtime prepares, and after the bridge
dies. Permissions exist only where `permissions.supported` is true. The primary
application update is still in-app; release notes remain the one secondary
browser action. No prototype demo data survives.

## Architecture / seams touched

- `ControlCenterBridge.get_state()` gained two normalized fields. No new bridge
  method; `CONTROL_CENTER_OPERATIONS` is unchanged, so the page can still call
  exactly the twenty-one allowlisted operations.
- `hanly-app → hanly` unchanged. Nothing was added to the engine package.
- `control_center_document()` still inlines both assets into one document.
- `qt_popup.py` and the popup path were not touched.

## Relevant files / diff areas

```
packages/hanly-app/src/hanly_app/assets/control_center/{index.html,control_center.css,control_center.js}
packages/hanly-app/src/hanly_app/control_center.py          two snapshot fields, _installed_version
packages/hanly-app/src/hanly_app/control_center_host.py     background_color follows the new palette
tests/test_control_center.py                                markup assertions retargeted; two new tests
tests/test_control_center_refresh.py                        fixture fields and new report keys
tests/hanly_fixtures/assets/control_center_harness.js       stub DOM widened; data-* now reflects into dataset
tests/native/shared/test_control_center_layout.py           new control ids; opens Region before measuring
.design-reference/Hanly Prototype.dc.html                   the collapse bug fixed at source
```

## Implementation-side validation already run

- `python -m pytest` → 1505 passed, 110 skipped, 2 failed. Both failures are
  pre-existing and reproduce on a clean stash: a stale editable install
  (`hanly-app` metadata 0.5.2 vs pyproject 0.5.3) and a stale frozen bundle in
  `dist/`.
- `python -m ruff check packages packaging tests tools benchmarks` → clean.
- `python -m mypy ...` → 20 errors, all pre-existing POSIX-only attributes
  (`fcntl.flock`, `os.getxattr`, `os.statvfs`) reported because this run is on
  Windows. Verified identical on a clean stash.
- `tests/native/shared/test_control_center_layout.py --suite native` → passed.
  Real window, real QtWebEngine, widths 400/640/760/780/900/1039/1040/1080, with
  Region expanded: no horizontal scrolling and every measured control inside the
  viewport at every width.
- Region collapse measured in the real window, both directions:
  wrapper height 0 → 202.25 → 0, `scrollWidth == clientWidth` throughout.
- Rendered the real document against a real `ControlCenterBridge()` snapshot in
  QtWebEngine and inspected Capture, Shortcuts, Appearance, Updates and Logs in
  both themes.

### The reported Reading-target line

Root cause, not masked: `regionInnerStyle` put `padding-top:16px` on the element
that is also the `grid-template-rows: 0fr` item. A `0fr` track zeroes an item's
*content* box only, so the collapsed wrapper stayed 16px tall and clipped a
card whose `box-shadow` blurs 12px upward against a 4px down-offset — the
surviving hairline. Measured before the fix: 16px. After: 0px.

A second, independent defect fed the same area: `row(active, last)` was called
with `last = (s.target !== 'region')`, so the final row of the Reading target
card grew a `border-bottom` that drew a straight rule across the card's rounded
bottom edge. The last row now never carries one.

Both are fixed in `.design-reference/Hanly Prototype.dc.html` and carried into
production as the `.collapse` / `.collapse-inner` / `.collapse-gap` rule, where
the gap lives inside the clip and a closed section contributes zero geometry.

## Known limitations / intentionally unvalidated areas

- **No manual pywebview session was run.** Everything visual was verified by
  driving the real document in QtWebEngine and by the native layout test. The
  window was never opened the way a user opens it (`hanly`), because this
  checkout cannot reach a provisioned `krdict`.
- **Permissions was never seen on screen.** This is Windows, so
  `permissions.supported` is false here. The conditional nav item, the row
  rendering, the grant action and the post-grant watching are covered by the
  Node harness against macOS-shaped snapshots, but no real macOS run happened.
- **The updater was never exercised against a live release channel.** The five
  panel states were reviewed against constructed snapshots and the coordinator's
  own status vocabulary, not against a real download.
- **Reduced motion was not visually confirmed.** The `prefers-reduced-motion`
  block is present and matches the prototype; no run with the setting enabled.
- The shortcut recorder maps browser key names to Hanly's spelling for a common
  subset (`KEY_NAMES`, `MODIFIER_KEYS`). An exotic key reaches Python as
  whatever `event.key` lowercases to and is rejected there rather than in the
  page. That is deliberate — Python stays the validator — but the rejection
  message will be the canonicalizer's.

## Decisions worth a second opinion

- **Monitor target moved to Capture settings.** The prototype puts the monitor
  `<select>` inside the Region card only, but `capture_monitor` is independent
  of `capture_mode` and matters in full-monitor mode too. Following the
  prototype exactly would have made the monitor unreachable whenever Current
  monitor was selected. It now sits in the "Capture settings — applies to both
  targets" card, which is that card's stated purpose.
- **Push to Hover wording rejected.** The prototype labels the two activation
  modes "Active" and "Deactivated", which inverts what `always_active` means.
  The rows now read "Only while held" and "Whenever capture is running".
- **Prototype-only sections dropped**, per the brief: the fake window chrome,
  the platform preview switcher, the interface-font picker, "Simulate failure",
  the in-page area picker overlay, the fake session metrics, and the invented
  `easyocr_ko` / `tokenizer` resources.
- **`update_checks_enabled` was left unexposed.** It is a real persisted
  preference that the old UI never surfaced and the prototype does not show, so
  nothing was lost by omitting it. Worth a decision if it should now appear.
- **`color-scheme` was added** to `:root` and `[data-mode="dark"]`. I briefly
  mis-diagnosed this as fixing a force-dark bug; it does not — Chromium was not
  inverting anything here. It is kept because it is what makes the native
  `select`, range and scrollbar render in the matching scheme.

## Suggested review targets

- `renderState` runs every renderer on every snapshot, and the refresh timer
  polls at 500ms while anything is pending. Worth checking that rebuilding the
  shortcut, permission, resource and log lists on each tick is not visibly
  expensive on a slower machine.
- `regionDirty` and `delayEditing` are the two guards that stop a poll from
  clobbering half-typed input. Worth checking they cover every path that
  re-renders, including the `focus` listener.
- The `data-*` reflection added to the harness stub is new; confirm it does not
  make a test pass for a reason a real DOM would not.
- `_installed_version()` swallows every exception. Confirm that is the wanted
  breadth, given `installed_version()` only documents `PackageNotFoundError`.
- Whether `.design-reference/` belongs in the repository at all.

## Review assignment

Human-selected after implementation. Not started.
