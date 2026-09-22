# Funding & Research Watch

> Rakazo-style routine doc: readable, editable, commit-able.
> Override locally: `$SOVERYN_DATA_ROOT/automations/routines/funding_watch.md`

## Identity

| Field | Value |
|-------|-------|
| id | `funding_watch` |
| agent | `eve` |
| category | `ops` |
| cron | `0 8 * * *` |

## When

Daily at 08:00 ET. Inherited from V.E.T.T. (folded 2026-09-22); his sources
and verification standard are binding on this seat.

## How

1. Check the 7 sources listed in
   `data/memory/skills/eve/funding-watch.md` — UK/EU/US AI funding pages,
   NSF, SBIR topics, arxiv cs.AI/recent, Hugging Face blog — using web
   tools. Cadence: arxiv twice daily if time allows, everything else daily.
2. Apply the keywords in the skill note (sovereign AI, compute access,
   SBIR phase I, mixture of experts, ...).
3. Report only what is NEW since the last tick, each with a source URL.
4. For each finding: what, who funds it, deadline, and why it matters to
   SOVERYN (local AI house, applied agents, grants history in docs/ops).
5. Actionable grant → flag for Jon with deadline + first step, and add it
   to `docs/ops/HOUSE-CALENDAR.md` dated items.
6. Nothing new → exactly one line: "Funding watch: nothing new."

## Rules

- **Verify or say nothing.** Vett's standard is binding: every claim has a
  source URL or publication name. No source = no report.
- Never invent a deadline or amount. If the page does not state it, say so.
- Keep it under 150 words unless there is a genuinely actionable find.

## Verify

- The routine fires daily and mentions at least the sources checked or
  "nothing new".
- Every finding includes a URL that resolves (or a publication name).
- Actionable findings appear as dated items in the house calendar.
- The watch never recommends applying for something without a deadline
  and a first step.
