# SOVERYN vNext — Slop Inventory

| Field | Value |
|-------|-------|
| **Date** | 2026-08-11 |
| **Scope** | `/home/jon-deoliveira/soveryn_vnext` (static tree + recent live findings) |
| **Purpose** | Single place for “what’s wrong / half-done / contradictory” so we stop re-discovering it |
| **Status** | Snapshot — not a fix plan; use as triage backlog |

---

## How to read this

| Severity | Meaning |
|----------|---------|
| **Critical** | Can break fleet, silence agents, leak secrets, or reintroduce known 504s |
| **High** | Major drift / half-wired product surface |
| **Medium** | Real debt; fix when touching the area |
| **Low / Nit** | Hygiene, comments, museum leftovers |

**Not slop (intentional):** Memory Grades list/detail bounds, history-only budget (fixes starvation; does *not* fix GPU prefill), dry-run defaults that protect writes until env flipped, vendor TODOs under `vett/harness/vendor/`.

---

## Executive summary

vNext is a real multi-agent fleet that grew faster than its SSOT. The highest-cost slop is **not** TODOs in code — it is:

1. **Serving path is an order of magnitude too slow** on Blackwell (prefill ~43–100 tok/s) — root of heartbeat 504s; memory compression is secondary.
2. **Multiple router preset copies** — one with `cache-ram = 0` can undo the warm-cache fix.
3. **Port / model alias collisions** for cognition (`:8089` vs `:8091`, model `"dream"` vs `"cognition"`).
4. **Secrets live in `.env` on disk** (gitignored but backup-risk).
5. **Systemd units in repo ≠ units actually installed**; museum paths (`soveryn_complete`) still appear in templates.
6. **Presence agent sources deleted, bytecode left** — half-wired.
7. **Dual DB paths** (messenger, conversations) invite split-brain.
8. **Phase-1 stubs and NotPorted surfaces** still sit next to real daemons.
9. **Daemons default dry-run=true** — easy to think systems are “running” when they write nothing.
10. **Disk clutter:** 8 worktrees, daily backups, lattice `.bak` piles, 33G tree.

---

## Critical

### C1 — Blackwell prefill/decode performance (live)

**Evidence (router logs, 2026-08-11):** prefill ~43–97 tok/s across 57–17k tokens; decode ~14 tok/s. Expected on RTX PRO 5000 + 31B Q6: prefill hundreds–thousands tok/s, decode ~40–50.

**Ruled out:** stale code, wrong GPU, missing sm_120, CPU spill (ngl=99), thermal, power, PCIe (idle downtrain), recent Xid-8.

**Strongest remaining suspect:** `swa-full` + quantized KV (`cache-type-k/v = q8_0`) + flash-attn on Gemma-4 SWA attention path. Live blackwell preset currently has `swa-full = false` (experiment comment) + `cache-ram = 32768` — confirm whether that A/B was completed and measured.

**Why it matters:** At 97 tok/s, even a “fixed” 8k prompt is still ~90s. Memory grades help product quality; they do **not** fix this class of timeout.

**Related:** `runtime/router-presets-blackwell.ini`, llama-server child flags.

---

### C2 — Router preset multi-copy + `cache-ram = 0` landmines

| Path | cache-ram | Note |
|------|-----------|------|
| `runtime/router-presets-blackwell.ini` | **32768** | Intended live Aetheria |
| `runtime/router-presets.ini` | **0** | Combined/stale — **dangerous if loaded** |
| `data/router-presets.ini` | **0** | Runtime noise copy |
| `docs/runtime-config/router-presets.ini` | absent/minimal | Docs claim SSOT, path still mentions `soveryn_complete` |
| Multiple `runtime/*.bak-*` | various | Bak pile |

**Why it matters:** Overwriting live blackwell with a `cache-ram = 0` preset re-creates cold re-prefill → heartbeat 504s (documented 2026-08-10/11).

---

### C3 — Secrets on disk in `.env`

`soveryn_vnext/.env` is gitignored but contains live API keys/tokens/passwords (Gmail, Google AI, Telegram, ElevenLabs, etc.).

**Do not commit. Do rotate** if tree was ever synced, snapshotted unencrypted, or shared. Prefer vault / `~/.config` outside the repo. Audit `backups/` for copied `.env`.

---

### C4 — Cognition port / alias identity crisis

| Source | Says |
|--------|------|
| `config/runtime.py` | cognition `:8091`, alias path “cognition” |
| `agents/dream/config.py` | default `http://127.0.0.1:8089` |
| `agents/cognition/runner.py` | `DEFAULT_COGNITION_URL = …:8089` |
| `agents/representation/config.py` | fallback `:8089` |
| `dream/cognition.py` / `representation/cognition.py` | `"model": "dream"` |
| Router / units | may expose `cognition` / `aetheria-cognition`, not `dream` |
| Quadro router | also uses `:8091` for multi-model |

**Why it matters:** Dream / cognition cycle / representation can hit empty ports or wrong aliases even when “services are up.”

---

### C5 — Committed `systemd/soveryn-router.service` still museum-path

Repo unit may still point `WorkingDirectory` / preset at `~/soveryn_complete/…` while production is vnext blackwell/quadro split. **Installed** user units under `~/.config/systemd/user/` may differ — but the repo template is a footgun for reinstall.

---

## High

### H1 — Systemd inventory drift

| Script / registry | Reality |
|-------------------|---------|
| `scripts/install_systemd_units.sh` | Only subset (router, vnext, ares, cognition-instance…) |
| `scripts/soveryn-restart.sh` | Expects heartbeat, dream, signal-bridge, vett-patrol, searxng, cognition |
| `RUNTIME_SERVICES` in `runtime.py` | Declares many systemd launches |
| Repo `systemd/` | Incomplete vs live `~/.config/systemd/user/` |

**Why it matters:** Fresh install / reinstall cannot rebuild the fleet from the repo alone; names drift (`soveryn-dream` vs timer names).

---

### H2 — Presence agent half-wired

Under `soveryn/agents/presence/`: stores/tools/workers partially present; **sources missing** for modules still referenced by plans (e.g. `daemon.py`, `approval.py`, `aetheria_bridge.py`, …) with **only `.pyc` left** in places.

**Why it matters:** `ImportError` or zombie bytecode; X presence path fragile.

---

### H3 — `docs/CURRENT_TRUTH_2026-05-23.md` is not current

Still describes early Phase-1 world (Qwen ports, in-process heartbeat, etc.). README points at it as authority → **documentation split-brain**.

---

### H4 — Dual databases (split-brain risk)

| Path | Status |
|------|--------|
| `data/memory/conversations_vnext.db` | Live (~18M) |
| `data/conversations.db` | Orphan / old (44K) |
| `data/messenger.db` | Live (startup) |
| `data/memory/messenger.db` | Likely orphan empty |
| Multiple lattice backups | `.bak-before-legacy-reclass`, `.pre-nemotron-*` |

---

### H5 — Scotty under-provisioned vs Vett

In `app/startup.py`: Vett gets `max_tokens=8192`, `chat_timeout_seconds=300`. Scotty keeps AgentLoop defaults (`max_tokens=2048`, `timeout=120`) while delegation path uses higher limits.

**Why it matters:** Same class of mid-tool-call truncation already fixed for Vett/Aetheria can still hit interactive Scotty.

---

### H6 — Compat API stubs look healthy but empty

`app/routes/compat.py`:

- `/api/message_board` — `_stub: true`, empty
- `/api/research_journal` — empty
- TODOs: memory evidence, vision WebSocket

**Why it matters:** UI can show empty boards forever without error.

---

### H7 — Phase-1 `*NotPortedError` fossils next to real daemons

| File | Reality |
|------|---------|
| `aetheria/heartbeat_surface.py` | Raises; real heartbeat is `agents/heartbeat/` process |
| `scotty/repair_surface.py` | Raises; real path is tools/delegation |
| `vett/research_surface.py` | Raises; real path is tools/harness |
| `ares/daemon.py` | `AresDaemonNotPortedError` class leftover while daemon works |

---

## Medium

### M1 — Memory Grades incomplete (by design stages)

| Piece | Status |
|-------|--------|
| PR0 content_caps | Landed |
| PR1 list/detail tool bounds | Landed |
| PR5 history-only 6k + soul origin | Landed |
| PR2 write_node caps | **Not landed** — still no length policy on store |
| PR3 heartbeat distill / standing note | **Not landed** — still full essays as reflections |
| PR4 dream clamp + archive | **Not landed** |
| `resolve_full_text_ref` | **Stub always returns None** |

Also: PR5 **grows** worst-case total prompt (~3.5k prelude + 6k history ≈ 9.5k vs old shared 8k). Correct for starvation; slightly wrong direction for prefill until serving is fixed.

---

### M2 — Daemons default dry-run = true

| Component | Default |
|-----------|---------|
| Dream | `SOVERYN_DREAM_DRY_RUN` default true |
| Cognition cycle | dry-run default true; cycle enabled default false |
| Representation | `dry_run=True` |
| Vett patrol | `SOVERYN_VETT_PATROL_DRY_RUN` default true |
| Ares CLI | dry_run default true |

**Why it matters:** Units “active” but write nothing unless env flipped; false sense of learning/patrol.

---

### M3 — Silent exception swallows (first-party)

- `signal_bridge/tools.py` — audit DB write fail → `except Exception: pass` (comment claims logging, no log)
- `platform/delegation/tools.py` — duplicate-task guard fails open silently
- `representation/writeback.py` — embed fail → `embedding=None` without log

(Many other `except Exception` sites correctly `logger.exception` — fail-open by design.)

---

### M4 — Import dualism (shims)

| Package | Role |
|---------|------|
| `soveryn.platform.inference` | Real implementation |
| `soveryn.inference` | Compat re-export (“Phase 1 migration”) |
| `soveryn.memory` | Still live conversation_store + lattice shim |
| `soveryn.platform.lattice` | Lattice truth |

Tests and loop still import both styles. Works, but confuses “where to edit.”

---

### M5 — Disk / worktree / backup clutter

| Item | Scale |
|------|-------|
| Tree size | ~**33G** |
| `.worktrees/` | **8** full UUID trees (gitignored, still huge) |
| `backups/2026-08-*` | Daily full data snapshots |
| Lattice/conversation `.bak` / `.pre-*` | Multi-hundred-MB each |

---

### M6 — Shepherd: design without agent

Four specs + plans; surface may exist on `:5055` / public domain; **no** `soveryn/agents/shepherd/` package in vnext.

---

### M7 — Duplicate / stale dream specs

- `2026-06-01-dream-daemon-vnext.md` vs `2026-06-05-dream-daemon-design.md` (latter supersedes) still both present.

---

### M8 — Hardcoded reflection URL

`reflection/tools.py` hardcodes `http://127.0.0.1:8091` + model `reflection` instead of `MODEL_SERVERS` / env.

---

### M9 — Medic unit embeds Signal numbers

`runtime/soveryn-medic.service` has phone numbers in `Environment=` (PII / coupling).

---

### M10 — Vendor harness debt

`agents/vett/harness/vendor/**` ~15 TODOs + HACKs, OpenAI embedding names, high grep limits. Upstream-ish; don’t churn unless forking.

---

## Low / nit

- Package `__init__.py` / policies still say “Placeholder; later vNext step”
- `app/routes/ui_compat.py` — legacy template bridge note
- `messenger/delivery_worker.py` — stderr print vs logger; “stub until real push”
- `router-presets.ini` header still mentions `:8080`
- Redundant Aetheria `history_token_budget` / `context_window` re-assignment in startup (same values as fleet)
- Stale comments: “8k history”, “65536 n_ctx”, Vett pre-Spark narrative
- Soul bak: `aetheria.md.bak-2026-06-17-pretrim`
- `config/runtime.py.bak-*` files next to live SSOT
- Paper scripts: dual `verify_paper_claims*.py`
- Scratch: `scratch/spark_vett_chat.py` outdated ports
- Integration/rig tests skipped by default (intentional) — no CI gate guaranteeing they run

---

## First-party TODO ticket list (product)

From `app/routes/compat.py` / `ui_compat.py`:

1. `TODO(vnext-memory-evidence)` — memory router
2. `TODO(vnext-perception-ws)` — SocketIO + perception
3. `TODO(vnext-message-board)` — stub 200s today
4. `TODO(vnext-research-journal)` — stub 200s today
5. `TODO(vnext-ui)` — legacy template bridge

---

## Quantitative sketch (tree)

| Metric | Approx |
|--------|--------|
| TODO/FIXME/HACK markers in `soveryn/**/*.py` | ~29 (most vendor) |
| `NotImplemented` / NotPorted classes | 5 |
| Explicit pytest skip/xfail body | ~6 + many integration/rig gated |
| Worktrees | 8 |
| Router preset `.bak` files | 6+ |
| Silent `except: pass` (raw count noisy) | hundreds of matches including fine ones |

---

## Suggested triage order (when you have tokens)

1. **Measure / fix Blackwell serving path** (swa/KV A/B, then reboot if needed) — unblocks everything time-sensitive.  
2. **Watermark or delete dangerous presets** with `cache-ram = 0`; one live blackwell + one quadro only.  
3. **Unify cognition URL + model alias**; kill `:8089` / `"dream"` defaults.  
4. **Sync repo systemd with reality** (or document “source of units is `~/.config`”).  
5. **Presence: restore sources or delete pyc + mark abandoned.**  
6. **Rotate `.env` secrets; scrub backups.**  
7. **Scotty max_tokens + timeout parity.**  
8. **Compat stubs → 501 or implement.**  
9. **Remove NotPorted fossils or rewire names.**  
10. **Prune worktrees + old backups + orphan DBs.**  
11. **Continue Memory Grades PR2–PR4** for write-side density (after serving is sane).  
12. **Update or archive CURRENT_TRUTH**; point README at a living SSOT.

---

## Related docs / session context

- Memory design: `docs/superpowers/specs/2026-08-11-memory-grades-self-through-memory-design.md`
- Live mitigations already applied: cache-ram 32G on blackwell, Aetheria timeout 300s, tool list/detail caps, history-only 6k, soul origin off hot path
- Honest limit: **history-only budget does not shrink total prompt**; serving rate dominates timeouts

---

## What this inventory is not

- Not a claim every line of the 33G tree was hand-read  
- Not a license to delete without checking live systemd units  
- Not security rotation performed — only flagged  

---

*End of inventory. Update this file when items are fixed so the next session doesn’t re-dig the same graves.*
