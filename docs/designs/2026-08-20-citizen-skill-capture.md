# Citizen skill capture — design

**Date:** 2026-08-20  
**Status:** Slice A **live** (loader + prelude + `recall_skill`). Capture / `skill_save` not built.  
**Parents:** [Hermes × Rakazo × SOVERYN three-way](../notes/2026-08-20-hermes-rakazo-soveryn-three-way.md), Hermes learning loop  

### Slice A landed (Kernel + finish pass)

| Piece | Where |
|-------|--------|
| Loader | `soveryn/agents/skills.py` — `get_skill_index`, `load_skill` |
| Tool | `soveryn/agents/recall_skill_tool.py` — owner-scoped `recall_skill` |
| Prelude | `AgentLoop._build_skills_index` — labeled `[PROCEDURAL SKILLS]` block, ~8k char soft cap |
| Config | `EnvConfig.skills_dir` → `data/memory/skills/` |
| Tests | `tests/test_skills.py` |

## Goal

Add **procedural memory** (how we do X here) on top of souls (who) and Lattice (what), without becoming a community skill marketplace.

Pattern: **soul + skills + memory + Jon-model + flush-before-forget**.

## File layout

```
data/memory/skills/
  aetheria/
    _index.md              # tiny index (always in prelude when present)
    cwg-brief-lead.md      # example skill body
  vett/
    _index.md
    verify-before-claim.md
  scotty/
    _index.md
  eve/
    _index.md
    cwg-caption-style.md   # Eve owns compose craft first
  kernel/
    _index.md
  _house/                  # promoted only — material house procedures
    _index.md
```

**Index filename is `_index.md`** (Kernel’s choice — kept). Not `SKILLS.md`, so the index cannot be loaded as a skill body by mistake.

Package may ship **seed** skills under `soveryn/agents/<citizen>/skills/` later; Jon/runtime writes land in `data/memory/skills/`.

### Skill file shape (Markdown)

```markdown
# <Title>

- id: kebab-case
- owner: eve | aetheria | vett | scotty | kernel | house
- when: one line trigger
- gated_tools: list (informational — never a grant)

## Procedure
1. …
2. …

## Verify
- …

## Notes
Edge cases learned in use.
```

## Capture trigger (nudge-driven)

After a turn that looks “skill-worthy”, nudge the citizen (system note / tool), don’t wait for Jon:

| Signal | Example |
|--------|---------|
| Multi-step tool success that Jon affirmed | Eve caption draft accepted |
| Repeated pattern (≥2 similar wins) | Same verify checklist |
| Explicit ask | “save that as a skill” |
| Automation verify pass with a reusable how | Morning brief lead formula |

**Not** every turn. Cap: at most one capture proposal per citizen per hour unless Jon asks.

Capture flow:

1. Citizen drafts skill markdown (or updates existing).
2. Writes under `data/memory/skills/<owner>/` via a **house-local** tool (`skill_save`) — not egress; no Approval Gate.
3. Updates that citizen’s `SKILLS.md` index.
4. Optional: propose promote-to-`_house/` (needs Jon yes or CoS rule).

## Prompt injection

At turn start (with persona/soul/recall):

1. Load `_index.md` for the citizen (soft-capped ~8k chars ≈ 2k tokens).
2. Wrap as `[PROCEDURAL SKILLS] … [/PROCEDURAL SKILLS]` and tell the model to call `recall_skill`.
3. Full bodies load **on demand** via `recall_skill` (better than stuffing 0–3 bodies every turn).

House-promoted skills (`_house/`) may appear for any citizen later; owner skills always preferred today.

## Permissions (non-negotiable)

- Skills are **procedures, not grants**.
- `gated_tools:` in a skill never bypasses Approval Gate.
- Automation read-tool auto-approve stays separate (`source=automation`).

## Flush-before-forget

When history budget / compression would drop middle turns:

1. Run a cheap “anything reusable?” check (or pending skill draft flush).
2. Persist skill / USER / Lattice notes **first**.
3. Then compress.

Do not invent a second compressor until this invariant is wired beside the existing history budgeter.

## Jon / USER model (companion)

Parallel thin file: `data/memory/user/JON.md` (preferences, cadence, voice).  
Updated on explicit signal or rare distill — not every chat. Skills may reference it (“Jon’s caption bar”) but don’t fork identity into skills.

## First concrete skill candidates

1. **Eve — CWG caption style** (after real pond→GPU drafts land)
2. **Vett — verify-before-claim** checklist
3. **Aetheria — morning brief lead formula** (from automations routine verify)

## Implementation slices (later)

| Slice | Deliverable |
|-------|-------------|
| A | dirs + `skill_save` / `skill_list` tools + index load in AgentLoop prelude |
| B | capture nudge after affirmed multi-step turns |
| C | flush-before-elision hook in history budget path |
| D | CC “Skills” fold per citizen (read-only first) |

## Non-goals

- agentskills.io / 88k registry
- Skills that grant egress
- Auto-promote to `_house/` without a bar
- Replacing Lattice facts with skill files

## Done when (for v1 of this design)

- Eve can save and reload one caption skill across sessions
- Skill text never disables Approval Gate
- Capture is nudged, not mandatory spam
