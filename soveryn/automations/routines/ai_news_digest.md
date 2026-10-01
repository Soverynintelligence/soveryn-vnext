# AI News Digest

> Rakazo-style routine doc: readable, editable, commit-able.
> Override locally: `$SOVERYN_DATA_ROOT/automations/routines/ai_news_digest.md`

## Identity

| Field | Value |
|-------|-------|
| id | `ai_news_digest` |
| agent | `eve` |
| category | `news` |
| cron | `0 8 * * *` |

## When

Daily at 08:00 — after morning brief, before planner.

## How

1. Cover last 24h: models, papers, labs, funding/product moves.
2. One sentence why-it-matters-to-us per item.
3. Rank by signal-to-noise; max 8; drop pure hype.

## Verify

- ≤ 8 items; each has a house-specific 'why it matters'.
- No pure hype entries.
- Lands in CC inbox.

## Prompt (source of truth in catalog)

```
Produce the AI news digest. Cover the last 24 hours: model releases and benchmarks, notable papers, lab announcements, and funding or product moves in applied AI. For each item give one sentence on why it matters to us specifically. Rank by signal-to-noise, max 8 items, drop anything that is pure hype.
```

## Delivery

- Default surface: **Command Center inbox** (`command_center`)
- Signal: preview-only until `signal_live_armed`
- Approval Gate: read tools auto-approved for `source=automation`; writes stay gated
