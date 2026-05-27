# Phase 1 vnext Refactor Baseline

**Date:** 2026-05-27
**Plan:** `~/soveryn_complete/docs/superpowers/plans/2026-05-27-soveryn-rebuild-phase1-vnext-refactor.md`
**Task:** 1 - Freeze baseline and classify dirty work
**Git HEAD:** `9ad8eff docs: track validation defects log from 2026-05-24 UI pass`

## Test Baseline

Command:

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest
```

Result:

```text
594 passed in 4.44s
```

Note: pytest emitted a `RequestsDependencyWarning` about `urllib3` / `chardet` / `charset_normalizer` version compatibility before the test run. It did not fail the suite.

## Dirty Worktree Classification

All dirty tracked files are part of the router-cutover arc. They are active changes, not unrelated edits.

| File | Status | Classification | Notes |
|---|---:|---|---|
| `soveryn/agents/loop.py` | modified | router-cutover active change | `AgentLoop` now sends `self.server.model_alias` in chat requests instead of the logical server name. |
| `soveryn/config/runtime.py` | modified | router-cutover active change | `MODEL_SERVERS` now share router port `8090`; `ModelServer.model_alias` identifies router presets; validation allows shared model-server port while still blocking service/app collisions. |
| `soveryn/inference/llama_server_client.py` | modified | router-cutover active change | Embeddings request uses the embeddings server `model_alias` so router dispatches to the embeddings preset. |
| `tests/test_agent_loop.py` | modified | router-cutover active change | Tests assert logical server identity and router alias instead of old per-agent ports. |
| `tests/test_llama_server_client.py` | modified | router-cutover active change | Tests expect router alias payloads and `:8090` embeddings route. |
| `tests/test_routing.py` | modified | router-cutover active change | Tests assert agent-to-alias routing instead of old port routing. |
| `tests/test_runtime_config.py` | modified | router-cutover active change | Tests encode router-mode port and alias invariants. |

Diff size at baseline:

```text
7 files changed, 153 insertions(+), 68 deletions(-)
```

## Backup/Cruft File Classification

These files are untracked backup snapshots from the router-cutover work. They are not runtime inputs and should not be imported by the app or tests.

| File | Classification | Decision |
|---|---|---|
| `soveryn/agents/loop.py.before-router-cutover` | router-cutover backup cruft | Preserve until router-cutover active changes are committed; then remove or archive in a dedicated cleanup commit. |
| `soveryn/config/runtime.py.before-router-cutover` | router-cutover backup cruft | Preserve until router-cutover active changes are committed; then remove or archive in a dedicated cleanup commit. |
| `soveryn/inference/llama_server_client.py.before-router-cutover` | router-cutover backup cruft | Preserve until router-cutover active changes are committed; then remove or archive in a dedicated cleanup commit. |
| `tests/test_agent_loop.py.before-router-cutover` | router-cutover backup cruft | Preserve until router-cutover active changes are committed; then remove or archive in a dedicated cleanup commit. |
| `tests/test_health.py.before-router-cutover` | router-cutover backup cruft | Preserve until router-cutover active changes are committed; then remove or archive in a dedicated cleanup commit. |
| `tests/test_llama_server_client.py.before-router-cutover` | router-cutover backup cruft | Preserve until router-cutover active changes are committed; then remove or archive in a dedicated cleanup commit. |
| `tests/test_routing.py.before-router-cutover` | router-cutover backup cruft | Preserve until router-cutover active changes are committed; then remove or archive in a dedicated cleanup commit. |
| `tests/test_runtime_config.py.before-router-cutover` | router-cutover backup cruft | Preserve until router-cutover active changes are committed; then remove or archive in a dedicated cleanup commit. |

## Gate Decision

Task 1 baseline is green.

Proceeding to structural refactor is allowed only after deciding whether to first commit the router-cutover active changes. The safest next step is to commit the green router-cutover cluster before Task 2 so Phase 1 platform refactor does not mix architecture moves with pending router behavior changes.

