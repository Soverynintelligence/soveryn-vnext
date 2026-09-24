# ActTruth by SOVERYN — product tiers

**Brand:** ActTruth by SOVERYN · **Site:** acttruth.com  
**Package:** `soveryn-acttruth` (`import acttruth`) · **House:** `soveryn.platform.acttruth` (legacy shim: `continuum`)

## One-liner (job, not brand)

*Your AI stops lying about what it did, and stops acting without a budget — even if it has no long-term memory yet.*

## Money sentence

> **ActTruth is free so trust compounds. SOVERYN and the people who wire it are how you get paid.**

Open-core: give away the thin honesty layer. Charge for the house, the install, and the humans who make it stick.

---

## Free vs paid

| | **Free (Tier 1 — ActTruth)** | **Paid (SOVERYN + services)** |
|--|------------------------------|--------------------------------|
| **What** | Act ledger, unprompted budget, soft lessons, wrappers, CLI, proof receipts | Full house, crew, CC/HITL, memory, ops, hard teeth when ready |
| **License** | Apache-2.0 · `pip install` | Commercial / project / retainer (case by case) |
| **Who** | Anyone with a tool-using agent | Teams that want a crew under that truth, or help wiring it |
| **Proof** | Open pytest claims; local receipts only | Same honesty — plus house dogfood and install help |

### Free forever (the package)

Ships / will ship as the public download:

- Episodic **act ledger** (timeouts + soft `{error:…}` → FAIL rows)
- **Unprompted spend allowance**
- **Soft** anti-loop lessons (no hard ban in v0)
- `audit_tool` / `wrap_callable` + OpenAI-compatible helpers
- `acttruth` CLI · local proof export
- Proof **suite** (what we claim is what we test)

**Not** scraped onto the public site: live house fail rates, tool names, or customer ledgers.

### What we charge for

**1. SOVERYN House** — ActTruth is a sensor; the house is the organism.

- Full crew (Aetheria, Vett, Scotty, Kernel, …)
- Command Center, HITL, souls, Lattice-class memory (Tier 2+)
- Heartbeat / patrol already on budgets
- Later: hard refuse-after-×3, earned-keep → budget, hosted/support edges

**Pitch:** *ActTruth is free so your agent stops lying. SOVERYN is how a whole crew runs under that truth.*

**2. Consulting / buildouts** — cashflow while the package stays free.

| Engagement | What we do | How we get paid |
|------------|------------|-----------------|
| **Wire-up** | Drop ActTruth into their agent stack | Fixed project |
| **House install** | Stand up SOVERYN (or a slim crew) on their GPUs / colo | Setup + monthly retain |
| **Dogfood audit** | Read their ledger, find quiet FAIL loops, tune budgets/lessons | Day-rate or package |
| **Proof for buyers** | Help them export receipts / tell a checkable story to *their* customers | Project or retainer |
| **Adjacent (e.g. CWG)** | Same honesty layer on domain agents when useful | Attach to existing work |

We’re not selling “a Python module.” We’re selling: **your agents will stop failing quietly, and we’ll prove it.**

### Later paid edges (only after free core is known)

- Hard anti-loop (teeth)
- Multi-agent crew dashboards beyond DIY
- Hosted proof / compliance export
- Support SLA on the package

Do **not** put a license key on `pip install` before anyone cares.

### Explicit non-goals (v1 monetization)

- Multi-tenant ActTruth SaaS as the first SKU
- Hiding proof tests behind a paywall
- Publishing live dogfood scrapes as marketing

---

## What we assume

| Tier 1 needs | Tier 1 does **not** need |
|--------------|---------------------------|
| Agent that calls tools (or wraps tool calls) | Lattice / graph memory |
| Local SQLite (or configurable path) | SOVERYN house, CC, heartbeat |
| Optional: OpenAI-compatible runtime | History’s Ledger (different product) |

## Ladder

| Tier | Ships | Price posture | Audience |
|------|--------|---------------|----------|
| **1 — Act truth** | Ledger + budget + soft lessons + wrappers | **Free** (Apache-2.0) | Anyone with a tool-using agent |
| **2 — Memory add-on** | Lattice-class durable memory (optional) | Paid / with House | Long-horizon self/world memory |
| **3 — House** | Full SOVERYN crew, CC, HITL, souls | **Paid** | Local-house builders |

Do **not** ship Lattice-and-all as the first download.

## Unprompted spend (not “anti-agency”)

Budget rations **unprompted** tool spends (heartbeat / patrol), not chat with the user.  
Quiet notes do not spend. Scarcity makes acts matter; the ledger makes them honest.  
Earned-keep (stub) scores whether an unprompted act left durable delta — a proxy for “earned its keep,” not a measure of being.

## SOVERYN dogfood (now)

- Crew: aetheria, vett, scotty, kernel — per-agent ledger + budget  
- Tool registry → act-truth rows (timeouts / soft errors = FAIL)  
- Heartbeat + Vett patrol → budget gate + spend on action  
- Agent prelude → `[ACTTRUTH — what actually happened]` brief + soft lessons  
- Public package: https://github.com/Soverynintelligence/acttruth  
- Install: `pip install "git+https://github.com/Soverynintelligence/acttruth.git"`  
- Monorepo editable: `pip install -e packages/soveryn-acttruth`  
- CLI: `acttruth status` (also `python -m soveryn.platform.acttruth status`)

## Contact

- Product / proof: [acttruth.com](https://acttruth.com) · `hello@acttruth.com`
- House / install / consulting: [soverynintelligence.com](https://soverynintelligence.com)
