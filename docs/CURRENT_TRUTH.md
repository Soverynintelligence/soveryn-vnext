# SOVERYN Current Truth

> **Source of authority for what is actually running — right now.**  
> Observed / operator-confirmed. Not aspirational. Not a phase dump.  
> Last rotated: 2026-10-19 (Kernel — full re-observe; previous rotation 2026-09-28 had drifted 21 days and listed a dead brain).
> Prior archive: `docs/archive/CURRENT_TRUTH_2026-05-23.md` (historical — do not treat as live).
> Staleness rule: key off the **newest per-row** "last observed" / "Last verified" date in this file, not this header date. If that newest per-row date is >7 days old, treat the file as stale and re-observe. The header "Last rotated" date is updated on every row edit to track the newest per-row date.  
> Machine check: `grep -E '^\|' docs/CURRENT_TRUTH.md | grep -oE '2026-[0-9]{2}-[0-9]{2}' | sort -r | head -1` — newest per-row date; if older than 7 days before today, file is stale, re-observe. Completeness check: `grep -cE '^## [0-9]' docs/CURRENT_TRUTH.md` must equal **6** (§0–§5) — freshness alone can pass on a truncated file; the section count makes truncation fail the check. Row-date check: every row that makes a **status claim** must carry a parseable 2026 date. Table header rows are the only legal exception. Command: `grep -E '^\|' docs/CURRENT_TRUTH.md | grep -vE '^\|[-: |]+\|$' | grep -vE '^\| *(Layer|Messages contact|Row|Pulled|Surface|Product|Lane|Repo|Item|Brand|Branch)[^|]*\|' | grep -vcE '2026-[0-9]{2}-[0-9]{2}'` must equal **0**. (Prior rotations violated this: the 2026-09-28 file carried 73 undated rows, which is how a dead brain row sat unread for 21 days.) Readers must confirm the section count before trusting any single section — a truncated read can still pass freshness on visible rows. Re-observe is assigned to **Kernel** (house build brain), cadence weekly — Monday morning, alongside the ledger reconcile timer. Escalation rule: two consecutive missed Monday re-observes → affected rows marked `STALE-UNVERIFIED` in the table itself. Integrity check: `grep -c '^END-OF-TRUTH' docs/CURRENT_TRUTH.md` must equal **1** (zero = truncated file; two or more = marker leaked into body).
> <!-- Staleness check: scope to | table rows only, not free-text prose dates. -->

If runtime behavior changes, **update this file first**, then code/notes.

---

## 0. House spine (locked 2026-08-24)
*As of 2026-10-19; per-row dates are the source of truth.*

**One rule:** if Jon needs it day-to-day, it shows up in **Messages**. Everything else is engine room or a satellite.

| Layer | What | Role | Last observed |
|-------|------|------|---------------|
| **Phone OS / front door** | Messages (`/` → `/messages`) | **The product.** Contacts = `MESSAGES_CONTACTS` + Critic/Scout overnight inboxes. Talk → Gate Allow/Deny in-thread. | 2026-10-19 |
| **Tower / desk** | Command Center (`/command-center`), Staff (`/citizens`), Fleet | Ops HUD — evidence & commissions; not the daily ask door. Both 200 on `:5001`. | 2026-10-19 |
| **House staff** | Citizens in `soveryn_vnext` | Execute work (commissions, Eve posts, Kernel builds). `ACTIVE_AGENTS` = aetheria, forge, eve. | 2026-10-19 |
| **Build brain** | Kernel — SOVERYN CLI on Pi, pinned `1.3.0` | **Not a chat citizen.** The harness Jon codes through. Follows `~/.soveryn/kernel_brain`. | 2026-10-19 |
| **Outside eye** | Teammates (`~/teammates`) | Critic/Scout overnight — **observe & brief**; do **not** become a second phone app. Briefs → Messages (`t_critic` / `t_scout`). | 2026-10-19 |
| **Public internet** | soverynintelligence.com, Seneca `:8400`, PondWright/CWG, acttruth.com, shepherdfcc.com, cathedral.soverynintelligence.com (DNS still pending) | Customer/brand surface. All respond except the cathedral host, which does not resolve (see §1). | 2026-10-19 |
| **In-house tower ports** | Atticus `:8500`, TGTHRmess | **Not** confirmed public-internet products — tower ports per §1 Public Spark. Atticus is the History's Ledger fact-guard. Messie is Qwen3.5-9B Q6 on `:5066` (TGTHR helper), not the Quadros 27B public slot. | 2026-10-19 |

- 2026-09-09: superseded snapshot 2026-05-23 moved to docs/archive/ — this file is the only live truth.
- 2026-10-19: **roster corrected.** Kernel is the build brain (Pi harness), not a citizen; the citizen formerly named Kernel is now **Forge** (`forge`, un-retired 2026-09-29). `MESSAGES_CONTACTS` = aetheria, forge, eve.

*These three are the surfaces the README public-surface table has actually fetched; README lists only fetched surfaces.*

### 0a. Fleet freeze — frontier few (locked 2026-08-27)
*Last observed: 2026-10-19.*
*How to verify: `nvidia-smi` shows ≤1 frontier model per card; `systemctl --user list-units 'soveryn*'` (and the `:PORT` listeners in §1) list the live agent services.*

**Constraint:** you cannot run six frontier minds and six personas on this iron. One card → one frontier mind. Extra agents only for **different tools** or a **different clock** — never another wig on the same weights.

| Messages contact | Role | Brain | Last verified |
|------------------|------|-------|---------------|
| **Aetheria** | Soul / face / judgment | Quadros CUDA1 `:8091` — llama-server router (Quadro RTX 8000, CUDA1). Serves `qwen38` as alias `aetheria`, plus cognition/embeddings/reflection/shepherd-* lanes. | 2026-10-19 (live check) |
| **Forge** | Local build citizen | `AGENT_TO_SERVER` → `kernel_build`, which resolves `~/.soveryn/kernel_brain` at call time. Currently **deepseek** — spark2 `:8888`. | 2026-10-19 (live check) |
| **Eve** | Research + ship | Blackwell `:8090` vLLM — Qwen 3.8-27B NVFP4, aliases `eve` / `qwen38` / `bench-flash`. | 2026-10-19 (live check) |
| **Critic / Scout** | Overnight only | Teammates → inbox (not chat peers). `teammates-scheduler.service` live. | 2026-10-19 |

Per-row verification dates — model swaps are the most common silent drift; do not trust the section-level date alone:

| Row (model/endpoint) | Last verified |
|----------------------|---------------|
| Aetheria — Quadros CUDA1 `:8091` llama-server router | 2026-10-19 (live; `/v1/models` lists aetheria via `qwen38`) |
| Forge / Kernel brain — **deepseek** `DeepSeek-V4.1-Flash-1017` EXL3 2.9bpw, tensorfold, spark2 `:8888` | 2026-10-19 (live; `~/.soveryn/kernel_brain` = `deepseek`; served id mixed-case, profile `modelId` canonical `deepseek-v4.1-flash-1017`) |
| Eve — Blackwell `:8090` Qwen 3.8-27B NVFP4 | 2026-10-19 (live; `/v1/models` lists `qwen38-nvfp4`) |
| Cognition — `:8089` Gemma 4 26B-A4B Q5, alias `dream` | 2026-10-19 (live; re-enabled 2026-10-04) |
| Messie — `:5066` Qwen3.5-9B Q6 | 2026-10-19 (live; `/health` 200) |
| Critic / Scout — Teammates inbox | 2026-10-19 (`teammates-scheduler.service` active) |

| Pulled from house chat | Notes |
|------------------------|--------|
| **Vett** | Folded into Eve. Not in `ACTIVE_AGENTS`. No Messages thread. `soveryn-vett-patrol.service` still runs — see §2. | 2026-10-19 |
| **Scotty** | Coding folded into Kernel / Forge. Not in `ACTIVE_AGENTS`. No Messages thread. | 2026-10-19 |
| **Grok** | Talk to Grok in **Grok Bots** on the desktop. Kernel is the phone→tower coding door. | 2026-10-19 |

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
*Last observed: 2026-10-19.*

- **Cadence:** Critic `02:00` ET, Scout `07:30` ET. **Overnight** = `00:00–08:00` ET.
- **Brief file format:** one markdown file per run. Required front-matter keys: `run_id`, `citizen` (`critic`|`scout`), `generated_at` (ISO-8601 ET), `severity` (`info`|`warn`|`act`), `targets` (list of repo paths or surfaces touched). Body: `## Findings` then `## Proposed actions`.
- **Delivery:** Teammates POST the brief to `POST /api/internal/teammates_brief` (localhost only). The bridge files it into the Messages inbox thread — Critic → `t_critic`, Scout → `t_scout`. Teammates observe & brief; they are **not** chat peers and do not appear in `ACTIVE_AGENTS`.
- **Halt:** `teammates stop` = HALT.
- **Units:** `teammates-scheduler.service` (cron), `teammates-console.service` (`:5075`, background/operator only).

---

## 1. What is live
*Last observed: 2026-10-19 (full re-observe: units, ports, /v1/models, public URLs).*

### House (soveryn_vnext) — tower `:5001`
| Surface | Status |
|---------|--------|
| Flask vNext (`soveryn-vnext.service`) | **Live 2026-10-19** — `/` 302 → `/messages`; `/command-center` 200, `/citizens` 200, `/cathedral` 200, `/api/delegation/pending` 200 |
| Cathedral (private `/cathedral`) | **Live 2026-10-19** — WebGL galaxy of the live lattice (nodes/edges/suns/landmarks from `lattice_vnext.db`, per request, 30s poll diff). Public view strips memory text at the API — stars real, words stay home. |
| Cathedral public (`soveryn-cathedral-public.service` `:18810`) | **Serving locally 2026-10-19** (200) — but `cathedral.soverynintelligence.com` **does not resolve** (no DNS record). The tunnel ingress exists; the CNAME was never added. Public URL is dead until Jon adds it in the CF dashboard → `85970537-f4aa-40cf-b616-c5f185e2ae81.cfargotunnel.com`. |
| Public auth gate (`soveryn-public-gate.service` `:5099`) | **Live 2026-10-19** — basic-auth reverse proxy → vNext `:5001`, funneled. 401 unauthenticated, as designed |
| Agents | **Live 2026-10-19** — Messages: aetheria, forge, eve (+ Critic/Scout inboxes). Vett/Scotty/Grok **not** house chat agents |
| Heartbeat / dream / automations (`soveryn-heartbeat`, `soveryn-dream`, `soveryn-automations`) | **Live 2026-10-19** |
| Cognition surface (`soveryn-cognition.service` — Gemma 4 26B-A4B Q5, CPU-only `:8089`, alias `dream`) | **Live 2026-10-19** — restarted 2026-10-04 22:05. Was silently down ~Aug 30 → Sep 13 |
| Deep Cognition Cycle (`soveryn-cognition-cycle.service`) | **Live 2026-10-19** — Aetheria reflect → process → distill loop |
| Representation daemon (`soveryn-representation.service`) | **LIVE 2026-10-19 — re-enabled 2026-10-04 22:08.** Previously PARKED 2026-09-22 after a 7,921-restart loop; re-enabled together with cognition. Quality gate before leaving dry-run still open (outputs read shallow/repetitive) |
| Vett patrol (`soveryn-vett-patrol.service`) | **DISABLED + STOPPED 2026-10-19 (Jon: falls under Eve).** Was running since 2026-10-01 for a folded agent with nothing logged. Ownership now unambiguously Eve's: sources + verify-or-say-nothing standard live in `data/memory/skills/eve/funding-watch.md`, which already said “do not restart it — run the watch through your automations.” Daemon left in the repo for a future deterministic crawler |
| Service crash watch (`soveryn-crash-watch.timer` 15min) | **Live 2026-10-19** — deterministic `scripts/systemd_health_watch.py` writes `data/automations/watches/systemd_health.txt` only on failed/activating/NRestarts≥10 units; unchanged file = no LLM, change = Aetheria briefs Jon |
| SOVERYN CLI harness hardening | **Live 2026-10-19** — `doctor --json` machine-readable; parked-but-live drift check; generated-config freshness gate; `doctor --gates` 8/8 PASS; pinned Pi **1.3.0** (`bin/soveryn-pi130`, rollbacks pi120/pi110/pi104/pi103/pi100/pi099/pi087) |
| Citizens commissions + standing objectives | **Live 2026-10-19** |
| Delegation engine (`execute_task` → worktree → worker → acceptance → human approve) | **Live 2026-10-19** — worker drains every 5s; review gate `/api/delegation/pending`. **6 tasks sit in `in_review`** — 4 are redundant house_diag duplicates (18eebfdc, 0c2ca529, 0840b1e8, 0587ec8d) plus b6596b58, 45eb1664. Nothing merges without Jon's approve |
| Night fixer (`soveryn-night-fixer.timer`, 03:30) | **Live 2026-10-19** — nightly suite run, failing test files become templated dispatches (denylist + dedupe, cap 2/night). Critic prose deliberately NOT parsed; this source is deterministic |
| Night librarian (`soveryn-night-librarian.timer`, ~03:04) | **Live 2026-10-19** — lattice maintenance pass |
| Medic (`soveryn-medic.timer`) | **Live 2026-10-19** — fleet auto-heal actuator, green actions only, never touches routers |
| Ares (`soveryn-ares.service`) | **Live 2026-10-19** — host sentinel, detection-only, no LLM |
| Eyes (`soveryn-eyes.service`) | **Live 2026-10-19** — screen presence on trust (Jon's offer, revocable) |
| Embeddings / Lattice Librarian (`soveryn-embeddings.service` `:8096`) | **Live 2026-10-19** — Nemotron-3-Embed-8B on helper Quadro |
| F5-TTS (`soveryn-f5tts.service` `:8088`) | **Live 2026-10-19** — Aetheria local voice |
| SearXNG (`soveryn-searxng.service` `:8095`) | **Live 2026-10-19** — metasearch, 200 |
| X Feed worker (`soveryn-x-feed.service`) | **Live 2026-10-19** — house @Soveryn_AI feed |
| Xid capture + verdict (`soveryn-xid-capture.service`; `soveryn-xid-verdict.timer` inactive) | **Capture live 2026-10-19**; verdict timer **inactive/disabled** — Blackwell RC-watchdog forensics lane |
| Thermal (`soveryn-thermal.timer`) | **Live 2026-10-19** — one reading per cycle, appended |
| Router Quadro (`soveryn-router-quadro.service` `:8091`) + CX-7 proxy (`soveryn-cx7-8091-proxy.service`) | **Live 2026-10-19** — llama-server multi-model router on Quadro CUDA1; CX-7 proxy exposes it to Spark at `10.10.10.1` only |
| House security sweep (`soveryn-security-sweep.timer`, Sun 09:00) | **Runs weekly, exits 1 2026-10-19** — gitleaks + pip-audit + backup freshness + endpoint health → `docs/ops/security/SECURITY-LATEST.md`, webpush on findings. **The unit is marked `failed` every cycle because it exits 1 whenever findings exist** (last: `pip-audit not importable; skipping dependency audit`). Report is fine; the unit state is noise. Either install pip-audit in the sweep env or exit 0 with findings |
| Ledger reconcile (`soveryn-ledger-reconcile.timer`, Mon 08:30) | **Runs weekly, exits 1 2026-10-19** — books vs evidence parity → `docs/ops/tax/RECONCILE-LATEST.md`. **Same pattern: `_main()` returns 1 when `report["clean"]` is false**, so open receipts (NEED_RECEIPT items, undated planning lines) mark the unit `failed`. Report is doing its job; the exit code conflates "found work" with "broken" |
| Backup + restore drill | **Live 2026-10-19** — cron 04:00 nightly (38 DBs, 1.7G, 99 easystore snapshots, 284G); secrets/ + docs-ops ship as AES-256 archive only. Restore drill Sundays 05:00 |
| House clock + calendar | **Live 2026-10-19** — `python -m soveryn.platform.house_clock`; `docs/ops/HOUSE-CALENDAR.md` |
| Eve marketing cadence | **Live 2026-10-19** — Mon/Thu Canva + Signal (automation auto-Allow) |
| Eve interactive compose | **Live 2026-10-19** — Messages Gate **Allow → Signal** (caption + image) |
| Eve CWG Instagram desk | **Session live 2026-10-19.** `eve_ig_post` Gate-only (never cadence). Pics: `~/Desktop/CWG-Instagram`. Profile `data/eve_ig_profile/` |
| Eve CWG Google Business | **Wired, not armed 2026-10-19.** `eve_gbp_post` Gate-only. OAuth: `python -m soveryn.platform.gbp authorize`. Tokens `data/gbp/` |
| Agent browser desks | **Live 2026-10-19** — persistent Chrome per agent under `data/desks/<agent>/<seat>/chrome` (eve present). **No auto-spend.** |
| Eve X | **Live 2026-10-19** — house @Soveryn_AI (`read_x` / `post_to_x`). Stages until Jon says `post it`. **Aetheria off X** |
| House improvement scan | **Live 2026-10-19** — Mon/Wed/Fri |
| Canva Connect | **Live 2026-10-19** — tokens local-only |
| Messages / CoS | **Live 2026-10-19** — default `/` door; PWA + Web Push on (Gate / needs-you / brief ready); Signal = Aetheria-only |
| Verification gate | **Live 2026-10-19** — owner: Eve (default was Vett; repointed 2026-09-01, `58cb1e9`) |
| Lounge (`data/rooms/lounge.json`) | **Created 2026-09-24, unused 2026-10-19** — pointer exists, 0 wall_notes, no peers active. Calendar dated it 2026-09-25; it never became a working group chat |
| Undocumented trial lanes | **Live 2026-10-19, no owner** — `:8097` llama-server `mellum2.1` (`llama.cpp_head/build-cuda131`, `~/mellum-trial`); `:8193` ComfyUI (`ablit-bake/cwg-ming-vs-qwen-20261003`); `:8123` `python -m http.server` from `~/pondpro`; `:19200` `cwg_pdf_proxy.py` **running from `/tmp`** (survives reboot only by luck) |
| PondWright access proxy | **Live 2026-10-19** — `:18100`–`:18500` from `~/access-logs/pondwright_access_proxy.py` |
| Pondviz (`cwg-pondviz`) | **Live 2026-10-19** — uvicorn on Tailscale `100.71.129.32:8771` |

### Teammates — `~/teammates`
| Surface | Status |
|---------|--------|
| Critic + Scout overnight (`teammates-scheduler.service`) | **Live 2026-10-19** — cron; briefs → Messages. Critic `02:00`, Scout `07:30` ET |
| Console (`teammates-console.service` `:5075`) | **Live 2026-10-19** — background / operator only; **not** a product UI |
| Bridge | `POST /api/internal/teammates_brief` (localhost) | 2026-10-19 |
| Repo | `feat/phase-0` @ `83ce7e0` | 2026-10-17 |
| Marketer interactive / `:5075` as product UI | **Deprecated** — posts via Messages → Eve | 2026-10-19 |

### Public Spark (spark2 `gx10-a733`, GB10)
| Product | Status |
|---------|--------|
| Seneca `:8400` | **Live 2026-10-19** — lead capture wired → Toni notify (root 404, app routes serve) |
| PondWright `:8200` | **Live 2026-10-19** (root 404, app routes serve; `pondwright.com` 301 → canonical) |
| Atticus `:8500` | **Live 2026-10-19** — History's Ledger fact-guard, 200 |
| Shepherd FCC UI `:5055` | **Live 2026-10-19** — 401 behind auth gate (as designed); shepherdfcc.com 401; repo `~/shepherd` |
| PondWright SMTP relay | **Live 2026-10-19** — SSH reverse relay: Spark `:2465` → tower → smtp.gmail.com:465 |
| PondWright SSH forwards | **Live 2026-10-19** — tunnel plumbing for crm/estimator/pondwright domains |
| PondWright CRM ops (tower) | **Live 2026-10-19** — invoices shipped; known open: starlette major upgrade (sweep finding), `/lead` rate limit |
| Spark2 systemd | **No `soveryn*` user units 2026-10-19.** Model lanes run as plain processes (`tf-dsv41-lanes` tensorfold), not units |
| Spark1 `gx10-5725` | **Live 2026-10-19** — only `soveryn-agent.service`. **`:8001` is NOT listening** (GLM is not parked; it is down). Ollama `:11434` serves qwen2.5:14b, gemma3:27b, gemma3:12b |

### Brains
| Lane | Where | Verified |
|------|-------|----------|
| **Kernel (build brain)** | **deepseek** — `DeepSeek-V4.1-Flash-1017` EXL3 2.9bpw (EAQ v1), tensorfold on spark2 `:8888`, reached via tower SSH tunnel `127.0.0.1:8888`. `~/.soveryn/kernel_brain` = `deepseek`. Thinking off; compaction on | 2026-10-19 |
| **GLM `:8001`** | **PARKED 2026-10-19 (Jon: park for now), profile-only.** Not listening on either Spark — this was never a clean park, the serve is gone. `profiles.glm.enabled=false` with `disabledReason`. No SSH, no serve swap: Flash-Next stays stopped. Unpark is owner-gated and needs both Sparks | 2026-10-19 |
| Aetheria | Quadros `:8091` CUDA1 llama-server router (`qwen38` alias `aetheria`) | 2026-10-19 |
| Eve + public Qwen | Blackwell `:8090` vLLM Qwen 3.8-27B NVFP4 (`eve`/`qwen38`/`bench-flash`) | 2026-10-19 |
| Cognition | `:8089` Gemma 4 26B-A4B Q5, CPU-only, alias `dream` | 2026-10-19 |
| Flash-Next `:8888` (profile `flash`) | **PARKED 2026-10-08, profile disabled.** Note: the `:8888` *port* is now the deepseek lane — the flash profile must not be re-enabled blind | 2026-10-08 |
| Second Spark | **LIVE** — serving the tensorfold deepseek lanes | 2026-10-19 |
| House overnight rule | Overnight agents hand findings to Kernel as instructions; never launch harnesses against unprobed endpoints (SOVERYN.md) | 2026-10-19 |

### Repo census (verdicts per Jon 2026-09-22 — unchanged)
| Repo | Verdict | Verdict date |
|------|---------|--------------|
| american-history-app, historys-ledger, historysledger-site | **LIVE products** — History's Ledger + Atticus fact-guard (Atticus `:8500`) | 2026-09-22 |
| carolinawatergardens, pondwright-cwg-ops, pondpro, pondwright-agent | **LIVE** — CWG + PondWright estate | 2026-09-22 |
| acttruth, acttruth-site | **LIVE** — ActTruth budget/product (`acttruth.com` 200) | 2026-09-22 |
| teammates, shepherd | **LIVE** — Critic/Scout + FCC UI `:5055` | 2026-09-22 |
| soveryn_vnext, soveryn-agent, pondwright-crm (legacy) | **LIVE / superseded** — house core; legacy CRM kept for history only | 2026-09-22 |
| llama.cpp, llama.cpp_head, llama.cpp_eval, llama.cpp_qwen4exp, llama-cpp-python, ComfyUI | **TOOLING / experiments** — not products | 2026-09-22 |
| tgthrmess-app, tgthrmess-site | **LIVE** — TGTHRmess, family product (site 200, Messie `:5066`, nightly backup timer) | 2026-09-22 |
| atticus | **LIVE** — History's Ledger corpus + fact-guard | 2026-09-22 |
| sealed | **ACTIVE DEV** — onchain quote-proof (Monad QuoteSeal, keccak256 hash-only) | 2026-09-22 |
| self-report-eval | **ACTIVE RESEARCH** — feeds the honesty paper | 2026-09-22 |
| soveryn-site | **LIVE** — soverynintelligence.com (200) | 2026-09-22 |
| soveryn_cathedral | **ARCHIVE** — superseded by soveryn_vnext lattice; keep for history | 2026-09-22 |
| legacy memory stores | **ARCHIVED to easystore** — `~/soveryn_memory` + June 10 tarball, byte-identical, nothing live referenced them | 2026-09-22 |

---

## 2. Incomplete / blocked
*Last observed: 2026-10-19.*

| Item | State |
|------|-------|
| Citizen email | **CONTRADICTION — needs Jon 2026-10-19.** Prior truth said NOT ARMED with the latch off. Observed: `.env` in `soveryn_vnext` sets `SOVERYN_EMAIL_PRODUCTION=1`. Either the checklist in `docs/notes/2026-08-23-citizen-email-identity.md` §Ops checklist was completed and truth was never updated, or the latch was flipped early. Egress is the risk; confirm before treating citizen email as armed or unarmed |
| GLM `:8001` | **PARKED 2026-10-19** — profile disabled, serve absent. Unpark is owner-gated and needs both Sparks | 2026-10-19 |
| Cathedral public DNS | **Blocked on Jon 2026-10-19** — `cathedral.soverynintelligence.com` does not resolve; CNAME → `85970537-f4aa-40cf-b616-c5f185e2ae81.cfargotunnel.com` not added in the CF dashboard |
| Delegation `in_review` backlog | **6 tasks 2026-10-19** — 4 redundant house_diag duplicates (18eebfdc, 0c2ca529, 0840b1e8, 0587ec8d; the break is closed by `de72ca7`) + b6596b58, 45eb1664. Needs approve/reject sweep |
| Sweep + reconcile unit state | **Cosmetic but misleading 2026-10-19** — both timers exit 1 whenever findings exist, so `systemctl` shows `failed` weekly. A real break would look identical |
| Vett patrol daemon | **RESOLVED 2026-10-19** — disabled + stopped; lane owned by Eve via `funding-watch` skill | 2026-10-19 |
| Stray `/tmp` service | **Live 2026-10-19** — `cwg_pdf_proxy.py` runs from `/tmp` on `:19200`; `/tmp` is not durable |
| Representation quality gate | **Open 2026-10-19** — daemon is LIVE again since 2026-10-04, but outputs still read shallow/repetitive; the gate before leaving dry-run has not been defined |
| CoS rename | **Deferred** — Aetheria still `COS_ID` | 2026-10-19 |
| Eve Allow → Signal | **Done 2026-08-24** — interactive Gate; Meta IG still later |
| Critic → Aetheria commissions | **Live + E2E 2026-08-25** — `read_overnight_brief` → `house_post_send` → commission queued |
| CWG brand | **Locked:** oasis/serenity/wildlife — not catalog pricing | 2026-10-19 |
| Memory / identity layer | **2026-08-25** — pinned + persona spine; journal/heartbeat recall demoted to Channel B (not “I remember…” essays) |
| Lounge group chat | **Built, never used 2026-10-19** — pointer from 2026-09-24, 0 wall_notes |

---

## 3. Brands (one place)
*Last observed: 2026-10-19.*

| Brand | Owns | Voice | Last observed |
|-------|------|-------|---------------|
| **SOVERYN** | House, citizens, Kernel, Messages | Quiet confidence | 2026-10-19 |
| **CWG** | Carolina Water Gardens craft | Oasis / serenity / wildlife | 2026-10-19 |
| **PondWright** | Quote/CRM for CWG | Product honesty | 2026-10-19 |
| **ActTruth** | Ledger / spend honesty | Cite-or-stop | 2026-10-19 |
| **History’s Ledger / Atticus** | Corpus / history | Precise, receipts | 2026-10-19 |

---

## 4. Kill list
*Last observed: 2026-10-19.*

1. ~~Rotate source of authority~~ → this file  
2. ~~Secrets/state backup~~ → runbook + drill PASS  
3. ~~Seneca lead capture~~ → `docs/leads/seneca-leads.csv` (retroactive 08-24)  
4. ~~Citizen email~~ → **contradiction open, see §2** — gated checklist in `docs/notes/2026-08-23-citizen-email-identity.md` §Ops checklist (step count single-sourced there)  
5. ~~House spine~~ → **§0 locked 2026-08-24**  
6. Keep this file short when state changes  
7. ~~Full re-observe~~ → **2026-10-19**, 21 days after the previous one; the missed-Monday rule fired twice and the brain row was wrong for the whole window

**Next (when Jon says go):** GLM re-seat or profile disable; cathedral CNAME; delegation backlog sweep; Meta IG / CRM parked.

Runbooks (not kill-list copies): `docs/runbooks/secrets-state-backup.md` · `docs/runbooks/env-var-map.md` · incident template `docs/notes/INCIDENT-TEMPLATE.md` · **internal** SOVERYN quote skeleton `docs/ops/soveryn-quote-skeleton.md` (not public; Seneca does not quote dollars).

---

## 5. Git / ops
*Last observed: 2026-10-19.*

| Repo | Branch / tip |
|------|----------------|
| `soveryn_vnext` | **`main` @ `8eb581a` (2026-10-19)** — synced with `origin/main`. Working tree clean except untracked `AGENTS.md` at repo root |
| `teammates` | **`feat/phase-0` @ `83ce7e0` (2026-10-17)** — overnight + Messages bridge |

### Branch census (2026-10-19 — Jon verdicts needed)
| Branch | Unique commits vs `main` | Last commit | Verdict |
|--------|--------------------------|-------------|---------|
| `soveryn-messenger-v1` | 0 | 2026-06-16 | **Delete** — pure ref noise |
| `publish/honesty-paper` | 0 | 2026-07-26 | **Delete** — content already on `main` |
| `feat/delegation-worktree-isolation` | 0 | 2026-07-09 | **Delete** |
| `feat/soveryn-ai-presence` | 0 | 2026-07-14 | **Delete** |
| `feat/mission-control-spark-tile` | 0 | 2026-09-24 | **Delete** — the old §5 tip pointer; merged long ago |
| `feat/steward` | 1 | 2026-07-01 | **Jon's call** — grant-compliance funding board, never landed |
| `spike/swappable-brain` | 2 | 2026-06-22 | **Jon's call** — local-vs-cloud persona eval spike |
| `predeploy-wip-20261002` | 3 | 2026-10-02 | **Jon's call** — pre-deploy WIP snapshot; likely already superseded by `f9b02c3` |

Notes in `docs/notes/` are **not** authority. **This file is.**

<!-- integrity footer (2026-10-19 re-observe, Kernel) -->
<!-- Expected sections: §0 House spine, §1 What is live, §2 Incomplete/blocked, §3 Brands, §4 Kill list, §5 Git/ops. -->
<!-- Last full-rotation checksum: re-derive with `git show HEAD:docs/CURRENT_TRUTH.md | sha256sum` after this rotation lands. Rotation date: 2026-10-19. -->
END-OF-TRUTH §5


