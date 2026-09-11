# Lattice Stale Detectors — Working Spec (S5)

| Field | Value |
|-------|-------|
| **Title** | Lattice stale detectors (cheap flags, no model calls) |
| **Author** | Alpha / Jon |
| **Date** | 2026-09-10 |
| **Status** | Draft for build — Jon said go |
| **Repo path** | `docs/superpowers/specs/2026-09-10-lattice-stale-detectors-design.md` |
| **Depends on** | Lattice teach loop S1–S4 (`remember_fact`, `close_and_supersede`, Aetheria+Eve register, seeds) |
| **Out of scope** | Utopia / bitemporal Postgres, LLM judges, Scout→Lattice, CRM as Lattice SoT, auto-rewrite of facts |

---

## Goal

Catch **silent stale current house facts** before desks confidently cite March’s wrong truth in September.

Detectors run on a **weekday schedule** (or on-demand CoS). They emit a short **flag digest** — never auto-repair. Jon (or a desk with `remember_fact`) closes/supersedes.

Inspired by the “what happens in six months?” framing; implementation stays on our Lattice substrate.

---

## Current substrate (assumed after S1–S4)

| Piece | Use |
|--------|-----|
| Current truth | `type=fact`, tag `canonical_fact`, **no** `historical_snapshot`, `layer=global` preferred |
| Historical | tag `historical_snapshot` + `supersedes` edge + `representation_log` |
| Entity | optional tag `entity:<slug>` |
| Provenance | `temporal_context` / `as_of`, `source`, receipt |
| Parallel | `pinned_memory.md` — not Lattice; still a contradiction surface |
| CRM | `crm.pondwright.com` / ops DB — **not** merged into Lattice (v1); optional *read-only drift check* later |

---

## Detectors (zero LLM)

All run as pure SQLite / file checks. Each flag: `{ detector, lattice_id?, entity?, summary, severity, suggested_action }`.

### D1 — TTL / as_of age

**Fire when:** a current `canonical_fact` has `provenance.temporal_context` (or node created_at) older than **N days** (default **90**; house rules may use **180**).

**Severity:** `low` if still plausible ops; `med` if entity is CWG job / ads / travel.

**Suggested action:** “Re-confirm with Jon or `remember_fact` same entity.”

### D2 — Entity collision (two currents)

**Fire when:** two or more current `canonical_fact` rows share the same `entity:<slug>` (neither has `historical_snapshot`).

**Severity:** `high` — teach path bug or race.

**Suggested action:** Keep newest, close others via `close_and_supersede` / repair script; do **not** silent-delete.

### D3 — Pinned vs Lattice contradiction (lexical)

**Fire when:** a line in `pinned_memory.md` (or house pin file) shares a known entity key / distinctive phrase with a current Lattice fact but differs on a locked token (yes/no, paused/live, hold/active, dollar amount, phone).

**v1 shape:** small hand-maintained checklist of `(entity_slug, pin_needle, lattice_needle)` — not free NLP.

**Severity:** `med`.

**Suggested action:** Teach Lattice from Jon; or update pin to match current fact.

### D4 — Orphan historical / broken supersede chain

**Fire when:**
- node has `historical_snapshot` but no inbound `supersedes` edge from a current fact, **or**
- `supersedes` edge points at missing id, **or**
- current fact has `entity:` but an older same-entity historical exists with no edge

**Severity:** `med` (integrity).

**Suggested action:** Repair edges / re-run close path; do not invent content.

### D5 (optional later) — CRM drift

**Fire when:** Lattice `entity:cwg.job.*` claim disagrees with live CRM job status/hold/don’t-contact flags.

**Blocked until:** stable CRM read API from ops DB and entity map. **Not in first ship.**

---

## Delivery

| Mode | Cadence | Route |
|------|---------|-------|
| **Digest** | Weekdays ~07:05 America/New_York (after CoS morning digest or as a section of it) | Quiet if zero flags; else bullet list to Jon |
| **On-demand** | “run lattice stale check” | Same report, immediate |

**Never:** auto `remember_fact`, auto Attic promote, or model rewrite.

---

## Implementation slices

| # | Slice | Done when |
|---|--------|-----------|
| **S5.0** | This spec accepted | Jon says build |
| **S5.1** | CLI / library `lattice_stale_scan()` → JSON flags (D1–D4) | Unit tests with fixture DB |
| **S5.2** | Wire weekday digest (CoS routine or vNext cron) | Empty run stays quiet; seeded stale fact appears once |
| **S5.3** | Mission-control / memory browse: show flag count | Optional; after S5.2 |

---

## Config (defaults)

```yaml
ttl_days_default: 90
ttl_days_by_entity_prefix:
  house.rule.: 180
  cwg.job.: 60
  cwg.ads.: 30
  lab.: 90
pinned_path: pinned_memory.md   # or house pin path used in prod
max_flags_per_digest: 20
```

---

## Test plan (minimal)

1. `test_d1_ttl_flags_old_as_of`
2. `test_d2_two_current_same_entity`
3. `test_d3_pin_checklist_hit`
4. `test_d4_orphan_historical`
5. `test_digest_quiet_when_clean`
6. Manual: seed a stale `cwg.ads.pmax`-style fact → weekday digest names it

---

## Non-goals / refusals

- No four-detector blog clone as a separate product
- No Groq / RAG demo dependency
- No merging CRM into Lattice as SoT
- No LLM “is this stale?” judge in v1
- No overnight / weekend spam — weekday digest only unless Jon asks

---

## Anchors

- Teach loop: `docs/superpowers/specs/2026-09-06-lattice-teach-loop-design.md`
- Store / rail: `soveryn/platform/lattice/legacy.py`, `fact_rail.py`
- Teach tool: `remember_fact` + tests in `tests/test_lattice_teach.py`
- Live DB: `data/memory/lattice_vnext.db`
