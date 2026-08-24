# SOVERYN Current Truth

> **Source of authority for what is actually running — right now.**  
> Observed / operator-confirmed. Not aspirational. Not a phase dump.  
> **Last rotated:** 2026-08-24  
> Prior archive: `docs/CURRENT_TRUTH_2026-05-23.md` (historical — do not treat as live).

If runtime behavior changes, **update this file first**, then code/notes.

---

## 1. What is live

### House (SOVERYN vNext) — tower `:5001`
| Surface | Status |
|---------|--------|
| Flask vNext (`soveryn-vnext`) | **Live** |
| Agents in `agent_loops` | **Aetheria, Vett, Scotty, Kernel, Eve** |
| Heartbeat / dream / automations | **Live** (systemd user units) |
| Citizens commissions + standing objectives | **Live** (census seeds SOVERYN+CWG work) |
| Eve marketing cadence (`eve_product_advertise`) | **Live** Mon/Thu — Canva + Signal draft-and-drop |
| House improvement scan | **Live** Mon/Wed/Fri |
| Canva Connect | **Live** (OAuth tokens local-only) |
| Messages / CoS relay | **Live** — Aetheria still wired as temporary CoS; partner tone; **rename deferred** |

### Public Spark products
| Product | Status |
|---------|--------|
| Seneca (`:8400`, ask.soverynintelligence.com) | **Live** — lead capture **not** wired |
| PondWright (`:8200`) | **Live** |
| Atticus (`:8500`) | **Live** |

### Teammates (separate repo `~/teammates`)
| Surface | Status |
|---------|--------|
| Critic + Scout Phase 0 | **Live** — console `:5075`, Tailscale phone |
| Overnight scheduler unit | Installed; enable when Jon wants unattended cron |
| Cloudflare hostname for Teammates | **Not done** (operator decision) |

### Brains (shortcuts)
| Lane | Where |
|------|--------|
| Aetheria | Blackwell `:8090` — alone |
| Kernel coding default | Quadros Flash `:8091` (`bench-flash` / DeepSeek-V4-Flash) via `soveryn-opencode` |
| Shared Spark workers | `:8001` (Vett/Scotty/PondWright/Atticus/Seneca) |
| FreeToken | **Back burner** until second Spark/ASUS brain is up |

---

## 2. What is dry-run / incomplete / blocked

| Item | State |
|------|--------|
| Citizen email (Zoho aliases, SPF/DKIM/DMARC) | **Designed, not armed** — not production |
| CoS ownership (Marshal / Eve / Kernel) | **Deferred** — Aetheria still `COS_ID` |
| Seneca structured lead capture | **Gap** — conversations.log only |
| Secrets/state backup runbook | **Done 2026-08-24** — nightly `secrets/` + easystore; `scripts/restore_secrets_drill.sh` PASS |
| Second ASUS GX10 | **Ordered — ETA Tuesday** — Kernel dedicated brain |
| CWG brand | **Locked:** oasis/serenity/wildlife — not catalog pricing |

---

## 3. Three-way product split (one place)

| Brand | Owns | Voice |
|-------|------|--------|
| **SOVERYN** | House, citizens, Kernel, Messages | Quiet confidence — we built this |
| **CWG** | Carolina Water Gardens craft / ponds | Oasis, serenity, ecosystems, outdoor beauty |
| **PondWright** | Quote/CRM tool for CWG | Product honesty (catalog/MAP when relevant) |
| **ActTruth** | Ledger / spend honesty | Cite-or-stop |
| **History’s Ledger / Atticus** | Corpus / history product | Precise, receipts |

---

## 4. Kill list (from Critic 2026-08-24 — work in order)

1. ~~Rotate source of authority~~ → **this file** (2026-08-24)
2. Secrets/state backup runbook (`.env`, `data/canva/tokens.json`, `data/memory/personas/*`)
3. Seneca lead capture on pricing/hardware gates
4. Arm citizen email end-to-end or mark “not production” everywhere
5. Keep this doc short when state changes — don’t let notes outrun it again

Then: Teammates Phase 1 (or overnight scheduler) when Jon says go.

---

## 5. Git / ops pointers

| Repo | Branch / tip (as of rotate) |
|------|------------------------------|
| `soveryn_vnext` | `feat/mission-control-spark-tile` @ `906e5f0` (+ later local) |
| `teammates` | `feat/phase-0` @ phone console live |

Detailed session notes stay in `docs/notes/` — they are **not** authority. This file is.
