# SOVERYN Current Truth

> **Source of authority for what is actually running — right now.**  
> Observed / operator-confirmed. Not aspirational. Not a phase dump.  
> Last rotated: 2026-09-22  
> Prior archive: `docs/archive/CURRENT_TRUTH_2026-05-23.md` (historical — do not treat as live).
> Staleness rule: key off the **newest per-row** "last observed" / "Last verified" date in this file, not this header date. If that newest per-row date is >7 days old, treat the file as stale and re-observe. The header "Last rotated" date is updated on every row edit to track the newest per-row date.  
> Machine check: `grep -E '^\|' docs/CURRENT_TRUTH.md | grep -oE '2026-[0-9]{2}-[0-9]{2}' | sort | head -1` — newest per-row date; if older than 7 days before today, file is stale, re-observe. Completeness check: `grep -cE '^## [0-9]' docs/CURRENT_TRUTH.md` must equal **6** (§0–§5) — freshness alone can pass on a truncated file; the section count makes truncation fail the check. Re-observe is assigned to **Kernel** (house build brain), cadence weekly — Monday morning, alongside the ledger reconcile timer.
> <!-- Staleness check: scope to | table rows only, not free-text prose dates. -->
> <!-- Staleness check: scope to | table rows only, not free-text prose dates. -->

If runtime behavior changes, **update this file first**, then code/notes.

---

## 0. House spine (locked 2026-08-24)
*As of 2026-09-15; per-row dates are the source of truth.*

**One rule:** if Jon needs it day-to-day, it shows up in **Messages**. Everything else is engine room or a satellite.

| Layer | What | Role | Last observed |
|-------|------|------|---------------|
| **Phone OS / front door** | Messages (`/` → `/messages`) | **The product.** Contacts = **MESSAGES_CONTACTS** + Critic/Scout overnight inboxes. Talk → Gate Allow/Deny in-thread. | 2026-09-22 |
| **Tower / desk** | Command Center (`/command-center`), Staff (`/citizens`), Fleet | Ops HUD — evidence & commissions; not the daily ask door. | 2026-09-22 |
| **House staff** | Citizens in `soveryn_vnext` | Execute work (commissions, Eve posts, Kernel builds). | 2026-09-22 |
| **Outside eye** | Teammates (`~/teammates`) | Critic/Scout overnight — **observe & brief**; do **not** become a second phone app. Briefs → Messages (`t_critic` / `t_scout`). | 2026-09-22 |
| **Public internet** | soverynintelligence.com, Seneca, PondWright/CWG | Customer/brand surface. | 2026-09-22 |
| **In-house tower ports** | Atticus `:8500`, TGTHRmess | **Not** confirmed public-internet products — tower ports per §1 Public Spark. Atticus is the History's Ledger fact-guard (halts when the page isn't held). Messie is Qwen3.5-9B Q6 on `:5066` (TGTHR helper), not the Quadros 27B public slot (public slot: unassigned as of 2026-09-15; no live check performed this pass). Unit: `~/.config/systemd/user/tgthrmess-messie.service` (tracked copy `~/tgthr-entries/systemd/tgthrmess-messie.service`). | 2026-09-15 |

- 2026-09-09: superseded snapshot 2026-05-23 moved to docs/archive/ — this file is the only live truth.

*These three are the surfaces the README public-surface table has actually fetched; README lists only fetched surfaces.*

### 0a. Fleet freeze — frontier few (locked 2026-08-27)
*Last observed: 2026-08-27.*
*How to verify: `nvidia-smi` shows ≤1 frontier model per card; `systemctl --user list-units 'soveryn*'` (and the `:PORT` listeners in §1) list the live agent services.*

**Constraint:** you cannot run six frontier minds and six personas on this iron. One card → one frontier mind. Extra agents only for **different tools** or a **different clock** — never another wig on the same weights.

| Messages contact | Role | Brain |
|------------------|------|--------|
| **Aetheria** | Soul / face / judgment | Blackwell alone — Qwen 3.8-27B |
| **Kernel** | Local build | **Flash-Next `:8888` NVFP4 TP=1 active** (2026-09-17, house standard — Kernel coding brain; GLM `:8001` parked). |
| **Eve** | Research + ship (Vett folded in) | Quadros Qwen 3.8 — Canva / Signal / CWG IG |
| **Critic / Scout** | Overnight only | Teammates → inbox (not chat peers) |

Per-row verification dates — model swaps are the most common silent drift; do not trust the section-level date alone:

| Row (model/endpoint) | Last verified |
|----------------------|---------------|
| Aetheria — Blackwell `:8090` Qwen 3.8-27B | 2026-08-27 (section freeze); re-confirmed 2026-09-01 per §1 Brains |
| Kernel — Flash-Next `:8888` NVFP4 TP=1 (GLM `:8001` parked) | 2026-09-17 (Kernel — coding brain live on Flash-Next per house standard; aider/opencode runs confirm `:8888` serving) |
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
| Cognition surface (Gemma 4 26B-A4B Q5, CPU-only `:8089`, alias `dream`) | **Live** 2026-09-13 (Kernel — restarted; was silently down since ~Aug 30, starved `soveryn-representation.service` into a 4.8k-restart loop) |
| Representation daemon | **PARKED 2026-09-22** — was stuck in a 7,921-restart loop since Sep 14: its readiness gate waits for the cognition brain on :8089, and cognition was intentionally stopped+disabled Sep 14. `systemctl --user disable --now soveryn-representation.service`. Re-enable BOTH together (`soveryn-cognition.service` + this) when the dream/representation experiment resumes. Quality gate before leaving dry-run still open (outputs read shallow/repetitive) |
| Service crash watch (`soveryn-crash-watch.timer` 15min + automation `service_crash_watch` 30min, monitor-mode) | **Live** 2026-09-13 — deterministic `scripts/systemd_health_watch.py` writes `data/automations/watches/systemd_health.txt` only on failed/activating/NRestarts≥10 units; unchanged file = no LLM, change = Aetheria briefs Jon. Canary-tested (caught + cleared) |
| SOVERYN CLI harness hardening | **Live** 2026-09-13 (Kernel) — `doctor --json` (machine-readable health/drift/gates, exit 1 on problems — house monitors can consume); parked-but-live drift check; generated-config freshness gate (`config/pi` + `config/soveryn-cli` audited per-harness vs profiles SSOT); `npm test` 25/25 (`packages/soveryn-cli/test/`) |
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
| Deep Cognition Cycle (`soveryn-cognition-cycle.service`) | **Live** — Aetheria reflect → process → distill loop (added to truth 2026-09-22; was running undocumented) |
| House security sweep (`soveryn-security-sweep.timer`, Sun 09:00) | **Live 2026-09-22** — gitleaks across house repos + pip-audit (house requirements) + backup freshness + endpoint health; report `docs/ops/security/SECURITY-LATEST.md`, webpush on findings. gitleaks pre-commit hooks on all house repos |
| Ledger reconcile (`soveryn-ledger-reconcile.timer`, Mon 08:30) | **Live 2026-09-22** — books vs evidence parity; report `docs/ops/tax/RECONCILE-LATEST.md`, webpush on drift |
| Backup encryption | **Live 2026-09-22** — secrets/ + docs-ops ship to easystore as AES-256 archive only (NTFS = no permissions; plaintext mirrors purged). Passphrase `~/.soveryn/house-keys/easystore-archive.key`, tower-only. Backup now covers docs/ops tax books + mirrors PondWright CRM ops.sqlite from Spark |
| verify gates + DEPLOY.md | **Live 2026-09-22** — `scripts/verify.sh` in soveryn_vnext + pondwright-cwg-ops; DEPLOY.md in vnext/CRM/site repos; deploy-discipline rules in SOVERYN.md. Known red resolved 2026-09-24: `test_delegation_end_to_end_isolation` passes (2/2) |
| Vett patrol (`soveryn-vett-patrol.service`) | **PARKED 2026-09-22 (Jon: hand to Eve)** — daemon ran since Sep 14 but never recorded a source visit (state table never created); desk silent since Aug 24; Vett folded into Eve Sep 1. Sources + verify-or-say-nothing standard inherited by Eve as automation `funding_watch` (daily 08:00, skill note `data/memory/skills/eve/funding-watch.md`). Patrol daemon + sources YAML kept in repo for a future deterministic crawler |
| House clock + calendar | **Live 2026-09-22** — `python -m soveryn.platform.house_clock`; `docs/ops/HOUSE-CALENDAR.md` shared calendar (reconcile Mon 08:30, security Sun 09:00) |
| Delegation engine (`execute_task` → worktree → worker → acceptance → human approve) | **Live 2026-09-24** — first production loop proven end-to-end: dispatch 1aee02d1 (house_look receipt retention) executed in an isolated worktree by the worker on the Spark vLLM, acceptance gate caught two bad deliveries (skills-gate crash, mangled f-string) before a green run reached `in_review`; Kernel reviewed, Jon approved, merged to main (def2319), verify GREEN, pushed. Fixes en route: `server_override` for folded-agent model binding, skills fail-soft for worker lanes, round-budget + py_compile instructions in the worker directive. The old Scotty desk stays folded — the engine runs headless, no chat persona needed. Dispatch via `DelegationStore.create_task` (worker drains every 5s); review gate at `/api/delegation/pending` + approve/reject |

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
| Shepherd FCC UI `:5055` | **Live — added to truth 2026-09-22** (was running undocumented). shepherdfcc.com via pondwright tunnel; repo `~/shepherd` |
| PondWright SMTP relay | **Live — added 2026-09-22** (undocumented before). SSH reverse relay: Spark `:2465` → tower → smtp.gmail.com:465 |
| PondWright SSH forwards | **Live — added 2026-09-22** (undocumented before). Tunnel plumbing for crm/estimator/pondwright domains |
| PondWright CRM ops (tower) | **Live 2026-09-22** — invoices shipped (quote-linked invoice editor, printable `/invoice/{id}`, INV numbering); `python-multipart` 0.0.31 security bump deployed. Known open: starlette major upgrade (sweep finding), `/lead` rate limit |

### Brains
| Lane | Where |
|------|--------|
| Aetheria | Blackwell `:8090` — alone |
| Kernel | **GLM-5.3-Flash EXL3 TP=2 `:8001` — LIVE 2026-09-22 (observed serving; spark2 116/121 GiB resident). Took over from Flash-Next ~2026-09-13. `~/.soveryn/kernel_brain` = `glm`.** |
| Eve + public Qwen | Quadros `:8091` Qwen 3.8-27B |
| Flash-Next `:8888` | **PARKED 2026-09-22 (observed: endpoint down).** NVFP4 TP=1, spark2. Tunnel unit `soveryn-spark2-flashnext-8888.service` still running (forward only, backend down). Re-park per lab. **Gotcha (two-week leak, fixed 2026-09-22):** overnight jobs launched aider against this parked endpoint; `soveryn-aider --kernel` now reads `~/.soveryn/kernel_brain` and probes before start |
| Second Spark | **LIVE — serving the GLM TP=2 half** (not parked; `:8001` spans both Sparks) |
| House overnight rule | Overnight agents hand findings to Kernel as instructions; they never launch harnesses against unprobed endpoints (SOVERYN.md, 2026-09-22) |

### Repo census (2026-09-22 — verdicts per Jon)
| Repo | Verdict |
|------|---------|
| american-history-app, historys-ledger, historysledger-site | **LIVE products** — History's Ledger + Atticus fact-guard (Atticus `:8500`, Public Spark) |
| carolinawatergardens, pondwright-cwg-ops, pondpro, pondwright-agent | **LIVE** — CWG + PondWright estate (see §1 Public Spark) |
| acttruth, acttruth-site | **LIVE** — ActTruth budget/product |
| teammates, shepherd | **LIVE** — Critic/Scout + FCC UI `:5055` |
| soveryn_vnext, soveryn-agent, pondwright-crm (legacy, superseded by cwg-ops) | **LIVE / superseded** — house core; legacy CRM repo kept for history only |
| llama.cpp, llama.cpp_head, llama.cpp_eval, llama.cpp_qwen4exp, llama-cpp-python, ComfyUI | **TOOLING / experiments** — inference engines and eval clones; not products |
| tgthrmess-app, tgthrmess-site | **LIVE** — TGTHRmess: built for Jon's sister, her app (site 200, Messie :5066 helper, nightly backup timer). Family product — treat as a customer-owned deployment, not a house lab |
| atticus | **LIVE** — History's Ledger corpus + fact-guard (WWI rework Sep 17; Atticus :8500) |
| sealed | **ACTIVE DEV** — onchain quote-proof product (Monad QuoteSeal, keccak256 hash-only; voiceover notes Sep 17) |
| self-report-eval | **ACTIVE RESEARCH** — self-report eval harness, feeds the honesty paper (results Sep 17) |
| soveryn-site | **LIVE** — soverynintelligence.com (200; jumpgate/lab experiments Sep 17) |
| acttruth-site | **LIVE stable** — acttruth.com (200; static, low churn is correct) |
| soveryn_cathedral | **ARCHIVE** — superseded by soveryn_vnext lattice (last touched Jul 26); keep for history |
| legacy memory stores | **ARCHIVED to easystore 2026-09-22** — `~/soveryn_memory` (1 GB, pre-vnext memory) + June 10 complete memory backup tarball (947 MB) moved to `/mnt/easystore/archives/memory/`; verified byte-identical; pointer note `SOVERYN_MEMORY_ARCHIVED.txt` in home. Nothing live referenced them (compat route is a stub) |

---

## 2. Incomplete / blocked
*Last observed: 2026-08-25.*

| Item | State |
|------|--------|
| Citizen email | **Not production — NOT ARMED.** Gated checklist body is canonical in `docs/notes/2026-08-23-citizen-email-identity.md` §Ops checklist (single source for the step list and its count — this row deliberately does not restate or number the steps). Roster tiers (live/folded/teammates) are single-sourced in README §What is SOVERYN. Latch `SOVERYN_EMAIL_PRODUCTION=1` off; SMTP alone does not arm egress. |
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
4. ~~Citizen email~~ → **NOT ARMED** — gated checklist in `docs/notes/2026-08-23-citizen-email-identity.md` §Ops checklist (step count single-sourced there; §2 is the live-state pointer)  
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

---

<!-- integrity footer (2026-09-24 docs-hygiene pass 5b38f0b6/bf465b6d, landed by Kernel) -->
<!-- Expected sections: §0 House spine, §1 What is live, §2 Incomplete/blocked, §3 Brands, §4 Kill list, §5 Git/ops. -->
<!-- Last full-rotation checksum: sha256:0268cfe90913… (file as it stood 2026-09-22, 19,272 B, §0–§5) — re-derive with `git show HEAD:docs/CURRENT_TRUTH.md | sha256sum`. Rotation date: 2026-09-22. -->
