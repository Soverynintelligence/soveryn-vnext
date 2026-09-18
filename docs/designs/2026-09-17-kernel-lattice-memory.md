# Kernel lattice memory — design

**Date:** 2026-09-17  
**Status:** v1 landed (flag default **off**). Overlay + CLI + Messages gate. No prod `opencode.json` / Pi settings edit. No soul write. No `:8001` change.  
**Parents:** Grok Build memory (shape only), JIT overlay (`~/ablit-bake/jit-exp/`), Lattice teach loop (`soveryn/platform/lattice/teach.py`)

## Goal

House Kernel (Messages seat **and** Pi/OpenCode → GLM `:8001`) remembers yesterday’s decisions, conventions, and failed approaches **as house Lattice facts**, the same graph Aetheria and Eve already use.

Day-2 test: a new session answers “what did we decide yesterday about X?” from the lattice, without re-explaining.

## Non-goals

- No `:8001` restart.
- No DeepSeek harness / dsh install.
- No ABLIT.
- No production `opencode.json` / Pi patch until flagged go.
- No Grok CLI (`~/.grok/memory`) in the path. That silo does not feed GLM.
- No `~/soveryn_vnext/memory/kernel/MEMORY.md` as source of truth.
- No soul-file writes (`data/memory/souls/kernel.md` stays locked).
- No trading / wallets / Polymarket.
- No Dream consolidator, FTS5, or vectors beyond the existing Librarian embed used by desk recall.
- Do not merge `jit-metrics.js` JSONL into lattice nodes.

## Current state (why this wire)

| Surface | Memory today |
|---|---|
| Lattice | SQLite `soveryn_vnext/data/memory/lattice_vnext.db`. Close-not-overwrite via `remember_fact` + `close_and_supersede`. |
| Aetheria / Eve | `remember_fact` registered in `create_app`. `recall_k=5`, threshold `0.25`, `lattice_store` on the loop. Canonical fact rail cannot be evicted by cosine. |
| Messages Kernel | **No** `remember_fact`. **No** `lattice_store` / `recall_k` on the loop. Comment in `teach.py` and startup: “Aetheria + Eve only in v1.” |
| Pi Kernel | Stock tools (read/bash/edit/write). No lattice. JIT retry plugin exists, default off. |
| Grok Build | Separate `memory_v2` on the TUI. Irrelevant to GLM. |

`find_canonical_facts` already returns **global** canonical facts to any seat (excludes `LAYER_PRIVATE` belonging to someone else, excludes dream and `historical_snapshot`). A Kernel-taught house fact is visible to Eve and Aetheria. That is intended.

## Design

One store. Two Kernel seats. Same teach function.

```
Jon / Kernel session
        │
        ▼
 remember_fact(content, entity?, agent="kernel")
        │
        ▼
 lattice_vnext.db  (global, node_type=fact, canonical_fact)
        │
        ├─ Messages Kernel: AgentLoop recall (same as Eve)
        └─ Pi Kernel: flag-gated plugin → CLI → same Python teach/recall
```

Models cannot mint receipts. `remember_fact` mints `USER_REMEMBER`. Writer gate still uses AtticStore. Overflow still raises / attics; we do not invent a Kernel bypass.

### Entity slugs

Coding facts use stable slugs so replace is close-and-supersede, not a second competing node.

Examples:

- `kernel.cwg.copy` — no em dash on public CWG copy
- `kernel.crm.ops` — live book is pondwright-cwg-ops, Eve Basic
- `kernel.gotcha.chrome-logs` — do not hang on `grep \| head` of Chrome logs
- `kernel.open.<thread>` — open work

One claim, ≤400 chars (existing tool schema). `/flush` may emit several `remember_fact` calls, one entity each.

### First-turn inject

**Messages Kernel.** Same path as Eve: `lattice_store` + `recall_k=5` + `recall_threshold=0.25` + canonical fact rail. Soft prelude cap already exists on the loop. Do not add a second markdown prelude.

**Pi Kernel.** Plugin, flag on only: run house recall CLI, prepend at most **3000 characters** (~12 bullets) into system/context. Recency + token match, then hard trim. Empty recall → inject nothing (bit-identical to stock except the tool schemas).

### Tools (both seats, names stable)

| Tool / slash | Does |
|---|---|
| `remember_fact` | Existing teach loop. `/remember <note>` is sugar: `content=note`, entity optional. |
| `memory_search` | Keyword / token search over **canonical lattice facts** (reuse `find_canonical_facts` + optional LIKE). Not ripgrep over markdown. |
| `memory_get` | Read one node by lattice id (jail: that db only). |
| `/flush` | Manual. GLM summarizes this session → N `remember_fact` calls. Capture: decisions, open threads, “do not retry X”. No session-end hook in v1. |

Pi implements these as OpenCode custom tools that `spawnSync` a small module:

```
python3 -m soveryn.platform.lattice.kernel_memory <remember|search|get|recall>
```

Working directory / `PYTHONPATH` = `~/soveryn_vnext`. No HTTP to `:5001` required (Flask is localhost-only; Spark cannot reach it; Pi runs on the tower).

### Flag

Default **off**.

- Pi / overlay: `KERNEL_LATTICE=1` (alias `KERNEL_MEMORY=1` or `JIT_MEMORY=1`).
- Messages / Flask: `SOVERYN_KERNEL_LATTICE=1` in `soveryn_vnext/.env`. Startup registers Kernel `remember_fact` and sets loop recall **only** when this is on.

Flag off = stock Kernel on that seat. No schema, no inject, no extra prelude.

### Overlay layout (not written until go)

```
~/ablit-bake/jit-exp/overlay/plugins/kernel-lattice.js
```

Same pattern as `jit-tool-retry.js`: env gate at load, no Pi patch, no `config/opencode/opencode.json` edit until promote.

House Python (when go, still not this spec’s write):

```
soveryn/platform/lattice/kernel_memory.py   # CLI + recall trim
```

Startup change (when go): extend `_teach_agent` tuple with `"kernel"` behind the env flag; copy Eve’s `lattice_store` / `recall_k` block onto `name == "kernel"`.

### Optional human dump (not SSOT)

If a session needs a readable log, Kernel may **also** append `data/memory/skills/kernel/` notes or a dated file. That is not recall. Lattice nodes are memory. Do not build `memory/kernel/MEMORY.md` as a second book.

### Autonomy (later, not v1)

Weekday morning: Kernel reads open `kernel.open.*` facts, acts only if a test is still red or a file still missing. Same “wait until undeniable” rule. Zero markets.

## Tests (when go)

- `remember_fact(..., agent="kernel")` writes global canonical; Eve `find_canonical_facts` can see it.
- Supersede on same entity; old node tagged `historical_snapshot`.
- Flag off: Kernel loop `recall_k == 0`, tool not in Kernel schemas.
- Flag on: Kernel loop `recall_k == 5`; inject trim ≤ 3000 chars.
- Pi CLI path-jail: `memory_get` refuses paths outside the lattice db / node ids.
- No write to `souls/kernel.md`.

Reuse `tests/test_lattice_teach.py` patterns. Add `tests/test_kernel_lattice_flag.py` for startup gating.

## Rollout

1. **This spec** — freeze.
2. Dry overlay + 3 manual Pi sessions with `KERNEL_LATTICE=1` on a scratch prompt. Still no prod `opencode.json`.
3. Jon go → default-off plugin in house OpenCode plugins path (like `JIT_TOOL_RETRY`).
4. Jon go → `SOVERYN_KERNEL_LATTICE=1` on Messages Kernel.
5. Promote only if inject does not blow GLM 32k on a long coding session.

## Success

- Day-2 Pi or Messages session cites yesterday’s fact from the lattice.
- Flag off = stock Kernel.
- Soul file git-clean.
- Eve can recall a Kernel-taught house fact (shared spine).

## Decisions locked in this freeze

| Choice | Decision |
|---|---|
| Store | Lattice, not Grok markdown, not a Kernel-only notes tree |
| Inject cap (Pi) | 3000 chars |
| Desk recall | `recall_k=5`, threshold `0.25` (match Eve) |
| Flush | Manual `/flush` only in v1 |
| Pi vs Messages | Same teach/recall; **Pi overlay first**, Messages behind env, same PR series if cheap |
| Visibility | Global canonical — Kernel facts are house facts |

## Hands off until go

Do not write overlay JS, do not edit `startup.py` / `teach.py` comments as if live, do not touch `opencode.json`, `config/pi`, or `souls/kernel.md`.
