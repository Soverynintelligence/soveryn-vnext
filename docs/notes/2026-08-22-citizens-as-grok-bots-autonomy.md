# Citizens as Grok bots — autonomy spine (assign → execute → verify)

**Date:** 2026-08-22  
**Status:** building — thin slice in progress  
**Owner intent:** SOVERYN citizens *are* Jon’s Grok bots. They must earn their keep on **CWG / PondWright**, **History’s Ledger (HL)**, and **SOVERYN** — not only win one-shot chat deals.

**Locked feeling (from Jon):**

> I don’t want to sit inside a chat writing another prompt every 5 minutes.  
> I want to define the objective, give the agent access to the right tools and data, let it execute, then step back in when judgment or approval is actually needed.  
> **assign → execute → verify** — once AI stops waiting for your next message, it stops feeling like software you use and starts feeling like work you delegated.

---

## 1. Diagnosis — why they feel one-shot today

The house already has Grok-*shaped* UX (Messages, peer icon → group, CoS summary relay, Gate). The **work substrate** is still chat-turn shaped.

| Layer | What exists | Why it fails autonomy |
|-------|-------------|------------------------|
| **Commission** | `queued → running → done` one body string | One `AgentLoop.process_message` — not a multi-hour objective. No resume, no phases, no “still working overnight.” |
| **Tool budget** | `max_tool_rounds` (Vett up to **16** in startup) | Research hits “tool budget exhaustion” and stops — PondWright-grade pricing needs longer dig + page fetches. |
| **GPU / busy** | Charter §8 single slot; `interactive_busy` | Parallel “3 jobs for 24h” collides with live chat; stale `running` zombies block the queue. |
| **Desks** | `~/soveryn_citizens/{id}/{inbox,outbox,work,notes}` | Per-**citizen**, not per-**business**. No CWG/HL/SOVERYN standing work folders or owners. |
| **Automations** | morning brief, digests, weekend deep dive | Scheduled **one-shots** into CC inbox — useful, but not lasting objectives. |
| **Long harness** | Kernel + **OpenCode** (`soveryn-opencode`, Qwen/Flash) | Proves long-run **is** possible in the house — but only for coding. Vett research still uses short AgentLoop commissions. |
| **CoS close-loop** | `[COS_RELAY]` summarize → Jon DM | Right *shape* for verify; still wraps one-shot peer work. |

**Vocabulary already locked** (`docs/notes/2026-08-14-house-health-and-rakazo-steals.md`):

| Kind | Standing | Survives turn? |
|------|----------|----------------|
| peer | founding citizen + desk | yes |
| subagent | ephemeral | no |
| commission | work item → outbox | until done/failed |

**Missing kind (this plan adds):** **objective** — standing, multi-step, business-scoped work that *spawns* commissions / harness runs until verify.

**Concrete evidence (today):** fountain maintenance pricing commission finished with “no published plans / tool budget exhaustion.” Aetheria correctly summarized the *gap*. That is CoS honesty — not Grok-bot depth. The harness quit early; PondWright didn’t.

---

## 2. Target — citizens earn their keep

### Business desks (first-class)

| Desk | Business | Standing work examples |
|------|----------|------------------------|
| **CWG** | Carolina Water Gardens / PondWright | Quotes, CRM hygiene, product/pricing research, competitor watch, estimator assist |
| **HL** | History’s Ledger | Corpus gaps, Atticus verify, site copy, Modern Wars intake |
| **SOVERYN** | House / product / ops | Spine health, ActTruth, fleet, NSF/pitch, citizen duties |

### Role map (draft — adjust when building)

| Citizen | Primary desk(s) | Harness |
|---------|-----------------|---------|
| **Aetheria** | All (CoS) | Assign objectives, summarize, Gate, deliver to Jon |
| **Vett** | CWG research + HL verify | Long research runner (not 16-round chat) |
| **Eve** | SOVERYN + CWG presence | Drafts, social, competitor narrative |
| **Kernel** | SOVERYN (+ HL site/code) | OpenCode long-run (already) |
| **Scotty** | SOVERYN ops / repair | Commission + desk worker (already) |

### Success criteria (overnight proof)

1. Jon assigns **one objective** (e.g. “CWG: maintenance-plan pricing brief across named platforms”).  
2. Leaves for hours.  
3. Returns to: progress trail + brief or honest gaps + Gate only if write egress needed.  
4. No “prompt every 5 minutes.”

---

## 3. Recommended spine

**Both layers** (objectives + long harness) — not more chat polish.

```
Jon / Aetheria
    │  assign objective (desk=CWG|HL|SOVERYN, owner=peer, success criteria)
    ▼
objectives store (standing, resumable)
    │  spawns work units over time
    ├─► commission (short)     — for bounded tasks
    ├─► research runner        — Vett multi-wave search/fetch (OpenCode-like loop or raised budget + checkpoints)
    └─► OpenCode run           — Kernel (already)
    ▼
checkpoints → desk/work/{objective_id}/
    ▼
CoS summarize → Jon DM / Signal / group   (verify)
    ▼
Gate only on real egress (email/X/messenger) — web stays ungated
```

### Why not “just raise max_tool_rounds to 64”?

Helps one-shot depth; **does not** give standing jobs, parallel business paths, resume after restart, or overnight progress. Treat higher rounds as a **tactical** patch inside a research-runner wave — not the architecture.

### Why OpenCode-shaped runners matter

Kernel already shows: long autonomy needs a **harness that expects many steps**, workspace persistence, and auto-approve within a fence — not a single chat completion. Vett’s research needs the same *class* of harness (waves + checkpoints + cite-or-stop), even if the binary isn’t OpenCode.

---

## 4. Implementation plan (phased)

### Phase 0 — Diagnosis artifact (this plan) ✅

Park north-star note in `docs/notes/` when building starts (copy of this diagnosis).

### Phase 1 — Objectives v0 (spine)

**Goal:** Standing work objects that outlive one LLM call.

| Piece | Detail |
|-------|--------|
| Store | SQLite `objectives` (or extend citizens.db): `id, desk, owner_id, title, brief, success_criteria, state (active\|blocked\|done\|failed), checkpoint_path, created_at, updated_at` |
| API | `POST /api/objectives`, list by desk, attach progress |
| CoS | Aetheria tool `objective_assign` / `objective_status` (or house_post kind) |
| UI | CC or Messages: “Active work” strip — not Mission Control first |
| Checkpoint | `~/soveryn_citizens/{owner}/work/objectives/{id}/` notes + partial brief |

**Exit:** Jon can assign “CWG: fountain maintenance pricing” and see it still `active` after a restart.

### Phase 2 — Research runner v0 (Vett)

**Goal:** Replace “one commission = one AgentLoop until budget dies” for research objectives.

| Choice | v0 recommendation |
|--------|-------------------|
| Shape | **Wave runner**: N search/fetch waves with checkpoint after each; stop on cite-or-stop or success criteria |
| Budget | Per-wave tool rounds (e.g. 12) × waves (e.g. 5–10), not one flat 16 |
| Persistence | Write partial tables to desk/work; resume wave index on reclaim |
| Stale running | Heartbeat requeue if `running` > threshold (fix zombie blocks) |
| Prompt | PondWright bar: Brand \| Model \| Price \| Source URL; multi-platform; fetch pages |

**Exit:** Re-run maintenance pricing overnight; brief has **specific sourced numbers** or an honest “local contractor only” with attempted sources listed.

### Phase 3 — CoS verify loop (Aetheria)

Already started (`[COS_RELAY]`). Extend:

| Piece | Detail |
|-------|--------|
| Trigger | Objective checkpoint or research-runner “ready for CoS” |
| Output | Decision brief to Jon DM + optional Signal |
| Autonomy | Propose next wave / close objective — Jon verifies |
| Parallel | Multiple objectives active across desks without forcing one chat |

### Phase 4 — Business desk wiring

| Desk | Thin standing objectives (examples) |
|------|--------------------------------------|
| CWG | Weekly competitor/pricing watch; CRM stale leads; estimator assist notes |
| HL | Corpus gap list; Atticus verify queue; site changelog draft |
| SOVERYN | House health digests; spine debt; pitch/NSF scraps |

Map Eve/Scotty/Kernel duties onto desks (extend `citizens/duties.py` + census notes).

### Phase 5 — Compute layout (don’t pretend)

| Constraint | Plan |
|------------|------|
| Single Blackwell for chat | Research runner prefers **non-interactive** hours or Spark lane if available |
| `interactive_busy` | Keep for chat GPU; **do not** mark coordination/commission as `direct` busy |
| Parallel Grok-style jobs | Cap concurrent long runners (1 research + 1 OpenCode) until multi-GPU policy is explicit |

---

## 5. Thin slice to prove (first build after plan approval)

**One objective, one desk, one overnight:**

1. Add `objectives` table + assign/list API + desk folder.  
2. Vett research-runner v0 (waves + checkpoints) for **CWG: pond/fountain maintenance & service pricing across named platforms**.  
3. CoS summary → Jon DM when status = `ready_for_verify`.  
4. Stale-`running` requeue so zombies can’t idle the queue.  

**Non-goals for this slice:** native phone app, Grok-style animated mascots, Docker-per-bot, Composio, rewriting in TS.

---

## 6. Relation to what we already shipped (keep)

- Messages 1:1 vs group-on-collab  
- Multi-peer rooms + shared transcript  
- Web search ungated; write egress gated  
- CoS relay / summarize path  

These are the **door**. Objectives + long harness are the **workforce**.

---

## 7. Open decisions (resolve at build start)

1. Research runner = custom wave loop in `soveryn/citizens/` **vs** thin OpenCode agent profile for Vett?  
2. Objectives live in `citizens.db` **vs** new `objectives.db` under data/?  
3. First overnight objective owner: Vett-only under Aetheria assign, or Jon assigns via UI?

**Recommendation:** custom wave runner (less OpenCode ceremony for web research); `citizens.db` table; Jon assigns via Aetheria chat tool + optional CC list for v0.

---

## 8. Done when

Jon can say: *“These are my Grok bots — they work CWG, HL, and SOVERYN while I’m gone, and I only show up to verify.”*  
Proven by one real overnight CWG research objective that beats today’s thin maintenance pass.
