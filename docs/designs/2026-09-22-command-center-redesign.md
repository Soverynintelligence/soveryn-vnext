# Command Center redesign — brief (2026-09-22)

**Status:** proposal for the mission-control effort already in flight
(`feat/mission-control-spark-tile` — public gate, messenger, mobile API,
edge). This document is the user-experience contract to build against.

## The problem, observed today

The Command Center accreted. It is now a long page of `<details>` folds,
several marked `cc-advanced`, which easy mode hides entirely
(`body.cc-easy .cc-advanced { display:none }`). Consequences, all observed:

- The **morning brief — the product's daily output — rendered into a fold
  that easy mode deleted from the DOM.** Jon had never seen one, ever.
- The automations inbox, triage, and catalog sit three layers deep.
- Nothing on the page tells you what is hidden. Hidden-from-the-user and
  hidden-by-CSS are indistinguishable.
- Fold count: 8+ top-level folds, most `cc-advanced`, most never opened.

## Target shape (v1 — mission control)

Order is the design. Top of page = what Jon needs in the first minute.

1. **Today** — the morning brief, verbatim, at the top. Funding watch,
   news digest, crash watch: the daily run's output IS the page header.
   Unread badge on the tab when a new brief lands.
2. **Needs you** — Gate approvals, failed units, sweep/reconcile findings,
   overdue calendar items. Empty state: "nothing needs you." This section
   being empty is a *feature*; make the emptiness visible.
3. **Citizens** — live state per seat (Aetheria / Kernel / Eve): last
   action, current commission, health. One row each, expandable.
4. **Estate** — services and timers from the truth file, rendered live
   (probe, don't paste). Green/red dots. Link each to its DEPLOY.md.
5. **Everything else** — the legacy folds (deep config, memory, pulse,
   chapters), collapsed under an explicit "Advanced" toggle. Hidden
   behind a *labeled* drawer, not CSS deletion.

## Rules

- Nothing renders into a container that easy mode deletes. If it exists,
  it is reachable. "Advanced" means collapsed behind a labeled toggle,
  never `display:none` on content someone asked for.
- The morning run writes the page. 04:00 backup → 08:00 briefs → the page
  shows what happened at each step, with timestamps.
- Every red dot links to its fix (runbook line, restart command, or the
  responsible seat).
- One column, no nested drawers inside drawers, no fold inside fold.

## Migration

- Tonight's stopgap already shipped: the automations fold is promoted
  (visible chapter, expanded) — briefs are findable as of now.
- The mission-control work (gate/messenger/mobile/edge) should land its
  data plumbing first; this document defines the view on top of it.
- Kill `body.cc-easy .cc-advanced { display:none }` only after every
  currently-hidden fold has been re-homed under the labeled Advanced
  drawer — otherwise the legacy folds spam the page.

## Success test

Jon opens the Command Center cold. Within ten seconds he knows: what the
house did this morning, whether anything needs him, and that nothing is
broken. If he has to search a fold for the morning brief again, the
redesign failed.
