# Morning Brief

> Rakazo-style routine doc: readable, editable, commit-able.
> Override locally: `$SOVERYN_DATA_ROOT/automations/routines/morning_brief.md`

## Identity

| Field | Value |
|-------|-------|
| id | `morning_brief` |
| agent | `aetheria` |
| category | `news` |
| cron | `30 7 * * *` |

## When

Weekdays/weekends at 07:30 local — first signal of the day.

## How

1. Pull overnight macro + AI/ML + house-product surface signals (web_search/fetch as needed).
2. Rank by decision relevance to Jon / the house.
3. Lead with the single most material item; cap ~200 words.
4. If nothing material, say so in one line — do not pad.

## Verify

- Opens with the decision-relevant lead (or an explicit 'nothing material').
- ≤ ~200 words; no hedging filler.
- Lands in CC inbox; Signal not sent unless armed.

## Prompt (source of truth in catalog)

```
Compose the morning brief for Jon. Summarize the top 5 stories worth his attention today: overnight macro moves, AI/ML releases, and anything touching the house's product surface. Lead with the single most decision-relevant item. Keep it under 200 words, no filler, no hedging. If nothing is material, say so in one line.
```

## Delivery

- Default surface: **Command Center inbox** (`command_center`)
- Signal: preview-only until `signal_live_armed`
- Approval Gate: read tools auto-approved for `source=automation`; writes stay gated
