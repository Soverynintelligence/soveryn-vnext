# ActTruth by SOVERYN

**Your AI stops lying about what it did, and stops acting without a budget.**

| | |
|--|--|
| **Portable package** | `soveryn-acttruth` → `import acttruth` |
| **House facade** | `soveryn.platform.acttruth` (shim) |
| **Site** | [acttruth.com](https://acttruth.com) |
| **Legacy** | `continuum` import shim remains |

## What it is (Tier 1)

1. **Act ledger** — short facts about tool outcomes (including quiet timeouts / soft errors)
2. **Unprompted spend allowance** — heartbeat / patrol can act a little, then must stand down
3. **Soft lessons (anti-loop)** — same tool FAIL ×2+ in a window → LESSON in prelude + `acttruth_lesson` on the tool result: don’t repeat that pattern
4. **Earned-keep stub** — score whether an unprompted act left durable delta (not “being”)
5. **Wrappers** — `audit_tool` / `wrap_callable` + OpenAI-compatible helpers (no SDK dep)

Does **not** require Lattice. Does **not** replace black_box / telemetry. Soft lessons only in v0 (no hard refuse-after-×3 yet).

**Step 1** = wrongness becomes visible. **Step 2** = repeated wrongness becomes a lesson so autonomous agents stop blind retry loops.

## Install

**Public:**

```bash
pip install "git+https://github.com/Soverynintelligence/acttruth.git"
```

Repo: https://github.com/Soverynintelligence/acttruth

**Monorepo dogfood:**

```bash
cd ~/soveryn_vnext
pip install -e packages/soveryn-acttruth
```

Outsiders use `~/.acttruth` or `ACTTRUTH_DIR`. SOVERYN configures `<DATA_ROOT>/acttruth/` on import.

## Crew (house)

Per-agent streams for **aetheria**, **vett**, **scotty**, **kernel**.

## Proof suite

```bash
cd ~/soveryn_vnext
python -m pytest tests/test_acttruth.py -v
pytest packages/soveryn-acttruth/tests -q
```

## CLI

```bash
acttruth status
acttruth status --agent vett
acttruth recall --agent aetheria
acttruth proof --style markdown --skip-pytest

# still works:
python -m soveryn.platform.acttruth status
python -m acttruth status
```

## Quick outsider wrap

```python
from acttruth import ActTruth, audit_tool

at = ActTruth.open("~/.acttruth")

@audit_tool(agent="demo", name="search", acttruth=at)
def search(q: str):
    return {"error": "upstream down"}
```

See `packages/soveryn-acttruth/README.md` and `examples/openai_loop.py`.

## Free vs paid

**ActTruth (Tier 1) is free** (Apache-2.0). SOVERYN house + wiring/consulting are how we charge.

See `docs/act-truth-product-tiers.md` for the full ladder and engagement table.

## Tiers

See `docs/act-truth-product-tiers.md`.
