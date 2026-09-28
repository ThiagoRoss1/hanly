# Vision hover and macOS restore — operator notes

What changed, and what you must do about it before a release.

## What changed

- **Apple Vision is the recognizer on macOS.** `auto` (the default) picks it
  where the platform provides it and falls back to EasyOCR elsewhere. A new
  **Text recognizer** setting can pin either one.
- **The recognizer choice now reaches the lookup child.** It previously stopped
  at the shell, so every lookup still ran EasyOCR while the interface reported
  Vision.
- **Hover keeps one capture while the pointer stays on a word.** A cursor-centred
  crop changed which lines it contained for a few pixels of movement, which is
  what made the popup alternate between an answer, an unrelated word and
  "Too unclear".
- **Vision text geometry is preserved**, so rotated text keeps its real shape
  instead of an axis-aligned approximation.
- **One bounded recapture** when the text an answer came from touches the crop
  edge. Never for a fully visible misreading.
- **The Control Center restores.** It called `restore()` only when pywebview
  reported the window minimized, and pywebview never reports that. Clicking
  Hanly in the Dock now reopens a live window.

## Operator actions

| Question | Answer |
|---|---|
| Database rebuild required | **No** |
| KRDICT schema changed | **No** |
| KRDICT data changed | **No** |
| Existing generated database compatible | **Yes** |
| Resource manifest or checksum update | **Not required** |
| Model or weight download changes | **None** — Vision ships with macOS |
| Release asset replacement | **Not required** |
| Configuration migration | **None** — a profile without `ocr_backend` reads as `auto` |
| Application rebuild | **Yes** — engine and desktop code changed |
| New runtime dependency | **None** — `pyobjc` was already installed; `Vision.framework` is loaded by path |

## macOS specifics

- Vision needs **macOS 13 or later** for Korean; this machine reports Korean
  available only at the `accurate` recognition level, which is what Hanly uses.
- Running from source is a **different binary** from `/Applications/Hanly.app`,
  so Screen Recording and Accessibility must be granted to it separately.
- Nothing leaves the machine. Vision is on-device; there is no network call, API
  key or account.

## Commands

No database rebuild, no resource re-upload, no migration. `translations.lemma`
was already a required column of the shipped KRDICT schema, and neither
`tools/krdict/` nor `data/` was touched.

## Known limitations

- **No real Dock cycle has been performed.** The restore ordering, the liveness
  gate and the debounce are covered by tests; that macOS actually delivers the
  activation on a Dock click for an accessory-child layout is not verified.
- **No live hover has been performed.** Every measurement here comes from
  rendered text, not a real screen capture.
- Windows and Linux were not exercised; they keep EasyOCR and its known
  weakness on Korean verb endings.
- The `친구들이` failure seen in the recording is still unexplained: intact text
  resolves correctly and no fixture reproduces it.
- 24 native tests error because an unaccepted Xcode 27.0 licence blocks `cc`.
  They are unrelated to this work and also blocked git, so **nothing is
  committed**.
