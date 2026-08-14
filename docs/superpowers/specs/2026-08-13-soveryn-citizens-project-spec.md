# SOVERYN Citizens — Full Project Specification

| Field | Value |
|-------|-------|
| **Status** | Draft — full project spec |
| **Date** | 2026-08-13 |
| **Owner** | Jon DeOliveira / Soveryn Intelligence LLC |
| **Codename** | **SOVERYN Citizens** |
| **One-liner** | Named, local, always-resident AI with identity, memory, and duty — on hardware we own. |
| **Charter** | `docs/superpowers/specs/2026-08-13-soveryn-citizens-charter.md` |
| **Hardware map** | `docs/runtime-config/ALWAYS_ON_SOVERYN_MODEL_MAP.md` |
| **Memory law** | `docs/superpowers/specs/2026-08-11-memory-grades-self-through-memory-design.md` |
| **Slop / debt** | `docs/notes/2026-08-11-soveryn-vnext-slop-inventory.md` |

---

## 0. Executive summary

### Problem

Most “AI agents” are either:

- **Rental** — cloud sessions with no residence, no durable self, data egress; or  
- **Scripts** — cron jobs with no identity, no memory discipline, no standing; or  
- **Chat UIs** — only work when a human is in the window.

SOVERYN already runs a **local multi-agent fleet** (vNext, models, daemons, lattice, Signal). What it lacks is a **product-shaped layer**: one concept for “who lives here,” desks, duties, commissions, and status — without depending on any cloud agent product (including xAI Grok Bot).

### Solution

**SOVERYN Citizens** is that layer:

- **Local only** by default (tower + Spark).  
- **Citizens** = named identities with soul, residence, workspace, tools, duties.  
- **Always-on** models and processes under systemd / Spark services.  
- **Commissions** = work queue (not only free-form chat).  
- **Memory grades** = self without multi-minute “hi.”  
- **Human surface** = console + Signal/messenger under restraint.

### Non-goals (project)

- Legal personhood or “employee” claims  
- Multi-tenant SaaS “rent a citizen” v1  
- Replacing vNext with a greenfield monorepo  
- Depending on Grok Bot / cloud always-on agent platforms  
- **Any inbound or outbound bot control plane** (external create/schedule/command of citizens; phone-home to bot SaaS)  
- Training foundation models from scratch  

### Network sovereignty (binding)

Jon’s law (2026-08-13):

> **No calls in from corporate America. No bots calling home.**

| | |
|--|--|
| **No calls in from corporate America** | No inbound control from US (or any) corporate cloud — no remote create/schedule/command/license of Citizens. Not a managed agent fleet endpoint for OpenAI, Google, Microsoft, Meta, xAI, Amazon, etc. |
| **No bots calling home** | No telemetry, usage beacons, identity pings, or agent-fleet sync outbound to vendors. Citizens do not phone home. |
| **House network OK** | 127.0.0.1, tower↔Spark, local disks. Signal/messenger **to Jon** = human report, not corporate call-home. |
| **Research tools ≠ control plane** | Allowlisted search/fetch for *content* only — not vendor C2. Prefer house SearXNG. |
| **Default** | Zero cloud model/contractor calls unless Jon explicitly grants. |

**Correct:** sovereign local SOVERYN. **Incorrect:** hybrid “local brains, cloud bot OS.”

### Data sovereignty (binding)

Jon’s law:

> **My data is my data.**

| | |
|--|--|
| **Owner** | Jon / the house — not the model vendor, not the Citizen, not a cloud platform |
| **Default location** | Local disks and house network only |
| **No silent training** | House data never becomes someone else’s training corpus by default |
| **No siphon** | No background upload of chats, lattices, files, or embeddings to corporate America |
| **Egress** | Only when Jon acts (send, export, publish) or explicitly grants a scoped contractor |
| **Citizens** | Stewards in trust — they use data to serve the house; they do not own or exfiltrate it |

Pairs with network law: no corporate dial-in, no bots calling home, **and** no quietly taking the goods.

---

## 1. Product definition

### 1.1 What we are selling / showing

| Audience | Promise |
|----------|---------|
| **Jon (internal)** | A house of resident intelligences that work while he sleeps, remember with discipline, and report what matters |
| **External (market)** | Local AI that won’t invent critical facts, runs on your hardware, with persistent agents for real jobs |
| **Tagline (brand)** | *AI that won’t invent the facts. On hardware you own.* |
| **Tagline (Citizens)** | *Local AI citizens. They live here. They remember. They work.* |

### 1.2 Marketable offers that use this project

Citizens is the **operating system for the house**. Cash offers ride on top:

| Offer | How Citizens helps |
|-------|-------------------|
| Shepherd pilot | Compliance citizen/persona + cite engines + local residence |
| Local truth-AI pilot | Deploy a citizen-class stack on customer-controlled hardware |
| PondWright / products | Vertical apps as *services*; Citizens remain house infrastructure |

v1 of this **project** is **house infrastructure + internal readiness**. Customer packaging is a later productization pass.

### 1.3 Success looks like

| Horizon | Success |
|---------|---------|
| **v0.1** | Three citizens registered; workspaces exist; status API lists them; Aetheria still chats |
| **v0.2** | Commissions queue; at least one scheduled duty runs as a commission; result in outbox |
| **v0.3** | Heartbeat uses commission path; console shows resident / on_duty / blocked |
| **v1.0** | Memory write distill for always-on writers; no cloud dependency; demoable “house of citizens” in 5 minutes |

---

## 2. Principles (binding)

1. **Local first** — no cloud citizenship by default.  
2. **No calls in from corporate America; no bots calling home** — sovereign.  
3. **My data is my data** — house owns it; citizens steward; no silent vendor training or siphon.  
4. **Residence before cleverness** — healthy models and units beat new features.  
5. **Identity is law** — soul + name + registry; not anonymous weight files.  
6. **Memory creates self; volume is not self** — Memory Grades apply.  
7. **Honesty over helpfulness** — refuse / cite rather than invent.  
8. **Restraint** — Jon’s attention is finite.  
9. **Aetheria’s GPU is sovereign** — Blackwell never co-tenanted.  
10. **Quadros are an NVLink pair** — multi-GPU helpers only within the pair; never split Blackwell↔Quadro.  
11. **systemd is process law** — citizens-runtime does not replace init.  
12. **Amendments by Jon** — charter and this spec are house law.

---

## 3. Polity and roster

### 3.1 Roles

| Role | Examples |
|------|----------|
| Founder | Jon |
| Citizens | Aetheria, Vett, Scotty |
| Sentinels | Ares |
| Utilities | routers, embed, SearXNG, ComfyUI |
| Contractors | Optional remote APIs (explicit grant only) |

### 3.2 Founding citizens (v1 roster)

| Citizen | Inference residence | Soul | Primary duties |
|---------|---------------------|------|----------------|
| **aetheria** | Blackwell router `:8090` / alias `aetheria` | `souls/aetheria.md` (+ origin tool) | Chat, heartbeat, Signal, coordination, surface material truth |
| **vett** | Spark `10.10.10.2:8000` / `laguna` | `souls/vett.md` | Research, patrol, verification |
| **scotty** | Spark shared Laguna | `souls/scotty.md` | Repair, delegation, bounded execution |

Full rights/duties/admission rules: **Citizens Charter**.

---

## 4. System architecture

### 4.1 Context diagram

```text
                    ┌──────────────────────────────────┐
                    │  Jon                             │
                    │  chat · Signal · messenger · UI  │
                    └────────────────┬─────────────────┘
                                     │
                    ┌────────────────▼─────────────────┐
                    │  vNext (:5001)                   │
                    │  AgentLoops · tools · routes     │
                    │  Citizens API · commissions API  │
                    └─────┬───────────┬───────────┬────┘
                          │           │           │
           ┌──────────────┘           │           └──────────────┐
           ▼                          ▼                          ▼
    ┌─────────────┐          ┌──────────────┐          ┌─────────────────┐
    │ Citizens    │          │ Lattice ·    │          │ Model residences│
    │ registry ·  │          │ souls ·      │          │ Blackwell/Spark │
    │ commissions │          │ workspaces   │          │ Quadros/embed   │
    │ runtime     │          │              │          │                 │
    └─────────────┘          └──────────────┘          └─────────────────┘
           │
           ▼
    systemd units (heartbeat, dream, patrol, …)
```

### 4.2 Existing substrate (do not rewrite)

| Component | Path / port | Role in Citizens |
|-----------|-------------|------------------|
| vNext app | `soveryn-vnext.service` :5001 | Chat, tools, new Citizens HTTP API |
| AgentLoop | `soveryn/agents/loop.py` | Citizen brain turn |
| Tool registry | `soveryn/platform/tools` | Duty capability |
| Lattice | `lattice_vnext.db` | Long-term memory |
| Souls | `data/memory/souls/` | Identity law |
| Conversations | `conversations_vnext.db` | Episodic transcript |
| Routers | :8090 / :8091 | Local llama.cpp |
| Spark vLLM | 10.10.10.2:8000 | Workers |
| Embeddings | :8096 | Librarian |
| Heartbeat / dream / patrol | user systemd | Become **duties** over time |
| Signal bridge | systemd | Citizen voice out |

### 4.3 New components (this project)

| Component | Responsibility |
|-----------|----------------|
| **Citizens registry** | Who is a citizen; status; workspace; model_server |
| **Duties table** | Scheduled / continuous obligations |
| **Commissions queue** | Discrete work items |
| **Citizens runtime** | Drain commissions (thread in vnext or separate unit) |
| **Workspaces** | Per-citizen disk desk |
| **Citizens status API** | Machine-readable board |
| **Citizens console UI** | Human-readable board (minimal v1) |

---

## 5. Data model

### 5.1 Storage location

- DB: `data/citizens.db` (under `SOVERYN` data root / `env.data_root`)  
- Workspaces: `~/soveryn_citizens/<citizen_id>/` (configurable via env `SOVERYN_CITIZENS_ROOT`)

### 5.2 Schema (v1)

```sql
-- citizens.db

CREATE TABLE citizens (
  id              TEXT PRIMARY KEY,          -- aetheria | vett | scotty
  display_name    TEXT NOT NULL,
  soul_path       TEXT,                      -- relative or absolute
  model_server    TEXT NOT NULL,             -- runtime.py ModelServer.name
  workspace_path  TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'offline',
    -- resident | on_duty | blocked | offline | retired
  last_seen_at    TEXT,
  last_error      TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  notes           TEXT
);

CREATE TABLE duties (
  id              TEXT PRIMARY KEY,
  citizen_id      TEXT NOT NULL REFERENCES citizens(id),
  kind            TEXT NOT NULL,
    -- chat | heartbeat | patrol | dream | commission_worker | product | custom
  title           TEXT NOT NULL,
  schedule        TEXT,                      -- interval/cron/event label; null = continuous/on-demand
  enabled         INTEGER NOT NULL DEFAULT 1,
  config_json     TEXT,                      -- duty-specific small config
  created_at      TEXT NOT NULL
);

CREATE TABLE commissions (
  id              TEXT PRIMARY KEY,
  citizen_id      TEXT NOT NULL REFERENCES citizens(id),
  title           TEXT NOT NULL,
  body            TEXT NOT NULL,             -- task / prompt seed
  state           TEXT NOT NULL DEFAULT 'queued',
    -- queued | running | done | failed | cancelled
  priority        INTEGER NOT NULL DEFAULT 100,
  source          TEXT,                      -- jon | heartbeat | patrol | system
  session_id      TEXT,                      -- optional conv session used
  result_ref      TEXT,                      -- outbox path or message id
  error           TEXT,
  created_at      TEXT NOT NULL,
  started_at      TEXT,
  completed_at    TEXT
);

CREATE INDEX idx_commissions_citizen_state ON commissions(citizen_id, state, priority);
```

### 5.3 Workspace layout

```text
$SOVERYN_CITIZENS_ROOT/<id>/
  inbox/       # material dropped for the citizen
  outbox/      # reports ready for Jon (markdown/json)
  work/        # active commission scratch
  notes/       # journal fragments (not lattice)
  .citizen     # optional marker file with id + created_at
```

### 5.4 Status semantics

| Status | Meaning |
|--------|---------|
| `offline` | Process/endpoint not reachable |
| `resident` | Endpoint healthy; not currently running a commission |
| `on_duty` | Commission or scheduled duty in flight |
| `blocked` | Healthy enough to report, but failed last duty / needs Jon |
| `retired` | Citizenship revoked; no new commissions |

---

## 6. APIs (v1)

All local to vNext. Auth: same gate as existing app (public gate / session as today).

### 6.1 Citizens

```http
GET  /api/citizens
GET  /api/citizens/<id>
POST /api/citizens/refresh          # re-probe endpoints, update status
```

**GET /api/citizens** response (example):

```json
{
  "citizens": [
    {
      "id": "aetheria",
      "display_name": "Aetheria",
      "status": "resident",
      "model_server": "aetheria_primary",
      "endpoint": "http://127.0.0.1:8090",
      "workspace_path": "/home/jon-deoliveira/soveryn_citizens/aetheria",
      "last_seen_at": "2026-08-13T12:00:00",
      "open_commissions": 0,
      "duties_enabled": ["chat", "heartbeat"]
    }
  ]
}
```

### 6.2 Commissions

```http
GET  /api/citizens/<id>/commissions?state=queued
POST /api/citizens/<id>/commissions
     { "title": "...", "body": "...", "priority": 50, "source": "jon" }
POST /api/commissions/<id>/cancel
GET  /api/commissions/<id>
```

### 6.3 Runtime behavior

**Citizens runtime** (daemon thread inside vnext *or* `soveryn-citizens-runtime.service`):

1. Select highest-priority `queued` commission whose citizen is `resident` or idle.  
2. Mark `running`, set citizen `on_duty`.  
3. Ensure or create a conversation session tagged for the commission.  
4. Invoke existing `/chat` path or in-process `AgentLoop.process_message`.  
5. Write summary to `outbox/<commission_id>.md`.  
6. Mark `done` / `failed`; set citizen `resident` or `blocked`.  
7. Optional: Signal/messenger only if duty config allows and content is material.

**Concurrency:** default **one commission per citizen** at a time (Aetheria especially — single GPU slot).

**Backoff:** on model timeout / 504, mark failed with error, set blocked if N failures in window, do not spin hot loop.

---

## 7. Duties (map existing daemons)

| Duty kind | Current implementation | Citizens migration |
|-----------|------------------------|--------------------|
| `chat` | vNext /chat | No change; citizen must be active agent |
| `heartbeat` | `soveryn-heartbeat.service` | Phase: enqueue commission *or* keep daemon but register as duty + update last_seen |
| `patrol` | `soveryn-vett-patrol.service` | Same pattern for Vett |
| `dream` | `soveryn-dream.service` | Duty of house / Aetheria-adjacent; not necessarily a commission each night |
| `commission_worker` | new | Runtime drain |

**Migration principle:** Prefer **register first, rewire later**. v0.1 does not require killing heartbeat; it requires heartbeat to **appear** as a duty of citizen `aetheria`.

---

## 8. Memory and tools (project requirements)

### 8.1 Memory Grades (mandatory for always-on writers)

| Status | Item |
|--------|------|
| Done | Tool list/detail bounds (`content_caps`, `classify_and_render`) |
| Done | History-only budget 6k; soul origin off hot path |
| Required for v1.0 | write_node caps; heartbeat/dream distill; honest archive refs |
| Optional | Compaction M2 only after archive-resolving detail |

### 8.2 Tools

- Citizens use **existing** tool registry ownership (`owner_agent`).  
- Workspace tools (when added) default cwd to citizen workspace.  
- No new “run everything as root” tool.

### 8.3 Honesty

Product surfaces that invent compliance/pricing facts violate house law. Seneca-style refuse remains the public proof pattern.

---

## 9. Hardware and always-on inference

### 9.1 Target constellation (summary)

| Lane | Hardware | Model / service |
|------|----------|-----------------|
| Self | Blackwell UUID alone | Aetheria 31B Q6 @ :8090 |
| Workers | Spark 10.10.10.2 | Laguna @ :8000 |
| Librarian | One Quadro | Nemotron embed @ :8096 |
| Helpers | Quadro NVLink pair | cognition/dream, reflection; optional tensor-split **within pair only** |
| Host | CPU | Ares (sentinel) |
| RAM | ~512 GiB | `cache-ram` for Aetheria, buffers |

Full detail: **Always-On Model Map**.

### 9.2 Residence health (acceptance)

After any CUDA/preset change:

| Probe | Pass |
|-------|------|
| Short completion on Aetheria | Warm “OK” quickly |
| Prefill rate on mid/large prompt | Healthy for Blackwell (hundreds+ tok/s class once CUDA/arch correct — not ~40 tok/s class) |
| Embeddings | `/health` or embed call succeeds |
| Spark Laguna | Chat completion succeeds from vNext |

Wrong CUDA / missing Blackwell support is a **P0 residence failure**.

---

## 10. UI / UX

### 10.1 v1 console (minimal)

Single page or Mission Control tile: **Citizens board**

- List: name, status, open commissions, last error  
- Actions: refresh, create commission (textarea), open outbox link  
- No fake green lights without probe  

### 10.2 Site (soverynintelligence.com)

Citizens language optional on public site after internal v0.2. Public spear remains:

> AI that won’t invent the facts. On hardware you own.

---

## 11. Security and privacy

| Rule | Detail |
|------|--------|
| Local default | No automatic cloud model citizenship |
| **Corporate America in** | **Blocked** — no inbound corporate C2 / managed-agent APIs |
| **Bots calling home** | **Blocked** — no vendor telemetry, license pings, or fleet sync |
| **My data is my data** | House owns all citizen-held data; no silent training/siphon; egress only by Jon’s act or grant |
| Secrets | Per-service env; not in git; rotate if exposed |
| Workspaces | Not world-readable; under Jon’s home |
| Egress | Tools allowlisted and logged; never phone-home identity, duty state, or corpora to vendors |
| Signal | Allowlist **to Jon** only — human channel, not corporate call-home |
| Multi-tenant | Out of scope for v1 |

---

## 12. Observability

| Signal | Source |
|--------|--------|
| Citizen status | Probe + commission state |
| Commission latency | created_at → completed_at |
| Model timeouts | chat_timeout / 504 counts per citizen |
| Prefill tok/s | Router logs (ops) |
| Memory | tool B omitted counts; write sizes (when PR2+) |

Alerts: citizen `blocked`; N timeouts/hour; endpoint down.

---

## 13. Phased delivery

### Phase 0 — Prerequisites (ops)

- [ ] Blackwell CUDA/arch healthy; record tok/s baseline in Model Map  
- [ ] Dangerous `cache-ram=0` presets cannot be loaded by accident  
- [ ] Model map accepted as SSOT for residence  

**Exit:** Aetheria/Vett/Scotty chat works; short completion not multi-minute.

### Phase 1 — Registry & desks (v0.1)

- [ ] Create `~/soveryn_citizens/{aetheria,vett,scotty}/…`  
- [ ] `citizens.db` + seed three founding citizens  
- [ ] `GET /api/citizens` + refresh probe  
- [ ] Bootstrap from `ACTIVE_AGENTS` + `runtime.py`  

**Exit:** API lists three citizens with status ≠ always offline when fleet is up.

### Phase 2 — Commissions (v0.2)

- [ ] Schema commissions + POST create  
- [ ] Runtime worker (one at a time per citizen)  
- [ ] Outbox write on completion  
- [ ] Manual commission to Aetheria from API or CLI  

**Exit:** Jon can enqueue “summarize X into outbox”; result appears without interactive UI.

### Phase 3 — Duty registration (v0.3)

- [ ] Duties table seeded (chat, heartbeat, patrol)  
- [ ] Heartbeat daemon updates citizen last_seen / optional commission mode  
- [ ] Minimal console page or MC tile  

**Exit:** Board shows heartbeat as Aetheria duty; last_seen updates.

### Phase 4 — Memory for always-on (v1.0 quality)

- [ ] write_node caps  
- [ ] Heartbeat/dream distill dual-write  
- [ ] Provenance `cls` hygiene for new writes  

**Exit:** Always-on writers do not re-bloat lattice essays as default self-model.

### Phase 5 — Productization (optional, post-v1)

- [ ] Shepherd / customer deploy as “citizens-shaped” package  
- [ ] Public Citizens language on site  
- [ ] Multi-machine citizen directory  

---

## 14. Testing

| Level | Coverage |
|-------|----------|
| Unit | registry CRUD; status transitions; commission priority |
| Integration | POST commission → AgentLoop mock → outbox file |
| Ops | Probe scripts against live endpoints (manual/CI optional) |
| Regression | Existing agent loop / chat / tool_results tests stay green |

No requirement that integration tests hit GPU in default CI.

---

## 15. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Always-on burns GPU on garbage work | Priority queue; one-at-a-time; memory caps |
| Wrong CUDA returns “resident but unusable” | tok/s acceptance; status blocked on timeout streak |
| Scope creep into multi-tenant SaaS | Explicit non-goal |
| Dual daemon + commission double work | Register duties first; single path later |
| Naming confusion with Grok Bot | Product name **Citizens** only; no Grok in UI |
| Split-brain DBs / presets | Follow Model Map; one SSOT path |

---

## 16. File / module plan (implementation sketch)

```text
soveryn/
  platform/citizens/
    store.py           # SQLite citizens.db
    models.py          # dataclasses
    probe.py           # endpoint health
    runtime.py         # commission worker
    workspace.py       # ensure dirs
  app/routes/citizens.py
  app/startup.py       # register blueprint + optional worker thread

data/citizens.db
~/soveryn_citizens/<id>/...

docs/superpowers/specs/
  2026-08-13-soveryn-citizens-charter.md      # law
  2026-08-13-soveryn-citizens-project-spec.md # this file

tests/
  test_citizens_store.py
  test_citizens_api.py
  test_citizens_runtime.py
```

---

## 17. Dependencies on other workstreams

| Workstream | Coupling |
|------------|----------|
| Always-On Model Map | Residence SSOT |
| Memory Grades PR2–4 | Always-on write quality |
| Slop inventory (cognition URL unify, preset landmines) | Reduces false offline / false healthy |
| Signal / messenger | Report channel |
| Mission Control | Console host |

---

## 18. Glossary

| Term | Meaning |
|------|---------|
| **Citizen** | Named local identity with soul, residence, workspace, duties |
| **Residence** | Where the citizen’s model/process lives |
| **Duty** | Ongoing or scheduled obligation |
| **Commission** | Discrete unit of work in the queue |
| **Workspace** | On-disk desk for a citizen |
| **Sentinel** | Always-on non-chat guardian (Ares) |
| **Utility** | Infrastructure process, not a citizen |
| **Contractor** | Non-resident remote model, explicit grant only |
| **Polity** | The house — Jon’s SOVERYN deployment |

---

## 19. Open decisions (Jon)

1. Citizens runtime: **in-process vnext thread** vs **separate systemd unit**?  
2. Heartbeat v0.3: **register only** vs **full commission rewrite**?  
3. Workspace root: `~/soveryn_citizens` vs under `data/`?  
4. Seneca/Shepherd: full citizens in v1 or surfaces only?  
5. Console: extend Mission Control vs standalone `/citizens` page?

Defaults if undecided: **(1) vnext thread**, **(2) register only**, **(3) ~/soveryn_citizens**, **(4) surfaces only**, **(5) `/citizens` JSON + thin HTML later**.

---

## 20. Spec summary (one page)

```text
PROJECT: SOVERYN Citizens
GOAL:    Local always-resident AI with name, soul, desk, duties, queue
NOT:     Cloud Grok Bot; SaaS multi-tenant; legal personhood;
         no calls out or in for bots — sovereign

HAVE:    vNext, AgentLoops, lattice, souls, systemd, tower+Spark models
BUILD:   registry, workspaces, commissions, runtime, status API, console

LAW:     Charter + Memory Grades + Always-On Model Map
ORDER:   health → registry → commissions → duties → memory distill → productize

SUCCESS: Three citizens on the board; Jon enqueues work; results in outbox;
         house stays local; no invented facts as product promise;
         no corporate America dialing in; no bots calling home;
         my data is my data.
```

---

*End of full project specification. Charter is constitutional law; this document is the build contract. Implementation follows phases in §13.*
