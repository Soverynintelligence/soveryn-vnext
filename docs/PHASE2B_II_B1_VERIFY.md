# Phase 2b-ii-b1 Verification: Legacy Migration + Identity Spine

Phase 2b-ii-b1 migrated prod-derived legacy memory into vnext storage while keeping Aetheria's live recall path dark. It copied the prod lattice into vnext Attic as low-confidence LEGACY Channel B material, then promoted a bounded reviewed identity spine into the vnext lattice as CONSOLIDATED `legacy_identity_review` Channel A material.

## Result

- Status: closed
- Final code/data-record commit before this docs closeout: `fc54015 lattice: record dark legacy migration execution`
- Full test command: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q`
- Full test result: `798 passed in 5.63s`
- Migration report: `docs/PHASE2B_II_B1_MIGRATION_REPORT.md`
- Structured result artifact: `docs/phase2b-ii-b1-real-migration-result.json`
- Live recall remains unchanged from the dark-boundary baseline `c930fef`.

Live-recall unchanged check:

```bash
git diff c930fef..HEAD -- \
  soveryn/agents/aetheria/recall_policy.py \
  soveryn/agents/loop.py \
  soveryn/app/startup.py
```

Result: empty diff.

## Migration Counts

- Prod source: `/home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice.db`
- Prod SHA-256 before/after: `3a77987247ca90f4c46f71eacd7ff2492a7045a70b5db162fdad7d907c56b2d5`
- Prod mtime_ns before/after: `1780108071529894889` / `1780108071529894889`
- Prod size before/after: `17686528` / `17686528`
- Prod unchanged: `true`
- Total prod rows read: `1682`
- Attic DB path: `/home/jon-deoliveira/soveryn_vnext/data/lattice/attic.db`
- Attic rows before/after: `0` / `1682`
- Attic links after migration: `1682`
- First migration run: `1682` migrated, `0` skipped existing
- Idempotency rerun: `0` migrated, `1682` skipped existing

Runtime DBs are intentionally not committed. `.gitignore` excludes `data/lattice/*.db*`; the migration report and JSON artifact are the committed evidence.

## Identity Spine

- Vnext canonical lattice DB path: `/home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice_vnext.db`
- Vnext canonical nodes before/after: `0` / `12`
- Identity candidates evaluated: `1417`
- Accepted/rejected: `12` / `1405`
- Identity spine cap: `12`
- Canonical identity spine promoted: `12`
- Promotion skipped existing/missing/unaccepted: `0` / `0` / `1405`
- Promotion idempotency rerun: `0` promoted, `12` skipped existing
- Independent SQLite check: `12` total vnext nodes, `12` identity nodes, `12` with `legacy_identity_review` provenance.

Promoted canonical identity ids:

- `2254d5f1-fc09-4e20-adbe-90a5eed80c2e`
- `90a5b089-8165-484d-bc4f-4ff29732b1e9`
- `2d449fb8-c205-4c91-864e-0df5a3dc2cfd`
- `dff427db-abdc-4664-8c20-edd2872ee8c1`
- `ab481b58-3da5-4f1b-8308-9f50a46856df`
- `904ff2d2-07da-495e-b18f-cf634cd37258`
- `769bf04d-bdf4-44f2-acf2-7879b1cebb03`
- `981c95c2-8bd8-4375-8fc3-1b0af982366a`
- `fc73f534-20de-4b36-b07d-19a18b74a0e7`
- `de2b9a48-1650-41d2-8ad2-75a7162ee038`
- `6fa7a811-49cf-4790-8084-a87742b50520`
- `1f664eb4-7ce4-476e-ab71-b204bc638707`

Each promoted identity node is `type="identity"` with `CONSOLIDATED` provenance, `source="legacy_identity_review"`, `trigger="migration_identity_review"`, a legacy id, and a chain back to the raw Attic id. Raw Attic records remain unchanged and available as Channel B material.

## Built Path

Task sequence completed:

1. Baseline and migration-surface audit.
2. Read-only legacy export API.
3. Attic linked-record lookup for idempotency.
4. Legacy-to-Attic migration helper.
5. Identity-review candidate report generator with locked exclusions.
6. Reviewed identity-spine promotion helper.
7. Real dark migration execution.
8. This verification closeout.

## Still Dark

Phase 2b-ii-b1 does not wire the new memory into Aetheria's live prompt. Current live recall remains:

```text
AgentLoop -> LatticeStore.find_nodes_by_embedding(...) -> format_recall_context(...) -> ChatMessage(system, recall_context)
```

The two-channel speech assembler from Phase 2b-ii-a is still not imported by `AgentLoop`, startup, or `format_recall_context`.

## b2 Precondition

Phase 2b-ii-b2, the live recall cutover, may start only after this verification document exists, the vnext tree is clean, and the b2 plan treats the cutover as a single isolated wiring change. Rollback for b2 must remain one wiring revert; the b1 Attic migration and identity spine stay intact.

## Sign-Off

Phase 2b-ii-b1 is complete. Prod legacy memory is copied into vnext Attic as raw low-confidence material, the reviewed identity spine exists in vnext lattice, migration and promotion are idempotent, prod source data is unchanged, and Aetheria's live recall voice is still untouched.
