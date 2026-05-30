# Phase 3b Ares Baseline

Phase 3b starts from a clean vnext tree and extends the Phase 3a Ares daemon with network and architecture lanes.

## Captured State

- Date: 2026-05-30
- Baseline HEAD: `f524a6a tune(aetheria): bound Qwen reasoning budget per request`
- Recent commits:
  - `f524a6a tune(aetheria): bound Qwen reasoning budget per request`
  - `b76b4a9 fix(2b-ii-b2): transport adapter for Qwen3.6 multi-system drop`
  - `b4a86b9 docs(2b-ii-b2): record canonical env.lattice_db path + forensics commands`
- Working tree: clean

## Baseline Checks

```text
$ /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q
809 passed in 5.81s
```

```text
$ /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_ares_readiness.py -q
1 passed in 0.03s
```

## Drift Rule

If any Phase 3b checkpoint reports a different test count, unexpected failure, dirty tree, or HEAD drift not explained by the current task commit, stop and reconcile before proceeding.
