# Repair Recipes

Repair recipes are human-authored, bounded instructions for Scotty's future repair surface. Phase 1 only validates recipe metadata. No recipe is executable yet.

## Tiers

- Tier A: autonomous low-risk operations such as service restarts, cache flushes, and stale-lock cleanup.
- Tier B: bounded system maintenance such as config repairs, dependency reinstall, or log rotation under pressure. Aetheria should be able to observe and flag these.
- Tier C: schema migrations, data writes, or anything touching Aetheria's memory substrate. Requires Aetheria endorsement or Jon approval before execution.

Scotty cannot author new recipes. New recipes are written and reviewed by Jon or a reviewed agent session, then registered by hand.
