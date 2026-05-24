# SOVERYN Current Truth Spec — 2026-05-23

> Authoritative description of what is actually running, right now, on this machine. Source of authority for vNext. If something in here changes, this doc changes first.
>
> **Not aspirational. Not historical. Observed.** Built from live `ps`, `ss`, `systemctl`, and the structural extracts under `/media/.../soveryn_PRESERVE_2026-05-23_174236/decompiled/`.

---

## 1. Active LLM agents

Three agents have a real in-process `AgentLoop` and respond to `/chat_stream`:

| Agent | Role | Model | Backend |
|-------|------|-------|---------|
| **Aetheria** | Human interface, in-charge | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` (+ `mmproj-BF16`) | llama-server `127.0.0.1:8085` |
| **V.E.T.T.** | R&D / research | `Qwen3.5-27B-Q8_0.gguf` (+ `mmproj-Qwen3.5-27B-F16`) | llama-server `127.0.0.1:8084` (shared with Scotty) |
| **Scotty** | Bounded executor (Aetheria directs) | `Qwen3.5-27B-Q8_0.gguf` (same instance as V.E.T.T.) | llama-server `127.0.0.1:8084` |

No other agents exist in `agent_loops` at runtime. `app.py` registers exactly these three.

---

## 2. Background daemons — observed running

Every daemon currently invoked or scheduled. Labels indicate intent:

| Process | What it does | Launch | Intent |
|---------|--------------|--------|--------|
| `ares_daemon.py` | Security daemon — runs scans, posts findings to Aetheria's inbox via `agent_message_board.post_inbox_message`. No LLM, no chat surface. | Started alongside `app.py` (or by `start.sh`) | **Active intended** (Bucket A) |
| `aetheria_stream.py` | Streaming/proprioception surface for Aetheria. Separate Python process. | Started alongside `app.py` | **Active intended** (Bucket A) |
| `AetheriaCognition` thread | In-process cognition loop. POSTs to `:8089` (Gemma-4 E4B) via `core/cognition.py`. Started by `app.py:2647-2649`, exposes `/cognition/status`. | Inside `app.py` | **Active intended** (Bucket A) |
| Heartbeat loop | Aetheria autonomous research/perception cycle. Class: `AetheriaAutonomy` (`heartbeat_integrated.py`). **Not a separate process** — thread inside `app.py`. | Inside `app.py` | **Active intended** (Bucket A) |
| `dream_daemon.py aetheria` | Nightly memory consolidation for Aetheria. Calls cognition `:8089` via `call_cognition()`. | systemd `soveryn-dream-aetheria.timer` @ **03:00** | **Active intended** (Bucket A) |
| `dream_daemon.py ares` | Nightly consolidation for Ares — purpose unclear since Ares LLM retired. | systemd `soveryn-dream-ares.timer` @ **03:15** | **Dormant** (Bucket B — investigate) |
| `dream_daemon.py tinker` | Nightly consolidation for retired Tinker agent. | systemd `soveryn-dream-tinker.timer` @ **03:30** | **Dormant** (Bucket B — disable after vNext) |
| `server.py` (Parakeet) | STT service on `:8087`. Conda env `parakeet`. | systemd `parakeet.service` | **Active intended** (Bucket A) |

---

## 3. Live port map

| Port | Bound to | Process |
|------|----------|---------|
| `5000` | `127.0.0.1` | `python app.py` (Flask) — main REST + UI |
| `8081` | `*` | Expo dev server for `soveryn_mobile/` (sibling dir, separate project) |
| `8084` | `127.0.0.1` | llama-server — Qwen3.5-27B + mmproj — V.E.T.T. / Scotty shared |
| `8085` | `127.0.0.1` | llama-server — Qwen3.6-35B + mmproj — Aetheria primary, tensor-split 0.90/0.10 |
| `8086` | `127.0.0.1` | llama-server — nomic-embed-text-v1.5.Q8_0 (`--embeddings`) — single embedding backend for the whole system |
| `8087` | `127.0.0.1` | Parakeet STT (`python server.py`) |
| `5443` | `127.0.0.1` | `python app.py` second bind — purpose unverified; investigate before vNext |
| `8089` | `127.0.0.1` | llama-server — gemma-4-E4B-it-Q8_0 — **cognition** layer (called by `core/cognition.py`, `dream_daemon.py`, `tools/dispatch_background_tool.py`). Load-bearing for memory consolidation. (Note: post-reset `config.py` re-introduces an `aetheria_public` agent on this port — that's zombie code; the live process predates the reset and serves cognition only.) |

ComfyUI (image generation, used by `tools/image_gen_tool.py`) runs separately on `8188` when started by `start.sh`. Not currently bound.

---

## 4. GPU layout (canonical UUIDs)

Reference numeric CUDA IDs only via UUID lookup. Numeric order is not stable across launch environments.

**Observed consumers (live `nvidia-smi --query-compute-apps`):**

| GPU | UUID | Resident processes / VRAM right now |
|---|---|---|
| GPU 0 Quadro RTX 8000 | `GPU-50b41c93-e957-fe4a-eb4d-001d7e7d990a` | Vett/Scotty `:8084` (29 GB) + Aetheria spillover `:8085` (5 GB, 10% of split) + embeddings `:8086` (342 MB) + `app.py` (524 MB) |
| GPU 1 Blackwell | `GPU-946b08b0-e9d3-949b-6eab-b6c5b8a5f5cd` | Aetheria primary `:8085` (35 GB, 90% of split) |
| GPU 2 Quadro RTX 8000 | `GPU-305d1801-319e-3330-d75e-0676387a91f2` | Cognition Gemma `:8089` (5.8 GB) + Parakeet STT `server.py` (5 GB) + ComfyUI when active |

**vNext intended assignment** (same as observed — keep as-is):

| GPU | Role |
|---|---|
| GPU 0 | Vett/Scotty 27B + Aetheria spillover + embeddings + Flask process |
| GPU 1 | Aetheria 35B primary |
| GPU 2 | Cognition Gemma + Parakeet STT + ComfyUI |

The old Ares LLM on `:8082` runs `-ngl 0` (CPU only) — uses no GPU. Bucket B drift.

---

## 5. Memory — single source of truth

**Lattice** is the only semantic memory system. SQLite DB at `soveryn_memory/lattice.db`.

| Layer constant | Purpose | Visibility |
|---|---|---|
| `LAYER_PRIVATE` (`'private'`) | Per-agent memory | Only that agent recalls it |
| `LAYER_GLOBAL` (`'global'`) | Shared facts | All agents recall |
| `LAYER_LIBRARY` (`'library'`) | RAG document chunks (ingested PDFs/docs) | Recalled only when explicitly searched (won't pollute conversational recall) |

Single embedding space: nomic-embed-text-v1.5 via llama-server `:8086`. No separate vector DB. No ChromaDB in the live path (migration completed 2026-05-04; orphan dirs remain on disk and should not be re-introduced in vNext).

**Non-Lattice memory surfaces** (also live):
- `soveryn_memory/persistent.db` — conversation history, tool call logs (SQLite)
- `soveryn_memory/conversations.db` — session/conversation persistence (SQLite, separate from persistent)
- `soveryn_memory/identity_state.json` — Aetheria's identity cathedral state
- `soveryn_memory/SOUL.md` — Aetheria's origin/essence (static, injected)
- `soveryn_memory/pinned_memory.md` — static facts injected every turn
- `soveryn_memory/aetheria_research_journal.md` — append-only journal
- `soveryn_memory/dream_agenda.json` — dream consolidation queue
- `soveryn_memory/ares_daemon_state.json` — live security daemon state
- `soveryn_memory/memory/<agent>/YYYY-MM-DD.md` — per-agent daily conversation logs (this dir layout since 2026-04-04)

**Backup**: `backup.sh` runs daily 04:00, writes runtime state only to `backups/YYYY-MM-DD/`. **By design skips code** — that gap is what made the 2026-05-23 reset catastrophic. vNext requirement: a code backup daemon.

---

## 6. Tool registry — ownership

Tools live in `soveryn_complete/tools/` (53 `.py` files). Registration is per-agent in `app.py`.

**Source of these assignments is best-effort:** the marshal extract of `app.py.cpython-313.pyc` gives the *registration call sites* and *tool class names* but not always the per-agent target with full fidelity. Some ownership rows below are inferred from CLAUDE.md historical context, file names, and explicit `agent_loops['<x>'].tools.register(...)` patterns visible in the live (post-reset) `app.py`. Treat as approximately-right starting point for vNext; cross-check against the structural extract at `/media/.../soveryn_PRESERVE_2026-05-23_174236/decompiled/structural/app.recovered.md` when reimplementing.

**Shared by all agents:**
- `persistent_memory_tool.PersistentMemoryTool` (legacy — superseded by `lattice_tool.py`, kept registered until vNext)
- `persistent_memory_tool.SelfReflectionTool` (still used)
- `web_search_tool.WebSearchTool`
- `web_fetch_tool.py` (lightweight stdlib fetch)
- `message_tool.SendMessageTool`
- `lattice_tool` (write/read/connect/recall against Lattice)
- `library_tool` (read-only LAYER_LIBRARY queries)

**Aetheria-only:**
- `task_agent_tool.TaskAgentTool` — delegate to Vett/Scotty
- `continue_task_agent_tool.ContinueTaskAgentTool` — phase-B continuation
- `perception_tool.RequestPerceptionTool` — screen / camera / mic / file
- `pixy_control_tool.PixyControlTool` — camera movement
- `look_tool.LookTool` — move + capture
- `scan_tool.ScanTool` — panorama sweep
- `image_gen_tool` — via ComfyUI :8188
- `email_tool` — Gmail send/receive (absorbed from retired Scout)
- `invoke_council_tool` — reflection_engine councils
- `journal_tool` — append to research journal
- `signal_gateway` — outbound to Jon via Signal (the user-facing channel)
- `dispatch_background_tool` — fire-and-forget agent tasks
- crawl stack: `crawl_tool`, `crawl4ai_tool`, `smart_crawl_tool`, `browser_tool` (5 overlapping tools — vNext should consolidate)

**Scotty-specific:**
- `bash_tool`, `code_test_tool`, `bandit_tool`, `code_graph_tool`, `self_heal_tool`, `write_file_tool`, `verify_file_exists_tool`, `architecture_memory_tool`, `_handoff` (internal)

**V.E.T.T.-specific:**
- Crawl stack + `research_contribution_tool`, `library_ingest_tool`, `document_tool`

**System / not agent-attached:**
- `approval_queue.py` — gates risky tool calls behind Jon's approval
- `message_board_tool` — agent inbox
- `scan_issues_tool` — Ares daemon scan integration
- `thermal_tool` — GPU thermals (Ares uses)
- `claude_bridge_tool` — Claude API bridge (hardcoded model `"claude-sonnet-4-6"`, no fallback — risky)
- `log_reader_tool`, `write_finding_tool`, `downloads_tool` — utilities
- `camera_broker.py` — single point of camera access

---

## 7. Startup order (per `start.sh`)

1. **GPU fan curve** — `gpu_fan_curve.sh` sets per-GPU fan profile
2. **llama-server fleet** — launched in this order:
   - `:8086` embeddings (nomic-embed) — warmed first because everything else needs it
   - `:8084` Qwen3.5-27B + mmproj (Vett/Scotty shared)
   - `:8085` Qwen3.6-35B + mmproj (Aetheria, 90/10 tensor-split)
   - `:8089` gemma-4-E4B (**cognition** — called by `core/cognition.py`, `dream_daemon.py`, `dispatch_background_tool.py`)
   - **Note:** `:8082` (old Qwen3.5-9B Ares LLM) is **NOT** launched by current `start.sh` — `grep '8082' start.sh` returns nothing. The running `:8082` process (PID 3358480, May 14) is a manually-launched long-lived process parented to `systemd --user` but not registered as a systemd unit (`systemctl --user list-units` does not list it). Bucket B drift.
3. **ComfyUI** on `:8188` if image gen enabled (separate conda env)
4. **Parakeet STT** — via systemd `parakeet.service`
5. **Ares daemon** — `python ares_daemon.py` (background)
6. **aetheria_stream.py** (background)
7. **`app.py`** on `:5000` — Flask boots, registers the three `AgentLoop`s, starts heartbeat thread, exposes REST + UI

`SOVERYN_USE_SERVER=1` and `SOVERYN_USE_SERVER_AGENTS=scotty,vett,aetheria` env vars route each agent's inference through `sovereign_llm_client.py` → llama-server. (Pre-cleanup the agents list still mentioned `ares,scout` — drift.)

---

## 8. Bucket A — Active Intended (vNext **keeps and reimplements**)

The canonical set vNext must support on day one. Anything not on this list is either dormant (Bucket B) or retired (Bucket C).

| Component | Why it's here |
|---|---|
| **Aetheria** `AgentLoop` on llama-server `:8085` | Primary human-interface agent |
| **V.E.T.T.** `AgentLoop` on llama-server `:8084` | R&D / research |
| **Scotty** `AgentLoop` on llama-server `:8084` (shared) | Bounded executor under Aetheria's direction |
| **Ares daemon** (`ares_daemon.py`, no LLM) | Background security/perimeter, posts to inboxes |
| **Heartbeat thread** (`AetheriaAutonomy` inside `app.py`) | Aetheria's autonomous research/perception cycle |
| **`aetheria_stream.py`** separate process | Stream/proprioception surface |
| **`agent_message_board.py`** | Inter-agent inbox primitive — Ares uses this to talk to Aetheria |
| **llama-server fleet** (`:8084`, `:8085`, `:8086`, `:8087`, `:8089`) | Inference + embeddings + STT + cognition |
| **Cognition layer** (`core/cognition.py` `AetheriaCognition` thread + Gemma-4 E4B on `:8089`) | Memory-consolidation reasoning, dream daemon target, background dispatch worker |
| **Parakeet STT** (`parakeet.service` on `:8087`) | Voice input |
| **Lattice** (`soveryn_memory/lattice.db` + `core/lattice/*.py`) | The only semantic memory system |
| **`soveryn-dream-aetheria.timer`** (nightly 03:00) | Aetheria memory consolidation — load-bearing |
| **`soveryn_memory/` runtime state** | All DBs, journals, identity_state.json, SOUL.md |
| **Signal channel** (`tools/signal_gateway.py` → `signal-cli`) | Outbound to Jon's phone — replaces retired Telegram |
| **`backup.sh` daily 04:00** (runtime state) | Existing — keep until vNext code-backup daemon ships, then this becomes the runtime-state component |
| **ComfyUI on `:8188`** | Image generation for `tools/image_gen_tool.py` |
| **Expo mobile** (`soveryn_mobile/`, dev server `:8081`) | Mobile UI (separate project; vNext API must remain compatible) |
| **Conda env `soveryn`** (Python 3.11.15) | Primary runtime env |

---

## 9. Bucket B — Observed Dormant / Legacy Still Running

Things actively occupying ports, processes, or systemd timers right now that may not be intentionally part of the active fleet. **Do not kill any of these until vNext is the production runtime** — they may be doing quiet useful work we haven't traced.

| What | Where it lives | Action label | Reason |
|---|---|---|---|
| **Old Ares LLM llama-server** | `:8082`, PID 3358480, Qwen3.5-9B, started May 14 (9 days continuous). **NOT in start.sh, NOT a registered systemd unit** — parented to `systemd --user` cgroup but launched manually (likely nohup/setsid from a terminal at some point). | **investigate before disabling** | Ares was retired as an `AgentLoop` agent, but this server has been up steadily. Could be that `ares_daemon.py` opportunistically calls it for analytical work. Need to grep daemon source + check llama-server access logs for recent requests before killing. If 0 requests in 7 days, safe to disable. CPU-only (`-ngl 0`) so no GPU pressure. |
| **`soveryn-dream-ares.timer`** | systemd, nightly 03:15 | **investigate before disabling** | Runs `dream_daemon.py ares`. Even though the LLM agent is retired, this might still produce useful security-pattern consolidation for the daemon. Inspect `dream_daemon.py`'s ares branch first. |
| **`soveryn-dream-tinker.timer`** | systemd, nightly 03:30 | **disable after vNext** | Tinker was retired earlier (no LLM, no daemon, no callers). Safe to disable once vNext is cut over. Until then, leaving alone is harmless — it just no-ops or logs an error. |
| **`ares-llamaserver.service`** | `/home/jon-deoliveira/soveryn_complete/systemd/ares-llamaserver.service` | **investigate before disabling** | The systemd unit that may be auto-restarting the old `:8082` server. Trace before touching the `:8082` process — kill the unit first if it's the parent. |
| **`aetheria-loop.service`** | `/home/jon-deoliveira/soveryn_complete/aetheria-loop.service` | **investigate before disabling** | Sitting in the repo, not loaded as a system unit (`systemctl cat` returned nothing). May be a draft. If unused, drop. If loaded under a different name, identify. |
| **`backups/` daily snapshots since 2026-05-16** | `soveryn_complete/backups/YYYY-MM-DD/` | **keep** | Active runtime-state backup written by `backup.sh` at 04:00. Lattice/persistent/conversations DBs preserved with 7-day history. Not affected by code-backup daemon; complementary. |
| **`/mnt/acer1`, `/mnt/acer2`** | Mounted but empty dirs | **investigate before disabling** | Empty NFS or USB mount points. Could be configured-but-disconnected NAS. Confirm with `mount` and intent before unmounting. |
| **Multiple `lattice.db.*` backup snapshots** in soveryn_memory/ | Numerous `.bak-*` and dated files | **keep** | Historical recovery surface from prior incidents (governance, confab quarantine, NPM cleanup). Don't sweep. |

---

## 10. Bucket C — Retired But Still Present In Code

Code/config artifacts referencing systems that should not exist in vNext. **vNext starts clean** — don't reintroduce any of these. Each item below is a non-feature.

| Retired system | Code drift in current repo (post-reset state) | Action |
|---|---|---|
| **Scout** | (Pre-reset) Persona block in `config.py:163-230`, AGENT_MAP entries in `templates/desktop_v2.html`, hardcoded `['ares','scotty','vett','scout','aetheria']` lists in `app.py` `/api/message_board` endpoints, `SOVERYN_USE_SERVER_AGENTS=...,scout,...` in `start.sh`, commented agent_loops registration. (Post-reset many references reverted — current `config.py` is Mar 20 vintage and likely has more Scout references than the WIP did.) | **Do not port** to vNext. Single source `ACTIVE_AGENTS = ['aetheria','vett','scotty']` makes Scout impossible to add accidentally. |
| **Vision (separate agent)** | Three `vision_loop = agent_loops.get('vision')` sites in app.py (`:2565`, `:3008`, `:3348`), dead Vision UI panel in `templates/desktop_v2.html:~179-240`, commented agent_loops registration, `vision` in `_agent_thinking` dict, `_AGENT_CTX` references | **Do not port.** Vision is mmproj-native on Aetheria / Vett / Scotty. No vision agent string anywhere in vNext. |
| **Telegram** | `telegram_enabled` flag still gates 13 sites in `heartbeat_integrated.py`, retained as backward-compat alias. `tools/telegram_tool.py` was deleted in pre-reset working tree. | **Do not port.** vNext: `notifications_enabled` only, channel-agnostic (Signal is the only channel). |
| **ChromaDB** | `soveryn_memory/chromadb/`, `soveryn_memory/chromadb.backup-2026-05-04/`, `chroma_db/`, orphan `synapse.db`. `tools/persistent_memory_tool.py` (superseded by `tools/lattice_tool.py`). `core/memory_manager.py` (stubbed no-op since migration). `ingest_document.py` imports nonexistent `memory.client` — broken. `ingest_library.py:160-210` (pre-reset) still wrote to ChromaDB despite header claiming Lattice migration. | **Do not port.** Lattice is the only memory backend. No ChromaDB import in vNext.|
| **Old `memory.py` / `memory_manager.py`** | `core/memory_manager.py` is a stub. `memory.py` (referenced by dead `ingest_document.py`) doesn't export what it claims. | **Do not port.** No memory_manager module in vNext — Lattice graph functions are the API. |
| **Tinker (as LLM agent)** | `soveryn-dream-tinker.timer` (Bucket B). Hardcoded `'tinker'` strings in scattered places (e.g. `core/lattice/graph.py` pre-cleanup `get_agent_activity` default list). | **Do not port.** No "tinker" string anywhere in vNext code paths. |
| **`forge` "agent"** | Pre-reset `core/agent_loop.py:424-448` had a FORCED BANDIT block gated on `self.agent_name == 'forge'` with a hardcoded `C:/Users/jonde/Downloads/...` Windows path. Dead, never matched. | **Do not port.** |
| **Old HTML templates** | `templates/index.html`, `index3-6.html`, `mobile.html`, `mobile6.html`, `mobile_v2.html`, `old.html`, `old_index.py`, `desktop.ini` — were `D` in pre-reset working tree, now restored on disk. | **Do not port.** vNext UI is built fresh against the new REST surface; reference only `desktop_v2.html` and `mobile_v3.html` (and the Expo client) for behavior. |
| **`core/vision_processor.py`** | Pre-reset working tree had this deleted; post-reset it's back on disk. | **Do not port.** Vision is mmproj-native. |
| **`soveryn.py`** (top-level) | Pre-reset deleted; post-reset back. | **Do not port.** No callers; was probably scaffold from before `app.py`. |
| **`claude_bridge_tool.py` hardcoded model** | Module-level `import anthropic` with no guard, hardcoded `"claude-sonnet-4-6"` with no fallback. | **Reimplement only if vNext actually needs Claude bridge** — gate behind env var, lazy-import, configurable model. |
| **Crawl/fetch cluster (5 overlapping tools)** | `crawl_tool`, `crawl4ai_tool`, `smart_crawl_tool`, `browser_tool`, `web_fetch_tool` — two register under `crawl_page` (name collision). | **Reimplement as one tool** with strategy parameter (`mode='basic'|'playwright'|'crawl4ai'|'smart-bfs'`). |
| **`tools/foo.py`** | Empty placeholder file. | **Do not port.** |
| **`aetheria_public` agent / persona** | Pre-reset WIP removed it (per memory). Post-reset Mar 20 `config.py:10, 282` re-introduces the model entry and persona, `sovereign_backend.py:92-94, 799-868` has the separate `_public_inference_lock`, and `app.py:443` prints "Creating agent loop for aetheria_public (GPU 2)" at boot. **The live running `app.py` predates the reset and does NOT serve aetheria_public** — the port `:8089` it talks to is actually the cognition layer. After a restart, the disk-state code would attempt to re-create aetheria_public on `:8089`, *colliding with cognition*. This is the highest-priority Bucket C item to defang before any restart. | **Do not port.** vNext on `:8089` is cognition only. No `aetheria_public` model entry, no persona, no `_public_inference_lock`, no agent registration. |

---

## 11. External integrations

| Integration | Direction | Where |
|---|---|---|
| **Signal** | Outbound (Aetheria → Jon's phone) and inbound replies | `tools/signal_gateway.py` → `signal-cli` |
| **ComfyUI** | Outbound (image gen) | HTTP to `127.0.0.1:8188`, called by `tools/image_gen_tool.py` |
| **Gmail** | Outbound (send) + inbound (poll) | `tools/email_tool.py` via SCOUT_EMAIL / SCOUT_EMAIL_PASSWORD env vars (legacy name) |
| **Web** | Outbound only | `tools/{web_search,web_fetch,crawl,crawl4ai,smart_crawl,browser}_tool.py` |
| **Expo mobile** | Frontend client | `soveryn_mobile/` sibling project, Expo dev server `*:8081`, hits `:5000` REST endpoints |

---

## 12. Filesystem layout

```
/home/jon-deoliveira/
├── soveryn_complete/                # current production (reset-mangled but running)
│   ├── app.py                       # Flask + agent_loops registration + heartbeat thread
│   ├── start.sh / stop.sh / restart.sh
│   ├── sovereign_backend.py         # llama.cpp client (legacy in-process path; mostly bypassed)
│   ├── sovereign_llm_client.py      # llama-server HTTP client (active path)
│   ├── sovereign_embeddings.py      # HTTP shim to embeddings server
│   ├── sovereign_stt.py / sovereign_tts.py
│   ├── heartbeat_integrated.py      # AetheriaAutonomy class (heartbeat thread body)
│   ├── aetheria_stream.py           # separate streaming process
│   ├── ares_daemon.py               # security daemon process
│   ├── agent_message_board.py       # inbox primitive
│   ├── core/
│   │   ├── agent_loop.py            # AgentLoop class (per-agent execution)
│   │   ├── tool_registry.py
│   │   ├── lattice/
│   │   │   ├── graph.py             # Lattice DB layer
│   │   │   ├── retrieval.py
│   │   │   ├── dream.py / collective_dream.py
│   │   │   └── operational.py
│   │   ├── brain_bus.py             # proprioception event bus
│   │   ├── identity_state.py / identity_socket.py / identity_summarizer.py
│   │   ├── memory_router.py / memory_audit.py / memory_candidates.py
│   │   ├── deliberate_share.py      # Signal-routing entry point
│   │   ├── dream_agenda.py / standing_missions.py
│   │   ├── presence_state.py / presence_sentinel.py / salience_monitor.py
│   │   ├── runtime_facts.py / declared_facts.py / signal_memory.py
│   │   ├── security_invariants.py / tool_audit.py / url_safety.py / fix_counter.py
│   │   ├── conversation_store.py / inbox_poller.py
│   │   ├── voice_pipeline.py / reflection_engine.py / self_heal_monitor.py
│   │   └── cognition.py
│   ├── tools/                       # 53 .py files (see §6)
│   ├── templates/
│   │   ├── desktop_v2.html          # active desktop UI
│   │   ├── mobile_v3.html           # active mobile UI (also Expo client)
│   │   └── _archive/                # retired UIs
│   ├── soveryn_memory/              # all runtime state, DBs, journals, archives
│   └── systemd/                     # ares-llamaserver.service (deployed via /etc/systemd)
│
├── soveryn_mobile/                  # Expo React Native app
├── soveryn_vnext/                   # **this dir** — clean rebuild target
│
├── SOVERYN_Models/GGUF/             # legacy local model store
├── /mnt/soveryn_models/GGUF/        # primary model store (mounted)
├── miniconda3/envs/soveryn/         # primary conda env (Python 3.11.15)
├── miniconda3/envs/parakeet/        # STT env
├── miniconda3/envs/comfyui/         # image gen env
├── .soveryn/workspace/              # heartbeat config.json, autonomous_log.jsonl, MEMORY.md
└── ComfyUI/                         # image gen install (also inside soveryn_complete/)
```

`/etc/systemd/system/` holds the three `soveryn-dream-*.service`/`timer` units + `parakeet.service`.

---

## 13. REST surface (UI dependencies — vNext must preserve)

Critical endpoints in current `app.py` that the desktop/mobile UI calls:

- `POST /chat_stream` — main SSE chat (any agent)
- `POST /chat` — non-streaming chat
- `GET  /api/message_board[?agent=X]` — per-agent inbox display
- `POST /api/message_board/clear` — clear inbox
- `GET  /api/persona/<agent>` — fetch persona
- `GET  /api/models` — current MODELS dict
- `GET  /api/research_journal` — Aetheria's journal contents
- `GET  /api/memory/evidence` — memory router audit + staged candidates
- WebSocket: `vision_frame` events — not tied to a Vision agent (retired); still used by Aetheria's `look_tool` / `perception_tool` / `scan_tool` for perception transparency in the UI. vNext should preserve the event channel as a perception side-channel even though no Vision agent receives them.
- `/` — desktop UI
- `/mobile` — mobile UI

---

## 14. vNext design constraints derived from above

- Single source of truth for **active agents** — one `config/runtime.py` constant list; UI, routing, registration, env vars all read from it.
- Single source of truth for **model/server map** — same file; `start.sh` reads from it (no parallel definitions).
- No silent fallbacks. If a model server isn't listening, fail loud at startup with a clear diagnostic.
- No legacy compatibility shims for retired systems. `Scout`, `Vision`, `Telegram`, `ChromaDB`, `Tinker` must not appear as strings, constants, or code paths.
- Embedding access is HTTP-only (`:8086`). No torch dependency for embeddings.
- Lattice is the ONLY semantic memory layer. No second vector store.
- Tool registration is declarative (list per agent), not scattered through `app.py`.
- Code backup daemon is a first-class requirement, not an afterthought.

---

## 15. Migration checklist (derived from buckets A/B/C)

The literal cutover punch list.

**Before vNext goes live:**
- [ ] vNext implements every item in Bucket A (§8)
- [ ] vNext REST surface preserves §13 endpoints (UI compatibility)
- [ ] vNext writes to the same Lattice / persistent / conversations DBs OR migrates with a one-shot script
- [ ] vNext runs side-by-side with current SOVERYN on a different port (e.g., `:5001`) without conflicting on DB writes
- [ ] Each Bucket B "investigate before disabling" item has been investigated and labeled `keep` or `disable`

**At cutover:**
- [ ] Stop old `app.py`, `aetheria_stream.py`, `ares_daemon.py`
- [ ] Start vNext equivalents
- [ ] Verify heartbeat cycle fires, Lattice writes land, chat round-trip works for all three Bucket A agents

**Post-cutover cleanup (Bucket B `disable after vNext`):**
- [ ] `systemctl disable --now soveryn-dream-tinker.timer`
- [ ] Stop old Ares LLM on `:8082` (PID 3358480) if investigation confirmed no callers
- [ ] Stop `aetheria_public` on `:8089` if investigation confirmed no callers
- [ ] Handle `ares-llamaserver.service` and `aetheria-loop.service` per investigation
- [ ] Disable `soveryn-dream-ares.timer` if `dream_daemon.py ares` branch is empty/no-op
- [ ] Move `soveryn_complete/` → `soveryn_legacy_2026-05-23/`, then `mv soveryn_vnext soveryn_complete` (or drop the `_vnext` suffix)

---

*End of Current Truth Spec. Anything not described here is either out of scope for vNext or needs to be added to this doc first.*
