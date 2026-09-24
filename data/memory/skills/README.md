# Citizen procedural skills

Disk-first how-to memory (Hermes-style procedures, house-scoped).

Layout (Kernel Slice A — live):

```
data/memory/skills/<citizen>/_index.md   # tiny index, always in prelude
data/memory/skills/<citizen>/<name>.md   # full body via recall_skill tool
data/memory/skills/_house/               # promoted house craft (later)
```

- Index filename is **`_index.md`** (not `SKILLS.md`) so it cannot be confused with a skill body.
- Empty citizen dirs are fine — no prelude block until `_index.md` exists.
- Skills are procedures, **not** permission grants. Approval Gate still applies.
- Capture / `skill_save` is a later slice — see `docs/designs/2026-08-20-citizen-skill-capture.md`.

Seed example (optional): add lines to `_index.md` and matching `<name>.md`.
