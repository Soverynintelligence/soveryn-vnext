# Competitor Watch

> Rakazo-style routine doc: readable, editable, commit-able.
> Override locally: `$SOVERYN_DATA_ROOT/automations/routines/competitor_watch.md`

## Identity

| Field | Value |
|-------|-------|
| id | `competitor_watch` |
| agent | `eve` |
| category | `news` |
| cron | `0 9 * * 1` |

## When

Mondays at 09:00 — weekly competitive scan.

## How

1. Review tracked competitors for the week (shipping, pricing, hiring, positioning, sentiment).
2. Per competitor: what changed + roadmap implication.
3. End with one 'watch closely' pick and why.

## Verify

- Every tracked competitor touched or explicitly unchanged.
- One clear 'watch closely' pick.
- Lands in CC inbox.

## Prompt (source of truth in catalog)

```
Weekly competitor watch. Review the tracked competitor set for the week: shipping notes, pricing changes, hiring signals, public positioning shifts, and community sentiment. For each competitor, state what changed and what it implies for our roadmap. End with a single 'watch closely' pick and why.
```

## Delivery

- Default surface: **Command Center inbox** (`command_center`)
- Signal: preview-only until `signal_live_armed`
- Approval Gate: read tools auto-approved for `source=automation`; writes stay gated
