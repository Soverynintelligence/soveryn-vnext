# SOVERYN Current Truth

> **Source of authority for what is actually running — right now.**  
> Observed / operator-confirmed. Not aspirational. Not a phase dump.  
> **Last rotated:** 2026-08-25  
> Prior archive: `docs/CURRENT_TRUTH_2026-05-23.md` (historical — do not treat as live).

If runtime behavior changes, **update this file first**, then code/notes.

---

## 0. House spine (locked 2026-08-24)

**One rule:** if Jon needs it day-to-day, it shows up in **Messages**. Everything else is engine room or a satellite.

| Layer | What | Role |
|-------|------|------|
| **Phone OS / front door** | Messages (`/` → `/messages`) | **The product.** Contacts = house staff + Critic/Scout overnight inboxes. Talk → Gate Allow/Deny in-thread. |
| **Tower / desk** | Command Center (`/command-center`), Staff (`/citizens`), Fleet | Ops HUD — evidence & commissions; not the daily ask door. |
| **House staff** | Citizens in `soveryn_vnext` | Execute work (commissions, Eve posts, Kernel builds). |
| **Outside eye** | Teammates (`~/teammates`) | Critic/Scout overnight — **observe & brief**; do **not** become a second phone app. Briefs → Messages (`t_critic` / `t_scout`). |
| **Public products** | Seneca, PondWright, Atticus, TGTHRmess | Customer/brand surfaces on Spark — not the house OS. |

**Do / don’t**

- **Do** add phone UX to Messages (or feed Messages).  
- **Do** keep Teammates as a separate process that POSTs briefs into the house.  
- **Don’t** invent new phone consoles (`:5075` marketing, extra PWAs) for house work.  
- **Don’t** treat Funnel/Command Center/Teammates console as the consumer front door.

Funnel: `https://soveryn-1.tail70bbcc.ts.net/messages` (Basic once → 30-day cookie).  
Refs: `docs/mockups/messenger-one-door/` + `refs/` (Grok Bots screenshots).

---

## 1. What is live

### House (soveryn_vnext) — tower `:5001`
| Surface | Status |
|---------|--------|
| Flask vNext | **Live** |
| Agents | **Aetheria, Vett, Scotty, Kernel, Eve** |
| Heartbeat / dream / automations | **Live** |
| Citizens commissions + standing objectives | **Live** |
| Eve marketing cadence | **Live** Mon/Thu — Canva + Signal (automation auto-Allow) |
| Eve interactive compose | **Live** — Messages Gate **Allow → Signal** (caption + image) |
| House improvement scan | **Live** Mon/Wed/Fri |
| Canva Connect | **Live** (tokens local-only) |
| Messages / CoS | **Live** — **default `/` door**; PWA + **Web Push** (Gate / needs-you); Signal stays Aetheria-only |

### Teammates — `~/teammates`
| Surface | Status |
|---------|--------|
| Critic + Scout overnight | **Live** — cron; briefs → Messages |
| Scheduler | **Enabled** — Critic `02:00` ET, Scout `07:30` ET; `teammates stop` = HALT |
| Bridge | `POST /api/internal/teammates_brief` (localhost) |
| Marketer interactive / `:5075` as product UI | **Deprecated** — posts via Messages → Eve |
| Console `:5075` | Background / operator only |

### Public Spark
| Product | Status |
|---------|--------|
| Seneca `:8400` | **Live** — lead capture wired → Toni notify |
| PondWright `:8200` | **Live** |
| Atticus `:8500` | **Live** |

### Brains
| Lane | Where |
|------|--------|
| Aetheria | Blackwell `:8090` — alone |
| Kernel / Eve default | Quadros Flash `:8091` |
| Shared Spark workers | `:8001` |
| FreeToken | **Back burner** until second ASUS (ETA Wednesday evening) |

---

## 2. Incomplete / blocked

| Item | State |
|------|--------|
| Citizen email | **Not production** — needs SMTP + `SOVERYN_EMAIL_PRODUCTION=1` |
| CoS rename | **Deferred** — Aetheria still `COS_ID` |
| Eve Allow → Signal | **Done 2026-08-24** — interactive Gate; Meta IG still later |
| Critic → Aetheria commissions | **Live + E2E 2026-08-25** — `read_overnight_brief` → `house_post_send` → commission queued (sample: Vett verify run `aab8411e`) |
| Second ASUS GX10 | **Ordered — ETA Wednesday** (bring-up Wed evening) |
| CWG brand | **Locked:** oasis/serenity/wildlife — not catalog pricing |
| Memory / identity layer | **2026-08-25** — pinned + persona spine; journal/heartbeat recall demoted to Channel B (not “I remember…” essays) |

---

## 3. Brands (one place)

| Brand | Owns | Voice |
|-------|------|--------|
| **SOVERYN** | House, citizens, Kernel, Messages | Quiet confidence |
| **CWG** | Carolina Water Gardens craft | Oasis / serenity / wildlife |
| **PondWright** | Quote/CRM for CWG | Product honesty |
| **ActTruth** | Ledger / spend honesty | Cite-or-stop |
| **History’s Ledger / Atticus** | Corpus / history | Precise, receipts |

---

## 4. Kill list

1. ~~Rotate source of authority~~ → this file  
2. ~~Secrets/state backup~~ → runbook + drill PASS  
3. ~~Seneca lead capture~~ → Spark `soveryn-leads.jsonl`  
4. ~~Citizen email~~ → marked not production  
5. ~~House spine~~ → **§0 locked 2026-08-24**  
6. Keep this file short when state changes  

**Next (when Jon says go):** Install Messages PWA on phone + Enable alerts; ASUS Wed evening; Meta IG / CRM parked.

---

## 5. Git / ops

| Repo | Branch / tip |
|------|----------------|
| `soveryn_vnext` | `feat/mission-control-spark-tile` (+ local) |
| `teammates` | `feat/phase-0` · overnight + Messages bridge |

Notes in `docs/notes/` are **not** authority. **This file is.**
