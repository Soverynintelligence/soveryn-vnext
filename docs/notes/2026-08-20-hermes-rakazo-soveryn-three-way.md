# Hermes × Rakazo × SOVERYN — three-way borrow list

**Date:** 2026-08-20  
**Status:** orientation note (not a build plan)  
**Refs:** Hermes Bot Mode / Profiles / Many Gateways / Agent learning loop; [Rakazo](https://github.com/elie222/rakazo) / [rakazo.com self-host](https://rakazo.com/#selfhost); prior [Rakazo steals](2026-08-14-house-health-and-rakazo-steals.md); Automations → CC inbox wire (same day).

## Spine (one sentence each)

| System | Spine |
|--------|--------|
| **Hermes** | Agent OS: profiles, skills, memory, cron, desktop desk + terminal |
| **Rakazo** | Teammate product: bots + sandboxed computers + Markdown routines + approvals |
| **SOVERYN** | Sovereign **house** desk: CoS + citizens + local models + Approval Gate + CC |

Same *shape* (roster, routines, desk, computer/terminal). Different *owner*: house first, citizens as roles — not N rented desktops or N private Hermes homes.

---

## Three-way matrix

| Concern | Borrow from Hermes | Borrow from Rakazo | Keep / twist (ours) |
|---------|--------------------|--------------------|---------------------|
| Identity | Bot = profile; forever Bot Chat | Job bot interviewed into a role | **Citizen** (soul + charter + grants); cast + census, not “create a bot” |
| Isolation | One writer per `HERMES_HOME`; never two processes on one profile | Team vs Private computer | Shared house substrate; **citizen-scoped turns/sessions**; Lattice as shared memory |
| Runtime | Per-profile gateway *or* multiplex | API + worker + computer provider | **One vnext** + specialist systemd daemons (`soveryn-*`) |
| Desk / UI | Bots tab, Active-now, Routines dock, built-in terminal | Live computer view + Take control | **Command Center** as desk; Scotty desk = computer metaphor ([earlier note](2026-08-14-house-health-and-rakazo-steals.md)) |
| Recurring work | Cron `[bot:name] routine` → Bot chat | Routines as **editable Markdown** | **Automations** catalog → live run → **CC inbox**; Signal gated off |
| Autonomy door | Toolsets / policies | Approvals + audit log | **Approval Gate** (fail-safe); automation auto-approve **read-only** tools only |
| Learning | Act → flush → distill skills → reuse; USER.md + MEMORY.md | Memory + saved routines | Souls + Lattice + salience + ActTruth; **gap:** procedural skills + explicit Jon model + flush-before-forget |
| Coordination | Groups, `@mention`, bot DM protocol | CoS template + peer bots / subagents | Aetheria CoS; house_post / delegation; vocabulary: **peer vs subagent vs commission** (locked) |
| Channels | Per-profile bot tokens; token-conflict lock | Integrations via Composio (optional) | House bridges (Signal/Telegram/X); **no double-bind**; local-first delivery |
| Skills registry | Huge community hub | Composio / skill packs | House craft library only — **not** a platform marketplace |
| Models | Multi-provider pin per bot | BYO keys / OpenRouter / local | Fixed house stack (router + local GGUF); per-citizen routing already |
| Ops | `hermes-gateways`, linger, logs per profile | Compose, backups, sandbox idle | `soveryn.target`, journalctl, existing backup timers |

---

## Borrow now (high value, fits bones)

1. **Routines as readable Markdown** (Rakazo) — **shipped 2026-08-20**: `soveryn/automations/routines/<id>.md`, overlay under data root, `GET /api/automations/<id>/routine`, CC **Routine** button.
2. **Held pile / come back when it needs you** (Rakazo) — CC inbox + pending approvals as the held pile; don’t invent a second surface. *(inbox wire live)*
3. **Active-now strip** (Hermes) — who’s mid-turn (chat / automation / heartbeat) without reordering the citizen roster.
4. **Flush-before-forget + skill capture** (Hermes learning loop) — design + **Slice A live**: loader, prelude, `recall_skill` ([design](../designs/2026-08-20-citizen-skill-capture.md)). Capture/`skill_save` still later; seed Eve caption skill when drafts exist.
4b. **ActTruth → bug triage → durable fix** (Rakazo Bug Triage energy) — design + thin queue shipped: [`docs/designs/2026-08-20-acttruth-bug-triage.md`](../designs/2026-08-20-acttruth-bug-triage.md). Lesson streak → CC triage strip; auto-fix not live.
5. **Explicit Jon / USER model** (Hermes) — one deepening surface, not only scattered Lattice hits.
6. **Scotty Take-control** (Rakazo, narrowed) — browser/OAuth or sandboxed shell for Scotty only; not every citizen gets a GUI VM.
7. **Token / channel conflict safety** (Hermes) — refuse double-binding Signal/Telegram tokens across bridges.

## Borrow later

- Forever-chat discipline: `/new` in canonical citizen chat → compact, don’t fork (Hermes).
- `@citizen` composer handoff with validated roster (Hermes).
- Group room with hard caps + `@jon` escalate (Hermes groups × house CoS).
- Citizen clone (`--clone` style): soul + grants + skills, fresh sessions.
- Markdown routine editor UI docked on citizen (Rakazo routines pane energy).

## Explicit non-goals (do not steal)

| From | Non-goal |
|------|----------|
| Hermes | N gateways / N `HERMES_HOME` installs as the architecture; 88k community skill hub; peer-DM across machines as v1 |
| Rakazo | Rewrite in TS/Pi/Composio; every bot gets a Docker/E2B desktop; cloud seats / multi-user control plane; “create a bot” as identity |
| Either | Replacing CoS with a flat peer swarm; Signal live without an explicit arm; automations that hang on Approval Gate for read tools |

---

## Learning-loop gap (Hermes validates; we fill)

Pattern both products converge on:

**soul (who) + skills (how) + memory (what) + user-model (Jon) + flush-before-forget**

| Layer | Ours today | Gap |
|-------|------------|-----|
| Who | Souls, personas, charters | — |
| What | Lattice, salience, continuity, Active Focus | — |
| How | ActTruth / cognition distill (soft) | **Citizen skill files + capture nudge** |
| Jon | Scattered | **Explicit user model** |
| Forget | History budget / elision | **Flush learnings before hard compress** |

---

## North star

**SOVERYN Desk = Hermes Bot Mode energy + Rakazo teammate clarity, on house CoS bones.**

- Desk = Command Center  
- Roster = citizens (not disposable bots)  
- Routines = automations → CC inbox  
- Computer = Scotty station (+ optional jail), not N GUIs  
- Door = Approval Gate  
- Factory = local models + systemd fleet  

When choosing a feature: if it strengthens the **house**, take it; if it turns us into a **bot SaaS**, leave it.
