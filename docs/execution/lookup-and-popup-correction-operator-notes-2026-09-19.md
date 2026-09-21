# Lookup and popup correction — operator notes

What changed in Bundle A, and what you have to do about it. Based on the actual
implemented diff.

## What changed

- Dictionary results now carry KRDICT's short English gloss (`apologize`,
  `drop`, `pretty; beautiful; comely`) above the fuller definition, and senses
  that share a definition but differ in gloss are no longer collapsed into one.
- A conjugated Korean word resolves to its whole lexical unit. `사과했어요` now
  answers `사과하다`, not the fruit `사과`, from any syllable.
- The popup no longer shrinks when expanded or collapsed, and it stays on
  screen after the cursor leaves the word, so it can be read and clicked.
- The popup gained a **Close** control in its footer. Pressing the hover chord
  again also dismisses it.
- A minimized Control Center now reopens instead of staying in the Dock.
- The Control Center's first window is sized from the screen's usable area
  rather than always asking for 1080×760.

## Required operator actions

- **Database rebuild required:** No
- **Existing KRDICT database compatible:** Yes
- **Resource manifest/checksum update required:** No
- **Release asset replacement/upload required:** No
- **Configuration migration required:** No
- **Application/package rebuild required:** Yes — the changes are in application
  and engine code, so a new build is needed to run them.
- **Remaining native/manual verification:**
  - Hover real Korean text and confirm the four reported words answer correctly.
  - Expand, scroll to the last sense, and collapse a long result repeatedly.
  - Move the cursor off the word and confirm the card stays; dismiss it with
    **Close** and with a chord re-press.
  - Minimize the Control Center with the yellow button and Command-M, then
    reopen it from the tray and by clicking the Dock icon.
  - Confirm the smaller Control Center window still shows the sidebar footer and
    page actions.
  - Windows and Linux were not exercised at all.

## Commands

No database rebuild or resource re-upload is required. `translations.lemma` is
already a required column of the shipped KRDICT schema
(`packages/hanly/src/hanly/krdict_schema.py`) and is present in the existing
generated database; only the runtime query and the normalized contracts changed.
The build tooling under `tools/krdict/` and `data/` was not touched.

No configuration migration is required. `ControlCenterOptions.width` and
`.height` now default to `None`, meaning "derive from the screen"; a stored
profile that carries explicit values is still honoured, and no profile on disk
records these.

No operator action is required beyond installing the updated application build.
