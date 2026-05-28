# Phase 3a Ares Baseline

**Date:** 2026-05-29
**Plan:** `~/soveryn_complete/docs/superpowers/plans/2026-05-29-soveryn-rebuild-phase3a-ares-core-hardware.md`
**Repo:** `~/soveryn_vnext`

## Gate State

- Expected baseline HEAD: `8b5a979 docs: close Phase 2 Ares prerequisites`
- Observed HEAD: `8b5a979`
- `git status --short`: empty
- Phase 3a plan file exists in `~/soveryn_complete` and is untracked there, consistent with prior planning docs.

## Test Commands

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q
```

Result:

```text
653 passed in 4.89s
```

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_ares_readiness.py -q
```

Result:

```text
1 passed in 0.03s
```

The suite emits the existing `RequestsDependencyWarning`; it is non-fatal and unchanged from Phase 2.

## Current Ares Surface

`soveryn/agents/ares/daemon.py` is still the Phase 1/2 honest stub:

- `AresFinding(finding_type, severity, evidence)` exists in `daemon.py`.
- `AresDaemonSurface.agent_name == "ares"`.
- `AresDaemonSurface.uses_llm == False`.
- `scan_once()` raises `AresDaemonNotPortedError`.

Task 2 may begin from a clean, green baseline.
