# Cognition API Report — Phase 4, Task 4.1 (Read Surface)

**Date:** 2026-06-25
**Branch:** feat/continuous-cognition
**Base:** 791f326
**Task:** GET read endpoints for Mission Control "Cognition" view

## Status: COMPLETE

All 5 tests pass. Zero regressions.

## Commit range

791f326..<head> (see `git log --oneline 791f326..HEAD`)

## Test summary

5 passed in 0.42s — new file `tests/test_app_api_cognition_routes.py`

Pre-existing failures: 8 in `tests/test_launcher.py` — confirmed present on
base commit 791f326 before any change. Not introduced by this work.

## What was built

**New file:** `soveryn/app/routes/api_cognition.py`
- Blueprint `api_cognition` with two GET routes.
- `GET /api/cognition/note` → `{"content": str, "id": str|null}` (200).
  Returns `{"content": "", "id": null}` on empty store — never 500.
- `GET /api/cognition/reflections?limit=N` (default 20) → list newest-first,
  each item: `{id, text, scope, citations, jon_originated, created_at}`.
- Same `_state()` / store-accessor / 503-if-store-missing pattern as
  `api_coord.py`. No localhost write-guard (read-only endpoints, matching
  api_coord's GET pattern).

**Edits to `soveryn/app/startup.py`** (3 surgical changes):
1. `cognition_store = None` initialized alongside `coord_store`.
2. `cognition_store = CognitionStore(env.lattice_db)` wired inside the
   `if env.lattice_db.is_file():` block, immediately after `coord_store` is
   constructed — same gate, same placement.
3. `"cognition_store": cognition_store` added to `app.extensions["soveryn"]`.
4. Blueprint registered in `_register_blueprints` immediately after
   `api_coord_bp`.

**New test file:** `tests/test_app_api_cognition_routes.py`
- Fixture mirrors `test_app_api_coord_routes.py` exactly: tmp lattice via
  `LatticeStore(tmp_path)`, build app with injected loops, manually inject
  `CognitionStore(lattice_path)` into `app.extensions["soveryn"]`.
- Tests:
  - `test_note_returns_note_content_and_id` — seed note → 200, correct fields.
  - `test_note_empty_store_returns_empty_not_500` — empty store → 200, nulls.
  - `test_reflections_returns_newest_first_with_fields` — 3 reflections,
    newest-first, all 6 fields present, values correct.
  - `test_reflections_limit_param_truncates` — `?limit=2` returns 2 of 3.
  - `test_reflections_empty_store_returns_empty_list` — empty → `[]`.

## TDD discipline

- Test file written first.
- All 5 tests confirmed RED (404) before any production code was written.
- Production code written; all 5 tests confirmed GREEN (5 passed / 0.42s).
- Full suite run: 2271 passed (2266 pre-existing + 5 new), 8 pre-existing
  launcher failures unchanged.

## Scope fence respected

Control endpoints (revert/purge), diff, and drift-audit were NOT built.
Only the three read surfaces specified for Task 4.1.

## Concerns

None. The `list_reflections()` store method returns oldest-first; the route
reverses in memory before slicing, which is correct for `?limit=N` semantics
(newest N, not oldest N). The store returns all rows; if reflection count
grows very large this will be a scan. For the current use case (periodic deep
cycles, bounded note size) this is not a problem — a future task can push
`LIMIT` into the SQL query if needed.
