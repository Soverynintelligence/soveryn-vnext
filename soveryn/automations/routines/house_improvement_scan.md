# House Improvement Scan

> Autonomy pulse — keep standing improvement + business objectives alive.

## Identity

| Field | Value |
|-------|-------|
| id | `house_improvement_scan` |
| agent | `aetheria` |
| category | `ops` |
| cron | `0 10 * * 1,3,5` |

## When

Mon / Wed / Fri at 10:00 local.

## How

1. `objective_status` for active SOVERYN + CWG work.
2. If SOVERYN has no active, `objective_assign` Kernel a bounded improve. Do **not** mint CWG pricing watch (Jon cancelled that standing brief).
3. No duplicate stacks. Partner tone — not bossy CoS.

## Verify

- At least one relevant `active` objective exists after the tick, or a clear report of existing actives.
- Brief under ~180 words.

## Delivery

- Command Center automations inbox
