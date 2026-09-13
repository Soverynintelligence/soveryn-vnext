# SOVERYN Current Truth

> **Source of authority for what is actually running — right now.**  
> Observed / operator-confirmed. Not aspirational. Not a phase dump.  
> Last rotated: 2026-09-13 (staleness rule re-keyed to newest per-row last-observed date)  
> Prior archive: `docs/archive/CURRENT_TRUTH_2026-05-23.md` (historical — do not treat as live).
> Staleness rule: key off the **newest per-row** "last observed" / "Last verified" date in this file, not this header date. If that newest per-row date is >7 days old, treat the file as stale and re-observe. The header "Last rotated" date is updated on every row edit to track the newest per-row date.  

If runtime behavior changes, **update this file first**, then code/notes.

---

## 0. House spine (locked 2026-08-24)
*Last observed: 2026-08-24; public-products row re-checked 2026-09-09 (Kernel).*
*As of 2026-09-12; rows below show last-observed dates.*

> Dated note 2026-09-09: superseded snapshot 2026-05-23 moved to docs/archive/ — this file is the only live truth.

**One rule:** if Jon needs it day-to-day, it shows up in **Messages**. Everything else is engine room or a satellite.

| Layer | What | Role |
|-------|------|------|
| **Phone OS / front door** | Messages (`/` → `/messages`) | **The product.** Contacts = **MESSAGES_CONTACTS** + Critic/Scout overnight inboxes. Talk → Gate Allow/Deny in-thread. |
| **Tower / desk** | Command Center (`/command-center`), Staff (`/citizens`), Fleet | Ops HUD — evidence & commissions; not the daily ask door. |
| **House staff** | Citizens in `soveryn_vnext` | Execute work (commissions, Eve posts, Kernel builds). |
| **Outside eye** | Teammates (`~/teammates`) | Critic/Scout overnight — **observe & brief**; do **not** become a second phone app. Briefs → Messages (`t_critic` / `t_scout`). |
| **Public internet** | soverynintelligence.com, Seneca, PondWright/CWG | Customer/brand surface. |
| **In-house tower ports** | Atticus `:8500`, TGTHRmess | **Not** confirmed public-internet products — tower ports per §1 Public Spark. Atticus is the History's Ledger fact-guard (halts when the page isn't held). Messie is Qwen3.5-9B Q6 on `:5066` (TGTHR helper), not the Quadros 27B public slot. Unit: `~/.config/systemd/user/tgthrmess-messie.service` (tracked copy `~/tgthr-entries/systemd/tgthrmess-messie.service`). |

*These three are the surfaces the README public-surface table has actually fetched; README lists only fetched surfaces.*

### 0a. Fleet freeze — frontier few (locked 2026-08-27)
*Last observed: 2026-08-27.*
*How to verify: `nvidia-smi` shows ≤1 frontier model per card; `systemctl --user list-units 'soveryn*'` (and the `:PORT` listeners in §1) list the live agent services.*

**Constraint:** you cannot run six frontier minds and six personas on this iron. One card → one frontier mind. Extra agents only for **different tools** or a **different clock** — never another wig on the same weights.

| Messages contact | Role | Brain |
|------------------|------|--------|
| **Aetheria** | Soul / face / judgment | Blackwell alone — Qwen 3.8-27B |
| **Kernel** | Local build | spark2 Qwen3.8-Flash-Next NVFP4 TP=1 (`:8888`, house ctx 131072). GLM TP=2 parked. |
| **Eve** | Research + ship (Vett folded in) | Quadros Qwen 3.8 — Canva / Signal / CWG IG |
| **Critic / Scout** | Overnight only | Teammates → inbox (not chat peers) |

Per-row verification dates — model swaps are the most common silent drift; do not trust the section-level date alone:

| Row (model/endpoint) | Last verified |
|----------------------|---------------|
| Aetheria — Blackwell `:8090` Qwen 3.8-27B | 2026-08-27 (section freeze); re-confirmed 2026-09-01 per §1 Brains |
| Kernel — spark2 `:8888` Qwen3.8-Flash-Next NVFP4 TP=1 | 2026-09-06 (Flash-Next move; GLM `:8001` parked — power-cut note §1 Brains) |
| Eve — Quadros `:8091` Qwen 3.8-27B | 2026-08-27 (section freeze); re-confirmed 2026-09-01 per §1 |
| TGTHR helper Messie — `:5066` Qwen3.5-9B Q6 | 2026-09-09 (Kernel — re-checked vs §0 public-products note; in-house TGTHR helper, not the Quadros 27B public slot) |
| Critic / Scout — Teammates inbox | 2026-09-07 (§0b brief contract) |

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

### 0b. Critic / Scout brief contract
*Last observed: 2026-09-07.*

- **Cadence:** Critic `02:00` ET, Scout `07:30` ET. **Overnight** = `00:00–08:00` ET.
- **Brief file format:** one markdown file per run. Required front-matter keys: `run_id`, `citizen` (`critic`|`scout`), `generated_at` (ISO-8601 ET), `severity` (`info`|`warn`|`act`), `targets` (list of repo paths or surfaces touched). Body: `## Findings` then `## Proposed actions`.
- **Delivery:** Teammates POST the brief to `POST /api/internal/teammates_brief` (localhost only). The bridge files it into the Messages inbox thread — Critic → `t_critic`, Scout → `t_scout`. Teammates observe & brief; they are **not** chat peers and do not appear in `ACTIVE_AGENTS`.
- **Halt:** `teammates stop` = HALT.

---

## 1. What is live
*Last observed: 2026-09-01.*

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
| Eve CWG Google Business | **Wired, not armed.** `eve_gbp_post` Gate-only (never cadence). OAuth listing posts: `python -m soveryn.platform.gbp authorize`. Tokens: `data/gbp/`. |
| Agent browser desks | **Live.** Persistent Chrome per agent under `data/desks/<agent>/<seat>/chrome`. Jon signs in: `python -m soveryn.platform.social.agent_desk login eve google` (CWG Google — Business + Ads). Eve: `eve_google_desk_status`. **No auto-spend.** Instagram remains `data/eve_ig_profile/`. |
| Eve X | **Live.** House @Soveryn_AI (`read_x` / `post_to_x`, `X_*` in `x_presence.env`). Stages until Jon says `post it`. **Aetheria off X** (no tools, no heartbeat tweet nudge). |
| House improvement scan | **Live** Mon/Wed/Fri |
| Canva Connect | **Live** (tokens local-only) |
| Messages / CoS | **Live** — **default `/` door**; PWA + **Web Push on** (Gate / needs-you / Critic·Scout brief ready); Signal = Aetheria-only |
| Verification gate | **Live — owner: Eve** (default was Vett; silently inert after the fold — repointed 2026-09-01, `58cb1e9`) |

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
| Kernel | spark2 Flash-Next `:8888` (`qwen3.8-flash-next`, NVFP4 TP=1, house ctx 131072; GLM `:8001` parked) |
| Eve + public Qwen | Quadros `:8091` Qwen 3.8-27B |
| Shared Spark workers | `:8001` GLM TP=2 **parked** (power-cut 2026-09-06; Kernel moved to Flash-Next) |
| Second Spark | **Live** — `gx10-a733` / soverynspark2, Flash-Next vLLM `:8888` |

---

## 2. Incomplete / blocked
*Last observed: 2026-08-25.*

| Item | State |
|------|--------|
| Citizen email | **Not production — NOT ARMED.** Gated checklist is canonical in `docs/notes/2026-08-23-citizen-email-identity.md` §Ops checklist (single source for the step list and its count — this row deliberately does not restate or number the steps). Latch `SOVERYN_EMAIL_PRODUCTION=1` off; SMTP alone does not arm egress. |
| CoS rename | **Deferred** — Aetheria still `COS_ID` |
| Eve Allow → Signal | **Done 2026-08-24** — interactive Gate; Meta IG still later |
| Critic → Aetheria commissions | **Live + E2E 2026-08-25** — `read_overnight_brief` → `house_post_send` → commission queued (sample: Vett verify run `aab8411e`) |
| Second ASUS GX10 | **Live** — Spark2 `gx10-a733` on GLM TP=2 |
| CWG brand | **Locked:** oasis/serenity/wildlife — not catalog pricing |
| Memory / identity layer | **2026-08-25** — pinned + persona spine; journal/heartbeat recall demoted to Channel B (not “I remember…” essays) |

---

## 3. Brands (one place)
*Last observed: 2026-08-31.*

| Brand | Owns | Voice |
|-------|------|--------|
| **SOVERYN** | House, citizens, Kernel, Messages | Quiet confidence |
| **CWG** | Carolina Water Gardens craft | Oasis / serenity / wildlife |
| **PondWright** | Quote/CRM for CWG | Product honesty |
| **ActTruth** | Ledger / spend honesty | Cite-or-stop |
| **History’s Ledger / Atticus** | Corpus / history | Precise, receipts |

---

## 4. Kill list
*Last observed: 2026-08-31.*

1. ~~Rotate source of authority~~ → this file  
2. ~~Secrets/state backup~~ → runbook + drill PASS  
3. ~~Seneca lead capture~~ → `docs/leads/seneca-leads.csv` (retroactive 08-24)  
4. ~~Citizen email~~ → **NOT ARMED** — gated checklist in `docs/notes/2026-08-23-citizen-email-identity.md` §Ops checklist (9 steps; §2 is the live-state pointer)  
5. ~~House spine~~ → **§0 locked 2026-08-24**  
6. Keep this file short when state changes  

**Next (when Jon says go):** House as-is (no second ASUS this week); Meta IG / CRM parked.

Runbooks (not kill-list copies): `docs/runbooks/secrets-state-backup.md` · `docs/runbooks/env-var-map.md` · incident template `docs/notes/INCIDENT-TEMPLATE.md` · **internal** SOVERYN quote skeleton `docs/ops/soveryn-quote-skeleton.md` (not public; Seneca does not quote dollars).

---

## 5. Git / ops
*Last observed: 2026-09-01.*

| Repo | Branch / tip |
|------|----------------|
| `soveryn_vnext` | `feat/mission-control-spark-tile` @ `ecf5635` — **pushed 2026-09-01** (12 commits: messenger faces, Eve vision/QR, Kernel composer, Pi harness, chess3d, citizen shapes, lattice scan cache, X media upload, reference KB) |
| `teammates` | `feat/phase-0` · overnight + Messages bridge (`6f9ae24`) |

Notes in `docs/notes/` are **not** authority. **This file is.**
