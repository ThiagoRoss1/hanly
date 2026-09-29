# V1 cleanup audit — intent for future sessions

**Status:** User direction recorded on 2026-09-28. This is a context brief,
not an approved execution plan or authorization to edit product code.

## Goal and boundary

Before V1, run a repository-wide **read-only** audit focused on organization,
file/folder placement, maintainability, documentation, dead or redundant code,
oversized comments, and reproducible bugs found along the way. A successful
audit produces **one comprehensive findings report**. A later final reviewer
will independently validate and prioritize the findings, then design the
actual cleanup: proposed folders, moves, removals, formatting, simplification,
tests and commit boundaries. Audit agents do not implement fixes.

Use **21 lightweight reading subagents**, in scoped rounds rather than
overlapping edits: seven focused on organization/documentation, seven on code
cleanup, and seven on QA. Assign tracked text files explicitly, cover code,
tests, scripts, workflows, configuration and Markdown, and record coverage and
exceptions. Each finding should identify file/line, evidence, impact, proposed
action, risk and validation needed. Consolidate duplicates and distinguish
verified defects from suspicions. Binary/generated artifacts require inventory
and reference checks rather than line reading. The goal of the Luna readers is
the best possible evidence package for the user and final reviewer, not a
patch or an unverified quota of findings.

Read-only means no repository edits, not a ban on validation. Agents may run
tests and, where justified by a finding, exercise Hanly on the Mac. Only one
team at a time may control the Mac for live testing; coordinate ownership and
never interrupt the user's active work. Hanly, Safari and GPT are permitted
test surfaces, as are previously used note-taking/test apps when relevant.
Use controlled test text, not private user content. Do not persist real screen
pixels, recognized text, provider crops or private artifacts in the report or
repository. A memory-only freeze stays in memory; do not invoke explicit
private export without separate user authorization. Record sanitized outcomes,
reproduction steps and measurements instead. Do not install software, change
system permissions or settings, or access unrelated applications as part of
the audit.

## Scope priorities

- Make repository layout and Markdown easier to navigate and present. Review
  the root README against the current product, but defer the final rewrite of
  README, CLAUDE.md and AGENTS.md to the later cleanup planning/execution.
  Those agent files should ultimately be short rules/routing guides; detailed
  architecture belongs in authoritative architecture documents and suitable
  folder READMEs.
- Identify dead code only with evidence that accounts for dynamic imports,
  platform-specific paths, entry points, packaging and tests. Do not remove
  files merely because they look historical or unused.
- Record important reproducible bugs, but do not let open-ended bug fixing
  prevent the cleanup or V1. In particular, missing KRDICT words/slang are
  not automatically OCR or implementation defects.
- Preserve approved engine/app boundaries, privacy guarantees, release and
  updater behavior, and architecture/visual invariant synchronization.
  Architectural changes require separate human approval.

## Explicitly later, not part of this audit

More extensive Windows false-alarm investigation and super-benchmarks,
dictionary coverage architecture, further functional improvements, and
product-design changes belong on the road from V1 to V2. The V2 direction is
a distinctive pixel-art design and a measured Tauri-first desktop prototype;
Electron is a fallback if Tauri proves unsuitable. Neither migration nor a
new design system is to be implemented as V1 cleanup.

## Handoff expected from the audit

One large, structured report: coverage ledger; verified findings with
evidence; proposed current/reference/historical documentation classification;
candidate folder organization; safe cleanup versus decisions requiring the
user's approval; deferred V2/product work; and a suggested order for the
subsequent reviewer to examine and plan changes. No audit finding is an
automatic instruction to modify the repository.

The final reviewer is a **separate, stronger agent** (GPT Astra or Sol), with
Claude Opus 5.5 available for targeted independent investigation or challenge
of uncertain findings. They should check important claims against the source,
investigate doubts and possible improvements, reject false positives, and
propose the actual cleanup plan. The user approves that plan before any
implementation. Do not make all 21 Luna readers duplicate this final review.
