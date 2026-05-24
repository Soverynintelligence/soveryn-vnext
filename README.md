# SOVERYN vNext

Clean rebuild of SOVERYN — the local multi-agent system. Built beside the running production instance, not in place of it.

**Source of authority:** `docs/CURRENT_TRUTH_2026-05-23.md`. Every design decision traces back to that spec.

## Status

vNext is scaffolded. No behavior is ported yet. The first commit establishes:
- Directory skeleton
- `soveryn.config.runtime` — single source of truth for agent identity and routing
- `soveryn.agents.registry` — registration that rejects retired names by construction
- Test scaffolding (pytest)

Future commits will fill in inference routing, Lattice memory, tool registry, and the Flask app surface — each TDD'd against the spec.

## Layout

See `docs/CURRENT_TRUTH_2026-05-23.md` §13 for the rationale behind the package split.

## Running tests

```bash
pip install -e .
pip install pytest
pytest
```
