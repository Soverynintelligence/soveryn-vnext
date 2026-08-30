# SOVERYN Current Truth

> **Source of authority for what is actually running — right now.**  
> Observed / operator-confirmed. Not aspirational. Not a phase dump.  
> **Last rotated:** 2026-08-30  
> Prior archive: `docs/CURRENT_TRUTH_2026-05-23.md` (historical — do not treat as live).

If runtime behavior changes, **update this file first**, then code/notes.

---

## 0. House spine (locked 2026-08-24)

**One rule:** if Jon needs it day-to-day, it shows up in **Messages**. Everything else is engine room or a satellite.

| Layer | What | Role |
|-------|------|------|
| **Phone OS / front door** | Messages (`/` → `/messages`) | **The product.** Contacts = **MESSAGES_CONTACTS** + Critic/Scout overnight inboxes. Talk → Gate Allow/Deny in-thread. |
| **Tower / desk** | Command Center (`/command-center`), Staff (`/citizens`), Fleet | Ops HUD — evidence & commissions; not the daily ask door. |
| **House staff** | Citizens in `soveryn_vnext` | Execute work (commissions, Eve posts, Kernel builds). |
| **Outside eye** | Teammates (`~/teammates`) | Critic/Scout overnight — **observe & brief**; do **not** become a second phone app. Briefs → Messages (`t_critic` / `t_scout`). |
| **Public products** | Seneca, PondWright, Atticus, TGTHRmess | Customer/brand surfaces — **not** the house OS. Messie is Qwen3.5-9B on `:5066` (TGTHR helper), not the Quadros 27B public slot. |

### 0a. Fleet freeze — frontier few (locked 2026-08-27)

**Constraint:** you cannot run six frontier minds and six personas on this iron. One card → one frontier mind. Extra agents only for **different tools** or a **different clock** — never another wig on the same weights.

| Messages contact | Role | Brain |
|------------------|------|--------|
| **Aetheria** | Soul / face / judgment | Blackwell alone — Qwen 3.8-27B |
| **Kernel** | Local build | Dual Spark GLM-5.3-Flash NVFP4 (RedHat, 32k) |
| **Eve** | Research + ship (Vett folded in) | Quadros Qwen 3.8 — Canva / Signal / CWG IG |
| **Critic / Scout** | Overnight only | Teammates → inbox (not chat peers) |

| Pulled from house chat | Notes |
|------------------------|--------|
| **Vett** | Folded into Eve. Not in `ACTIVE_AGENTS`. No Messages thread. |
| **Scotty** | Coding folded into Kernel / OpenCode. Not in `ACTIVE_AGENTS`. No Messages thread. |
| **Grok** | Talk to Grok in **Grok Bots** on the desktop. Kernel is the phone→tower coding door. |

**Do / don’t**

- **Do** add phone UX to Messages (or feed Messages).  
- **Do** keep Teammates as a separate process that POSTs briefs into the house.  
- **Do** keep Vett/Scotty/Grok off the house chat roster (folded / desktop).  
- **Don’t** invent new phone consoles (`:5075` marketing, extra PWAs) for house work.  
- **Don’t** treat Funnel/Command Center/Teammates console as the consumer front door.  
- **Don’t** load a sixth local frontier “just in case.”

Funnel: `https://soveryn-1.tail70bbcc.ts.net/messages` (Basic once → 30-day cookie).  
Refs: `docs/mockups/messenger-one-door/` + `refs/` (Grok Bots screenshots).

---

## 1. What is live

### House (soveryn_vnext) — tower `:5001`
| Surface | Status |
|---------|--------|
| Flask vNext | **Live** |
| Agents | **Messages:** Aetheria, Kernel, Eve (+ Critic/Scout inboxes). Vett/Scotty/Grok **not** house chat agents. |
| Heartbeat / dream / automations | **Live** |
| Citizens commissions + standing objectives | **Live** |
| Eve marketing cadence | **Live** Mon/Thu — Canva + Signal (automation auto-Allow) |
| Eve interactive compose | **Live** — Messages Gate **Allow → Signal** (caption + image) |
| Eve CWG Instagram desk | **Session live.** `eve_ig_post` Gate-only (never cadence). Pics: `~/Desktop/CWG-Instagram`. Profile `data/eve_ig_profile/`. |
| Eve CWG Google Business | **Wired, not armed.** `eve_gbp_post` Gate-only (never cadence, never ads). OAuth: `python -m soveryn.platform.gbp authorize`. Needs Cloud client + Google access/quota. Tokens: `data/gbp/`. |
| Eve X | **Live.** House @Soveryn_AI (`read_x` / `post_to_x`, `X_*` in `x_presence.env`). Stages until Jon says `post it`. **Aetheria off X** (no tools, no heartbeat tweet nudge). |
| House improvement scan | **Live** Mon/Wed/Fri |
| Canva Connect | **Live** (tokens local-only) |
| Messages / CoS | **Live** — **default `/` door**; PWA + **Web Push on** (Gate / needs-you / Critic·Scout brief ready); Signal = Aetheria-only |

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
| Kernel | Dual Spark GLM `:8001` (`glm-5.3-flash`, RedHat compressed-tensors, ctx 32768) |
| Eve + public Qwen | Quadros `:8091` Qwen 3.8-27B |
| Shared Spark workers | `:8001` GLM TP=2 (Spark2 worker on fabric) |
| Second Spark | **Live** — `gx10-a733` / soverynspark2, GLM rank 1 |

---

## 2. Incomplete / blocked

| Item | State |
|------|--------|
| Citizen email | **Not production — NOT ARMED.** Gated checklist (source: `docs/notes/2026-08-23-citizen-email-identity.md` §Ops checklist): 1) aliases on soverynintelligence.com + carolinawatergardens.com · 2) SPF/DKIM/DMARC both domains · 3) arm `SOVERYN_SMTP_HOST`/`SOVERYN_SMTP_FROM` + creds · 4) optional IMAP house inbox · 5) `SOVERYN_EMAIL_PRODUCTION=1` only after controlled smoke · 6) smoke: Messages → Aetheria → Gate Allow → test as `aetheria@soverynintelligence.com` · 7) flip this row to **Live** only after smoke |
| CoS rename | **Deferred** — Aetheria still `COS_ID` |
| Eve Allow → Signal | **Done 2026-08-24** — interactive Gate; Meta IG still later |
| Critic → Aetheria commissions | **Live + E2E 2026-08-25** — `read_overnight_brief` → `house_post_send` → commission queued (sample: Vett verify run `aab8411e`) |
| Second ASUS GX10 | **Live** — Spark2 `gx10-a733` on GLM TP=2 |
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
3. ~~Seneca lead capture~~ → `docs/leads/seneca-leads.csv` (retroactive 08-24)  
4. ~~Citizen email~~ → **NOT ARMED** — gated checklist in §2  
5. ~~House spine~~ → **§0 locked 2026-08-24**  
6. Keep this file short when state changes  

**Next (when Jon says go):** House as-is (no second ASUS this week); Meta IG / CRM parked.

Runbooks (not kill-list copies): `docs/runbooks/secrets-state-backup.md` · `docs/runbooks/env-var-map.md` · incident template `docs/notes/INCIDENT-TEMPLATE.md` · **internal** SOVERYN quote skeleton `docs/ops/soveryn-quote-skeleton.md` (not public; Seneca does not quote dollars).

---

## 5. Git / ops

| Repo | Branch / tip |
|------|----------------|
| `soveryn_vnext` | `feat/mission-control-spark-tile` @ `5c1e880` — **pushed** (Messages door, push, spine) |
| `teammates` | `feat/phase-0` · overnight + Messages bridge (`6f9ae24`) |

Notes in `docs/notes/` are **not** authority. **This file is.**
