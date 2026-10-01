# soveryn-acttruth

**ActTruth by SOVERYN** — https://acttruth.com

> Your AI stops lying about what it did, and stops acting without a budget.

Tier-1 portable layer for tool-using agents:

- **Act ledger** — quiet timeouts and soft `{error:…}` payloads become FAIL rows
- **Unprompted spend allowance** — a ceiling on autonomous tool use
- **Soft lessons** — repeat the same FAIL pattern → anti-loop LESSON (no hard ban in v0)

Import name: `acttruth` · Dist name: `soveryn-acttruth` · Stdlib only · **Apache-2.0 (free).**

> **ActTruth is free so trust compounds. SOVERYN and the people who wire it are how we get paid.**

Tier 1 (this package) stays free. The SOVERYN house, installs, and consulting are how the lights stay on — see `docs/act-truth-product-tiers.md`.

## Install

**Public (recommended for outsiders):**

```bash
pip install "git+https://github.com/Soverynintelligence/acttruth.git"
```

Repo: https://github.com/Soverynintelligence/acttruth

**From this monorepo (dogfood / editable):**

```bash
cd /path/to/soveryn_vnext
pip install -e packages/soveryn-acttruth
acttruth status --root /tmp/demo-acttruth
```

## Wrap any callable

```python
from acttruth import ActTruth, audit_tool

at = ActTruth.open("~/.acttruth")

@audit_tool(agent="demo", name="search", acttruth=at)
def search(q: str):
    return {"error": "upstream down"}  # soft FAIL → ledgered

search("acttruth")
print(at.ledger.recall_brief("demo"))
```

## OpenAI-compatible tool loop

No OpenAI SDK required — call after each tool result:

```python
from acttruth.openai_tools import record_openai_tool_result, inject_lessons_message

lesson = record_openai_tool_result(
    agent="demo",
    tool_name="generate_image",
    arguments={"prompt": "…"},
    result={"error": "timed out"},
)
# optional: inject_lessons_message(messages, "demo")
```

See `examples/openai_loop.py` for a no-API-key demo.

## CLI

```bash
acttruth status
acttruth recall --agent demo
acttruth proof --style markdown --skip-pytest
python -m acttruth proof
```

Data dir: `ACTTRUTH_DIR` env, or `~/.acttruth`, or `--root`.

## SOVERYN house

Dogfood continues via `soveryn.platform.acttruth` (thin shim over this package).
House data stays under `<DATA_ROOT>/acttruth/`.

## Proof

```bash
# House proof suite (monorepo)
pytest tests/test_acttruth.py -q

# Package wrappers (no house)
pytest packages/soveryn-acttruth/tests -q
```

Live house ledgers are **private**. Public site shows claims + tests, not your dogfood scrape.

## Free vs paid (short)

| Free (this package) | Paid |
|---------------------|------|
| Ledger, budget, soft lessons, wrappers, CLI, local proof | SOVERYN house, crew/CC/HITL/memory, installs, dogfood audits, retainers |
| Apache-2.0 | Commercial / project |

## Not in v0

Hard refuse-after-×3, earned-keep → budget auto-tune, Lattice memory, multi-tenant SaaS, license keys on `pip install`.
