# Phase 2b-ii-b1 Baseline + Migration-Surface Audit

Task 1 gate for Phase 2b-ii-b1. This document records the real prod/vnext memory migration surface before implementation. No source code changes happen in this task.

## Baseline

- vnext HEAD at audit start: `c930fef docs: close Phase 2b-ii-a verification`
- `git status --short` at audit start: empty
- Full test command: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q`
- Full test result: `775 passed in 5.43s`
- Live recall diff against `c930fef` for `recall_policy.py`, `loop.py`, `startup.py`: empty

## Prod Lattice Source

- Path: `/home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice.db`
- Read mode for b1: source only, copy not move. Do not mutate prod lattice.

Schema:

```sql
CREATE TABLE nodes (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,
    layer        TEXT NOT NULL DEFAULT 'lattice',
    agent        TEXT NOT NULL,
    content      TEXT NOT NULL,
    intensity    REAL NOT NULL DEFAULT 0.3,
    salience     REAL NOT NULL DEFAULT 0.5,
    access_count INTEGER NOT NULL DEFAULT 0,
    tags         TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    embedding    TEXT DEFAULT NULL,
    intent       TEXT,
    provenance   TEXT DEFAULT NULL
);
CREATE INDEX idx_nodes_agent    ON nodes(agent);
CREATE INDEX idx_nodes_layer    ON nodes(layer);
CREATE INDEX idx_nodes_type     ON nodes(type);
CREATE INDEX idx_nodes_salience ON nodes(salience DESC);
CREATE INDEX idx_nodes_created ON nodes(created_at DESC);
```

Counts:

- Total rows: `1682`
- By agent:
  - `aetheria`: `1440`
  - `scotty`: `134`
  - `ares`: `51`
  - `vett`: `46`
  - `scout`: `8`
  - `test`: `1`
  - `test_t1`: `1`
  - `tinker`: `1`
- By type:
  - `event`: `1120`
  - `fact`: `430`
  - `insight`: `106`
  - `library_chunk`: `23`
  - `concept`: `3`
- By layer:
  - `private`: `1558`
  - `lattice`: `63`
  - `global`: `36`
  - `library`: `23`
  - `core`: `2`
- Non-empty legacy `provenance`: `30`
- Salience range/avg: min `0.0`, max `1.0`, avg `0.354809750297265`
- Access-count range/avg: min `0`, max `37753`, avg `471.442330558858`

Aetheria type/layer distribution:

| type | layer | count | avg_salience | max_access_count |
|---|---|---:|---:|---:|
| event | private | 1010 | 0.292 | 611 |
| fact | private | 251 | 0.539 | 37753 |
| insight | private | 74 | 0.502 | 2696 |
| fact | lattice | 45 | 0.505 | 1440 |
| library_chunk | library | 23 | 0.308 | 3 |
| insight | global | 16 | 0.709 | 15255 |
| fact | global | 15 | 0.790 | 22947 |
| concept | global | 2 | 0.850 | 1267 |
| event | lattice | 2 | 0.800 | 461 |
| fact | core | 2 | 0.925 | 33247 |

Observed pollution counts in Aetheria rows:

- Retired-agent mentions (`tinker`, `scout`, `vision`, `aetheria_public`): `85`
- Stale model/runtime refs (`llama 70b`, `llama-70b`, `heretic`, `qwen`): `24`
- Autonomous heartbeat phrasing (`[I told Jon]`, `shared_with_jon`, `deliberate-communication`): `152`
- Test artifacts (`TEST_TRIGGER`, `Project Obsidian`, `forbidden fact`): `2`

## Current `LatticeStore` Read Surface

File: `soveryn/platform/lattice/legacy.py`

Public read APIs today:

- `get_node(node_id) -> Node | None`
- `find_nodes_by_keywords(agent, query, limit=20, include_global=True) -> tuple[Node, ...]`
- `find_nodes_by_embedding(agent, embedding, limit=10, threshold=0.70, layer_filter=None) -> tuple[tuple[Node, float], ...]`
- `LegacyLatticeAdapter.fetch(query, agent, limit=20, include_global=True) -> tuple[Entry, ...]`

Important helpers:

- `_row_to_node(row)` parses tags, embedding, provenance with tolerant JSON helpers.
- `region_for_node(node)` maps only explicit type/layer signals:
  - identity only when type is one of `identity`, `self`, `persona`, `soul`
  - event/conversation/journal/episode -> episodic
  - fact/concept/library or library layer -> semantic
  - procedure/skill/howto/tool -> procedural
  - mood/affect/salience -> affective
  - otherwise unknown
- `entry_from_node(node)` creates an `Entry` with `source="legacy_lattice"`, metadata copy of legacy fields, and no first-class structured provenance.

Gap for b1:

- There is no public full export / iterator API for migration.
- Keyword and embedding reads are intentionally recall/search scoped and insufficient for copying the whole legacy corpus.
- Task 2 should add a read-only full-node export helper, without hardcoding prod paths or reaching into private `_conn` from migration code.

## Current `AtticStore` Surface

File: `soveryn/platform/lattice/attic.py`

Current schema:

```sql
CREATE TABLE IF NOT EXISTS attic_entries (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attic_links (
    attic_id TEXT NOT NULL,
    lattice_id TEXT NOT NULL,
    PRIMARY KEY (attic_id, lattice_id),
    FOREIGN KEY (attic_id) REFERENCES attic_entries(id) ON DELETE CASCADE
);
```

Current write/read APIs:

- `AtticStore.append(content, metadata=None, linked_lattice_ids=(), provenance=None) -> AtticRecord`
- `AtticStore.fetch(query, include_links_to=None) -> tuple[Entry, ...]`
- `AtticStore.get_record(attic_id) -> AtticRecord | None`
- `AtticStore.promote(attic_id, lattice_store, to_region, trigger, agent="aetheria", corroboration_count=0, corroboration_threshold=2) -> str`

Append behavior:

- Stores content, JSON metadata, structured provenance, and links in `attic_links`.
- Returns `AtticRecord` with `linked_lattice_ids` and provenance.
- Default raw provenance is currently `TOLD`, `source="attic"`, confidence `0.2`; b1 migration must pass explicit `LEGACY`, `source="legacy_lattice"` provenance instead of relying on default.

Fetch behavior:

- Returns private, non-canonical `Entry` objects with:
  - `source="attic"`
  - `region=UNKNOWN`
  - `private=True`
  - `metadata["canonical"] = False`
  - `metadata["zone"] = "attic"`
  - `metadata["linked_lattice_ids"] = [...]`

Idempotency gap:

- There is no direct `records_linked_to(lattice_id)` helper.
- `fetch(query, include_links_to=...)` is content-query scoped and not sufficient as an idempotent migration primitive.
- Task 3 should add an explicit linked-record lookup.

Current promote behavior:

- Valid triggers are `review` or threshold-satisfied `corroboration`.
- It creates canonical lattice nodes with `ProvenanceClass.CONSOLIDATED`, `source="attic_promotion"`, and `chain=(raw_attic_id,)`.
- It writes trigger metadata and `attic_id` into the legacy node provenance dict.

Gap for identity spine:

- 2b-ii-a renderer expects reviewed legacy via `CONSOLIDATED` with `source` starting `legacy_`, specifically `legacy_identity_review`.
- Current `AtticStore.promote()` does not produce that source or the `migration_identity_review` trigger.
- b1 needs either a narrowly extended promotion path or a b1-specific promotion helper that preserves raw Attic records and writes canonical identity nodes with the locked marker.

## Identity Candidate Grounding

Prod data does not have a useful explicit identity region. Type values are mostly `event`, `fact`, `insight`, `library_chunk`, `concept`; there are no meaningful `identity` rows to rely on.

Therefore candidate selection must use review signals, not `region_for_node()` alone.

Candidate ranking signals:

- tags/content around identity, self, interaction style, presence, autonomy, directness, performance mode, friendship, relationship, voice, home, memory philosophy, Aetheria/Jon continuity
- salience and access_count as ranking inputs only
- provenance/source metadata when present, but legacy provenance is sparse and weak (`30` rows only)

Non-proof rule:

- Salience/access_count are review-priority signals, not promotion evidence.
- Nothing promotes solely because it is high-salience or high-access.

## Tightened Identity-Review Exclusion Categories

These are locked for Task 5 candidate report enforcement.

1. Retired-agent mentions:
   - `tinker`, `scout`, `vision`, `aetheria_public`
2. Retired/stale model refs:
   - `llama 70b`, `llama-70b`, retired Qwen/Heretic runtime claims, stale `Tinker will...` claims
3. Autonomous heartbeat phrasing:
   - `[I told Jon]`, `shared_with_jon`, `deliberate-communication`, repeated presence pings
4. False tool/write claims:
   - Examples: `I wrote`, `I saved`, `I filed`, `I posted`
   - This must be a **structural check**, not a substring-only rule: exclude when there is no backing tool-output provenance or real write evidence.
5. Test artifacts:
   - `TEST_TRIGGER`, `Project Obsidian`, `forbidden fact`

Additional exclusion classes from the b1 design:

- duplicates and near-duplicate weaker rows
- contradiction/near-duplicate weaker rows
- tool/persona-policy artifacts
- low-salience tail
- stale model/runtime facts
- hardware/work facts unless identity-relevant
- noisy `shared_with_jon` event broadcasts

## DO NOT TOUCH in b1

These live voice surfaces are frozen until b2:

- `soveryn/agents/aetheria/recall_policy.py`
- `soveryn/agents/loop.py`
- `soveryn/app/startup.py`
- persona files
- souls files
- recall threshold `0.70`
- `format_recall_context`
- AgentLoop recall insertion behavior
- startup recall wiring

b1 does not wire the 2b-ii-a assembler into live recall. b1 produces dark migrated data and a reviewed identity spine only.

## Task 1 Gate

This audit is the gate for b1 implementation. Task 2 may start only after this document is committed alone with no source changes and the full suite remains green.
