# Weekly Review

> Rakazo-style routine doc: readable, editable, commit-able.
> Override locally: `$SOVERYN_DATA_ROOT/automations/routines/weekly_review.md`

## Identity

| Field | Value |
|-------|-------|
| id | `weekly_review` |
| agent | `aetheria` |
| category | `productivity` |
| cron | `0 16 * * 5` |

## When

Fridays at 16:00 — close the week.

## How

1. Recap shipped vs slipped.
2. Surface 2–3 highest-leverage wins.
3. Name the bottleneck/risk for next week.
4. Propose top 3 Monday priorities. Keep scannable.

## Verify

- Wins + bottleneck + Monday top-3 present.
- Scannable (not a novel).
- Lands in CC inbox.

## Prompt (source of truth in catalog)

```
Run the Friday weekly review. Recap what shipped and what slipped this week, surface the 2-3 highest-leverage wins, name the bottleneck or risk that should get attention next week, and propose the top 3 priorities for Monday. Keep it scannable.
```

## Delivery

- Default surface: **Command Center inbox** (`command_center`)
- Signal: preview-only until `signal_live_armed`
- Approval Gate: read tools auto-approved for `source=automation`; writes stay gated
