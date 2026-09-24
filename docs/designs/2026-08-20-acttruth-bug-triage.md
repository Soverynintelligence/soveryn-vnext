# ActTruth → bug triage → durable fix

**Date:** 2026-08-20  
**Status:** design + thin wire (queue / CC surface); auto-fix not live  
**Parents:** [three-way borrow list](../notes/2026-08-20-hermes-rakazo-soveryn-three-way.md), [skill capture](2026-08-20-citizen-skill-capture.md), [acttruth.md](../acttruth.md), Rakazo Bug Triage energy  

## One-liner

**ActTruth sees the lie. Triage closes the loop. Skills / proposals make it stick.**

## Stages

| Step | Layer | What |
|------|-------|------|
| 1 | ActTruth ledger | Tool outcomes visible (incl. quiet FAIL) |
| 2 | Soft lesson | Same pattern FAIL ×2+ → anti-loop LESSON in-band |
| **3** | **Bug triage** | Classify + propose durable correction type |
| 4 | Durable fix | Skill playbook **or** Scotty/Kernel proposal **or** house note |

Step 2 stops the dumb retry **this turn**.  
Step 3–4 encode the right behavior **next time**.

## Cast (duty pipeline, not a new peer)

| Actor | Job |
|-------|-----|
| ActTruth | Sensor — streak / lesson armed |
| **Vett** | Default triage owner — real vs flaky vs thrash |
| **Scotty** | Code/config correction via commission / worktree |
| **Aetheria / Jon** | Escalate when judgment or Approval Gate needed |
| Skill layer | Persist “how we avoid this” |

Do **not** invent a tenth founding citizen named “Bug Triage.” It is a **duty** on ActTruth signal.

## Correction types

| Type | When | Next action |
|------|------|-------------|
| `skill` | Bad args, repeatable procedure miss | Draft/update citizen skill (skill-capture) |
| `code` | House bug / tool impl / config | Scotty commission or Kernel proposal |
| `ops` | Timeout, unreachable, infra | Medic / Ares / human ops note |
| `ignore` | Flake, one-off, already fixed | Close triage row |
| `ask_jon` | Permission, product judgment | CC held pile / approval |

## Thin wire (shipped with this note)

1. When `maybe_lesson_for_tool_result` returns a lesson (streak hit), house enqueues a **triage candidate** (deduped by `agent::pattern`).
2. Store: `$SOVERYN_DATA_ROOT/acttruth/triage.jsonl`
3. API: `GET /api/system/acttruth/triage`
4. CC Automations fold shows recent triage rows (held pile for bugs)

**Not yet:** auto-running Vett triage turns, auto skill_save, auto Scotty fix.

## Product / tiers

| | Free ActTruth | SOVERYN House |
|--|---------------|---------------|
| Ledger + soft lessons | yes | yes |
| Triage → durable fix | — | **house feature** |

Pitch: *ActTruth shows the lie; the house teaches itself not to repeat it.*

## Later slices

| Slice | Deliverable |
|-------|-------------|
| A | Queue + API + CC (this pass) |
| B | Automation / commission: Vett classifies open triage rows on a cron or on demand |
| C | `skill` path → skill-capture draft |
| D | `code` path → Scotty commission template |
| E | Promote closed triage → earned-keep / Lattice when material |

## Non-goals

- Auto-merge production code without gates
- Soft lesson becoming hard ban in the same PR
- Triage bot as a separate identity product
- Spamming a new row on every FAIL (only on lesson / streak crossing, with cooldown dedupe)
