# Lattice Teach Loop — Working Spec

| Field | Value |
|-------|-------|
| **Title** | Lattice teach loop (Jon teaches once → shared current truth) |
| **Author** | Alpha / Jon |
| **Date** | 2026-09-06 |
| **Status** | Accepted 2026-09-06 — Aetheria + Eve teach; build S1–S4 |
| **Repo path** | `docs/superpowers/specs/2026-09-06-lattice-teach-loop-design.md` |
| **Depends on** | Live `LatticeStore`, `LatticeWriter`, fact rail, representation `_supersede` |
| **Out of scope** | Utopia install, Kernel→Hermes, CRM↔Lattice merge, Attic mass-promote, auto-distill of chat into house facts |

---

## Goal

Jon teaches a fact **once**. It lands as a durable Lattice node with **source + time**. Every desk seat (Aetheria, Eve, Kernel, …) can read the **same current** fact. When truth changes, the house **closes** the old row and writes a new one — never silent overwrite.

Not: more reflections. Not: Utopia. Not: training weights.

---

## Current substrate (measured 2026-09-05/06)

| Piece | Reality |
|--------|---------|
| DB | `data/memory/lattice_vnext.db` (~3.8k nodes) — **LIVE** |
| Store | `soveryn/platform/lattice/legacy.py` `LatticeStore` — append-only `write_node` |
| Gated writer | `LatticeWriter` + `write_gate` + `USER_REMEMBER` receipt — **built, unit-tested, not wired to seat tools** |
| Fact rail | `CANONICAL_FACT_TAG` + `find_canonical_facts` + AgentLoop merge — **code live, 0 tagged rows in prod** |
| Close-not-overwrite | Representation `_supersede` (`historical_snapshot` tag + `supersedes` edge + `representation_log`) — **API exists; daemon passes `supersedes=None`; log empty** |
| Cognition notes | Versioned with `supersedes` id — pattern to steal for house facts |
| Attic | Pending/uncertain quarantine — keep for non-receipt writes; **not** the teach UX |
| Seat tools | Aetheria (and peers) lattice tools are **read-only** by design today |
| Parallel truth | `pinned_memory.md` — always-on markdown; **not** Lattice nodes |

**Gap in one line:** teach channel empty; Writer unused; supersede unused for Jon-taught facts.

---

## Product shape (v1)

### House fact

One sentence of **current operational truth**.

| Field | Rule |
|-------|------|
| `content` | ≤400 chars (`fact` content cap). One claim. |
| `type` | `fact` |
| `layer` | `global` (shared across seats; not private Aetheria residue) |
| `tags` | must include `canonical_fact`; optional `entity:<key>` |
| `provenance.cls` | `told` (Jon) or `witnessed` (tool+confirm) |
| `provenance.source` | non-empty — e.g. `jon` / Messages turn id / URL |
| `provenance.temporal_context` | as-of ISO date or short phrase (`as of 2026-09-06`) |
| `provenance.generator` | `teach_loop` / seat id |
| Receipt | `USER_REMEMBER` (or `TOOL_OK` only when Jon confirmed in-band) |
| Writer kind | `factual_anchor` → Writer tags `canonical_fact` |

**Entity key (optional but preferred for supersede):** stable slug, e.g.

- `house.rule.no_street_address`
- `cwg.job.valkanoff`
- `cwg.job.dan_ward`
- `cwg.ads.pmax`
- `lab.voice.tts`
- `lab.kernel.runtime`

### Current vs historical

- **Current:** has `canonical_fact`, does **not** have `historical_snapshot`
- **Historical:** tagged `historical_snapshot`; linked from newer node via `supersedes` edge (new → old); row in `representation_log`
- Default recall / fact rail: **exclude** `historical_snapshot` (existing cosine path already has `include_historical`; keep that contract)

### Scopes in v1

**In:**

1. House operating rules (no public street, seating freezes, voice=Kokoro, Kernel=OpenCode+Sparks, Vett folded→Eve, …)
2. CWG job / ops facts Jon locks (Ward hold, Valkanoff don’t-contact, Care budgets, ads paused, travel rule builds-vs-green-water)

**Out (v1):**

- Pondwright CRM jobs table as source of truth (CRM stays CRM)
- Scout trend briefs (ephemeral; may cite, not teach)
- Dream / heartbeat reflections
- Identity / affective claims (still CONFIRM / Attic via existing gate)

---

## Teach UX

### Tool: `remember_fact` (all desk seats that may teach)

Not raw `write_node`. Model cannot mint a receipt.

**Args:**

- `content` (string, required)
- `entity` (string, optional slug)
- `source` (string, default `jon`)
- `as_of` (string, optional; default now UTC date)
- `replace_entity` (bool, default true) — if entity exists as current canonical, close-and-supersede

**Behavior:**

1. Sanitize / clamp content (`on_overflow=raise` so model shortens)
2. Build `Provenance(cls=told, source=…, confidence=1.0, temporal_context=as_of, generator=teach_loop)`
3. `ActionReceipt(USER_REMEMBER, source=jon)`
4. If `entity` set and a current `canonical_fact` with tag `entity:<slug>` exists → **close-and-supersede** (see below)
5. Else `LatticeWriter.write(..., region=SEMANTIC, kind=factual_anchor, confirmed=True, receipt=…)` with **layer forced to `global`** (Writer today defaults agent private — **spec change:** teach path must pass / set `global`)
6. Embed on write (existing night librarian backfill is backup)
7. Return `{ ok, lattice_id, superseded_id? }`

**CoS / Messages path:** When Jon says “lock this” / “remember this” in chat, the seat calls `remember_fact` — no separate HTTP API required in v1.

### Close-and-supersede

Steal representation writeback (`agents/representation/writeback.py` `_supersede`):

1. Write **new** fact node (global, canonical, entity tag)
2. Tag **old** with `historical_snapshot` (do not mutate `content`)
3. Edge `relationship='supersedes'` new → old
4. Insert `representation_log` row (old_id, new_id, content heads, run_id=`teach:<uuid>`, confidence)

Add thin wrapper on store or Writer:

`close_and_supersede(*, old_id, new_content, entity, provenance, receipt, agent) -> WriteResult`

Never `UPDATE` old content in place.

### Read path (already mostly there)

- AgentLoop auto-recall: keep `find_canonical_facts` + `merge_fact_rail`
- Seat tools: search / get_node / recent unchanged
- Ensure global-layer canonical facts are visible to every seat’s scoping (today: non-private of others + own; `global` already shared — verify in tests)

Miss hint (optional v1.1): if query tokens look like a known entity and rail empty → “no current house fact for X — ask Jon.”

---

## Seed set (manual teach, first ship)

Teach via `remember_fact` (or one-shot script using the same Writer path) — do **not** bulk-copy reflections.

Suggested first seeds (Jon confirms wording):

1. CWG has no public street address (home = office); service-area + (910) 581-3970 only — `house.rule.no_street_address` / `cwg.rule.no_street`
2. CWG Google Ads Performance Max paused (account + conversion tag kept) — `cwg.ads.pmax`
3. Dan Ward rebuild ON HOLD — do not quote / lock dollars — `cwg.job.dan_ward`
4. Andrew Valkanoff: paid; do not contact; CWG owes two fish; twice-yearly service $170 — `cwg.job.valkanoff`
5. Builds: travel where customer pays; green-water / maintenance stay local Sandhills (not Charlotte green-water) — `cwg.rule.travel`
6. Aetheria TTS = Kokoro (not F5) — `lab.voice.tts`
7. Kernel = OpenCode + vLLM on Sparks; not Hermes runtime — `lab.kernel.runtime`
8. Vett folded into Eve — no live Vett seat — `house.bench.vett`
9. Aquascape Inc = supplier / trend signal for backyard ideas — not peer competitor — `cwg.supplier.aquascape`
10. Estimator locked; pondwright.com public build hold — as applicable

Acceptance: Eve and Aetheria both retrieve the same node id for a phone/name query that hits the fact rail.

---

## Implementation slices (ordered)

| # | Slice | Done when |
|---|--------|-----------|
| **S0** | This spec locked | Jon says build |
| **S1** | `remember_fact` tool + Writer path with `layer=global` + embed | Unit test: teach → tagged `canonical_fact` in DB |
| **S2** | `close_and_supersede` + entity tag lookup | Teach same entity twice → 1 current, 1 historical, 1 edge, 1 log row |
| **S3** | Register tool on Aetheria + Eve (both desks) | Live Messages: “remember …” → node id returned |
| **S4** | Seed 5–10 facts from list above | Fact rail non-empty; cross-seat recall demo |
| **S5** | Ops: mission-control / memory browse filter `canonical_fact` | Jon can see current house facts without SQL |

No Flask bounce required beyond normal tool registry reload / vNext restart if tools load at startup.

---

## Non-goals / refusals

- Do not expose raw `write_node` to the model
- Do not auto-promote Attic → canonical without Jon receipt
- Do not install Utopia / bitemporal Postgres
- Do not merge Pondwright `leads.db` into Lattice
- Do not route Scout overnight into Lattice teach (trends stay briefs)
- Do not treat pinned_memory.md as write-through in v1 (optional later: seed script reads pinned → teach)

---

## Test plan (minimal)

1. `test_remember_fact_writes_global_canonical` — Writer + tag + provenance
2. `test_remember_fact_supersedes_entity` — second teach closes first
3. `test_fact_rail_returns_seed` — `find_canonical_facts` hits seed content
4. `test_historical_excluded_by_default` — cosine / rail skip `historical_snapshot`
5. Manual: Messages teach → Eve search sees same id

---

## Decisions (Jon)

1. **Who teaches:** Aetheria **and** Eve (both have desks). Kernel not in v1 teach set unless asked later.
2. **Seeds:** use the ten in this spec unless Jon edits mid-flight.
3. **Surfaces:** Messages desk tools first; CoS/tower API later if needed.

---

## Anchors

- Store / rail: `soveryn/platform/lattice/legacy.py`
- Writer / gate / receipt: `writer.py`, `write_gate.py`, `receipt.py`, `provenance.py`
- Supersede reference: `soveryn/agents/representation/writeback.py`
- Fact rail merge: `fact_rail.py` + AgentLoop
- Live DB: `data/memory/lattice_vnext.db`
