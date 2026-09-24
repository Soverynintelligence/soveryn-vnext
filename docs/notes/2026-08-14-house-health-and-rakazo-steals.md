# House health + Rakazo steals (2026-08-14)

What we take from [Rakazo](https://github.com/elie222/rakazo) (Grok Bot–style product)
without adopting their stack or identity model.

## 1. House health JSON — **shipped**

`GET /api/citizens/health`

Named runtime path (their idea) with Soveryn evidence rules:

| Field | Meaning |
|--------|---------|
| `runtime` | `soveryn_vnext`, version, agent_loops, wakeup, sandbox=`desk_workspace` |
| `residents` | Roster statuses from last census (not self-declared green) |
| `workers` | Process units from `census.CITIZENS` + optional `systemctl is-active` |
| `commissions` | Queue counts (queued / running / done / failed) |
| `connectors` | Existing grant + armed map |
| `desks` | inbox/outbox/work/notes present? |
| `spawned` | Ephemeral specialists (subagents) under Aetheria |
| `vocabulary` | peer vs subagent vs commission |

Query: `?probe=0` skips systemctl (tests / fast path).

**Not** a drop-in for `GET /health` (process liveness). Health = app up.
House health = polity coherent.

### Example

```bash
curl -s http://127.0.0.1:8080/api/citizens/health | jq '{ok, problems, runtime, residents:.residents.counts, workers}'
```

## 2. Peer vs subagent — **vocabulary locked**

| Kind | Standing | Desk | Survives turn? | Counted resident? |
|------|----------|------|----------------|-------------------|
| **peer** | founding citizen | yes | yes | only if observed |
| **subagent** | ephemeral specialist | no | no | never |
| **commission** | work item for a peer | result → outbox | until done/failed | n/a |

No third half-kind. COS commissions peers; Aetheria may spawn subagents
for one job. Documented in `house_health.VOCABULARY` and returned on health.

## 3. Scotty desk as “computer” — **sketch, not Docker**

Rakazo: each bot has a full GUI Linux desktop.

Soveryn: Scotty already has a **desk** (`~/soveryn_citizens/scotty/{inbox,outbox,work,notes}`)
and `soveryn-scotty-worker` drains commissions. That *is* the sandbox metaphor
without E2B.

### Next increments (when wanted)

1. **Desk status on Citizens board** — green drawers when dirs exist (health already reports `desks.scotty`).
2. **Take-control for browser logins** — only if a connector needs interactive OAuth; human signs in, session file stays under desk/work. Not every citizen.
3. **Optional Docker jail for `code` connector** — only Scotty’s `run_command` / pytest, not the whole house.

Do **not** give every citizen a GUI computer.

## 4. Explicit non-goals

- Rewriting Soveryn in TypeScript / Pi / Composio core
- “Create a bot” as identity (we keep the cast + census)
- Cloud control plane

## 5. UI

Citizens board can load `/api/citizens/health` for a one-line mast status
(`ok` + problems). Optional; API is the contract.
