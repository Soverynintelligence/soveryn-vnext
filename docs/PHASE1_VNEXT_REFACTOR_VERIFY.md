# Phase 1 vnext Refactor Verify

**Date:** 2026-05-27
**Plan:** `~/soveryn_complete/docs/superpowers/plans/2026-05-27-soveryn-rebuild-phase1-vnext-refactor.md`
**Implementation repo:** `~/soveryn_vnext`

## Result

Phase 1 is implemented against `~/soveryn_vnext`, not a fresh `~/soveryn/` repo.

The refactor created the platform/agents split while preserving existing behavior through compatibility imports. No production cutover happened. No Ares, Vett, Scotty repair/research/daemon behavior was ported. No Flask route was wired through the new bus.

## Final Test Command

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest
```

Expected final result after Task 10:

```text
631 passed in 4.61s
```

The suite may emit the existing `RequestsDependencyWarning` before collection; it is non-fatal.

## Package Snapshot

```text
soveryn/
├── agents/
│   ├── aetheria/
│   │   ├── chat_surface.py
│   │   ├── heartbeat_surface.py
│   │   ├── persona.py
│   │   └── recall_policy.py
│   ├── ares/
│   │   └── daemon.py
│   ├── scotty/
│   │   └── repair_surface.py
│   ├── vett/
│   │   └── research_surface.py
│   ├── loop.py
│   ├── personas.py
│   ├── recall.py
│   ├── registry.py
│   └── souls.py
├── app/
├── backup/
├── config/
├── inference/
├── memory/
├── platform/
│   ├── bus/
│   │   ├── events.py
│   │   ├── memory.py
│   │   └── sqlite.py
│   ├── inference/
│   │   ├── health.py
│   │   ├── llama_server_client.py
│   │   └── routing.py
│   ├── lattice/
│   │   ├── attic.py
│   │   ├── legacy.py
│   │   └── types.py
│   ├── repair/
│   │   ├── recipes.py
│   │   └── recipes/
│   │       ├── README.md
│   │       └── repair_restart_aetheria_chat_surface.yaml
│   ├── supervisor/
│   │   └── health.py
│   ├── telemetry/
│   │   └── events.py
│   └── tools/
│       └── registry.py
├── tools/
└── validation/
```

## Compatibility Imports

Kept for Phase 1 so existing app/routes/tests keep resolving while internals move:

| Old path | Target | Planned removal |
|---|---|---|
| `soveryn.inference.health` | `soveryn.platform.inference.health` | After Phase 2 callers are migrated |
| `soveryn.inference.llama_server_client` | `soveryn.platform.inference.llama_server_client` | After Phase 2 callers are migrated |
| `soveryn.inference.routing` | `soveryn.platform.inference.routing` | After Phase 2 callers are migrated |
| `soveryn.memory.lattice` | `soveryn.platform.lattice.legacy` | After memory rewrite adapter consumers migrate |
| `soveryn.tools.registry` | `soveryn.platform.tools.registry` | After tool registry callers migrate |
| `soveryn.agents.recall` | `soveryn.agents.aetheria.recall_policy` | After agent package imports are migrated |
| `soveryn.agents.personas.AETHERIA_PERSONA` | `soveryn.agents.aetheria.persona.AETHERIA_PERSONA` | Keep until shared persona registry is split or retired |

## Task Checklist

- Task 1: Baseline captured and dirty router-cutover work classified.
- Task 2: Platform package skeleton added.
- Task 3: Inference moved behind compatibility shims.
- Task 4: Tool registry moved behind compatibility shim.
- Task 5: Lattice mechanism split from memory shim; Entry/Region/Attic declared.
- Task 6: Event bus interface added; no app wiring.
- Task 7: Aetheria package and chat/heartbeat surfaces added.
- Task 8: Ares/Vett/Scotty contracts added; no behavior ported.
- Task 9: Supervisor, telemetry, and repair recipe skeletons added.
- Task 10: README and this verify document added.

## Commit Trail

```text
e7551a1 platform: add supervisor telemetry repair skeletons
73b2b23 agents: declare Ares Vett Scotty package contracts
1a141f3 agents: lift Aetheria policy into explicit surfaces
78e6116 platform: add event bus interface
a6baa8a platform: split lattice mechanism from memory shim
e284e34 platform: move tool registry behind compatibility shim
2f55757 platform: move inference behind compatibility shims
6ddd1ca platform: add Phase 1 package skeleton
313cf49 docs: record Phase 1 vnext refactor baseline
9b1b1b3 routing: route vnext models through llama router aliases
```

## Explicit Non-Claims

- Phase 1 does not cut over production.
- Phase 1 does not port Ares daemon behavior.
- Phase 1 does not implement Scotty repair execution.
- Phase 1 does not populate Attic or finalize region taxonomy.
- Phase 1 does not wire Flask or agents through the new bus.
- Phase 1 does not remove compatibility imports.
