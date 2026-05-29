# Phase 2b-i Verification: Provenance + Write Gate + Attic Storage

Phase 2b-i builds the storage substrate that can hold truth safely without changing Aetheria's recall voice. Recall rendering, legacy migration, prompt integration, and no-ghost-memory rendering enforcement remain Phase 2b-ii.

## Result

- Status: closed
- Final code commit before docs: `cbd2778 platform: add provisional lattice facets`
- Full suite: `747 passed in 5.38s`
- Frozen recall/lattice subset: `65 passed in 0.61s`
- Working tree at close: clean after this docs commit

Frozen recall/lattice subset command:

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_recall_formatter.py tests/test_lattice.py tests/test_platform_lattice.py tests/test_app_startup_recall.py -q
```

## Commit Trail

```text
f9b0c47 docs: record Phase 2b-i baseline audit
53e1214 platform: add lattice provenance type
fab6341 platform: attach provenance to lattice entries
c9b7003 platform: add lattice write gate
14621a8 platform: implement durable Attic store
c586220 platform: add additive Attic promotion
14b7438 platform: add provenance-aware lattice writer
cbd2778 platform: add provisional lattice facets
```

## Acceptance Criteria

- Baseline/API audit exists and was committed before implementation: `docs/phase2b-i-baseline-audit.md`.
- Provenance is first-class:
  - `ProvenanceClass`: witnessed, told, inferred, consolidated, legacy.
  - `Provenance` validates confidence in `[0.0, 1.0]`.
  - `INFERRED` requires non-empty `derived_from`.
  - `Entry.provenance` is optional and backward compatible.
- Write gate is pure and safe-by-default:
  - Structural/observational writes classify as `AUTO`.
  - Identity and affective region writes classify as `CONFIRM`.
  - Interpretive kinds classify as `CONFIRM` regardless of region.
  - Unknown kinds classify as `CONFIRM`.
- Attic is durable and separate:
  - `AtticStore` is SQLite-WAL backed.
  - Attic has its own `attic_entries` and `attic_links` tables.
  - Attic fetch returns private, non-canonical `Entry` objects with structured provenance.
  - Attic entries do not surface through `LatticeStore` region/query paths.
- Additive promotion exists:
  - Promotion creates a new canonical Lattice node.
  - The canonical node carries consolidated provenance with a chain back to the Attic id.
  - The original raw Attic entry remains unchanged.
  - Promotion requires `review` or threshold-satisfied `corroboration`.
  - Volume and recency do not promote.
- Provenance-aware writer exists:
  - AUTO writes land canonical with provenance.
  - CONFIRM writes without `confirmed=True` route to Attic, not canonical Lattice.
  - CONFIRM writes with `confirmed=True` land canonical with confirmation recorded.
- Facets are provisional metadata:
  - `working_context`, `pattern_reservoir`, `friction_log`, `salience_cache` are labels in `Entry.metadata`.
  - They are not DB columns or tables.
  - They are orthogonal to `Region` and reshapeable without migration.

## Headline Proofs

### Identity/Affective Require Review

Proved by `tests/test_write_gate.py`:

- `test_identity_and_affective_regions_always_require_confirmation`
- `test_interpretive_kinds_require_confirmation_regardless_of_region`
- `test_unknown_kind_defaults_to_confirmation`

Integrated through the writer by `tests/test_lattice_writer.py`:

- `test_unconfirmed_confirm_class_write_routes_to_attic_not_canonical`
- `test_confirmed_confirm_class_write_lands_canonical_with_confirmation_recorded`
- `test_interpretive_unconfirmed_semantic_write_cannot_become_canonical`

### Raw Stays Raw

Proved by `tests/test_attic_store.py`:

- `test_promote_creates_canonical_lattice_entry_with_chain_and_preserves_raw`
- `test_promote_requires_valid_trigger`
- `test_corroboration_promotion_requires_threshold`
- `test_volume_and_recency_never_auto_promote`

The raw-preservation test captures `before = attic.get_record(raw.id)`, promotes, then asserts `after == before` and verifies the Attic entry remains fetchable.

## Explicit Non-Goals

Phase 2b-i does not implement:

- recall rendering changes
- legacy lattice migration
- prompt integration
- no-ghost-memory rendering enforcement
- dream/consolidation daemon behavior
- Aetheria field-review taxonomy changes
- persona/souls changes
- recall threshold changes

Those are Phase 2b-ii or later. The frozen recall/lattice subset stayed green, and `format_recall_context`, prompt wording, startup threshold `0.70`, and legacy read semantics were not changed.

## Commands Run

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_recall_formatter.py tests/test_lattice.py tests/test_platform_lattice.py tests/test_app_startup_recall.py -q
```
