# House calendar — one clock for every citizen

The shared source for "what is coming." Humans, Kernel, Eve, Aetheria all
read this file. Keep entries one line. Format for dated items:

    - YYYY-MM-DD — event — detail

Recurring items go under their own heading. When a dated item completes,
move it to Done at the bottom (do not delete — the history is cheap).

## Recurring

- Monday 08:30 — Ledger reconcile — `soveryn-ledger-reconcile.timer`; drift
  report at `docs/ops/tax/RECONCILE-LATEST.md`, webpush on drift
- Weekdays 07:00-17:00 — Automations tick — `soveryn-automations.service`
  (briefs, watches, crons via vNext)
- Nightly ~03:00 — Lattice librarian backfill — `soveryn-night-librarian.timer`
- Every 15 s — Scotty worker desk presence + commission drain (poll 60 s
  since 2026-09-18)
- CRM restarts — after any `pondwright-cwg-ops` deploy on the Spark
  (`systemctl --user restart pondwright-crm.service` on spark)

## Dated

- 2026-09-21 — First weekly ledger reconcile run — expect first report Monday morning
- 2026-09-21 — Backup camera arrives (Amazon 111-9440800-7041010) — CWG van install
- 2026-09-30 — OpenAI ChatGPT Plus Sep billing expected — book when billed (SOVERYN ledger)
- 2027-03-11 — BAP insurance policy 0630199 expires — renewal due before this date

## Done

- 2026-09-22 — Vett patrol parked; sources + standard inherited by Eve as `funding_watch` (daily 08:00)
- 2026-09-22 — Scotty worker fully parked (folded citizen; returns with delegation engine)
- 2026-09-22 — Estate audit: truth file corrected (brains backwards), 4 undocumented services added, repo census added, /lead rate-limited, representation 7,921-restart loop parked

- 2026-09-19 — Journal post 1 live: How to Clear a Green Pond Naturally (carolinawatergardens.com) — first content-engine post
- 2026-09-19 — Field Notes index at /journal, month grouping, hover dropdown nav — site-wide

- 2026-09-18 — Invoices live in CRM + estimator (b5ad209, 3eb8e28)
- 2026-09-18 — Ledger reconcile system built; books clean (0e444bc)
- 2026-09-18 — Email grants scoped to eve + kernel (333b03f)
