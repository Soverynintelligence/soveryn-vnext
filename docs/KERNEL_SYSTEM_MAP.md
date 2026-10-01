# KERNEL SYSTEM MAP — soveryn_vnext

> Kernel's working map of the house. Written 2026-09-13 after a full sweep
> (Eve pic-migration investigation + harness hardening + crash watch).
> Truth for *state* lives in `docs/CURRENT_TRUTH.md`; this file is truth for
> *where things live and how they connect*. Update both when reality changes.

## One-paragraph shape

Flask app (`soveryn.app`, :5001) hosts everything in-process: agent loops
(Aetheria/Kernel/Eve), Messages UI, automations scheduler client, tool
registry. Citizens are AgentLoops built from souls (`data/memory/souls/*.md`,
read fresh per run) + tools via `soveryn/platform/tools/registry.py`
(jsonschema-mediated, audited). Every agent run is recorded as one JSONL line
per run in `data/black_box/<agent>/<session>.jsonl` — a file holds many runs;
each line = `{user_message, actions_and_observations[], final_content}`.
Conversation turns live in `data/memory/conversations_vnext.db`
(`conversations` table: session_id, agent, role, content, timestamp).

## Where things live

| Need | Path |
|---|---|
| App log (stdout/stderr) | `logs/vnext.log` (journal only has systemd start/stop) |
| Per-run agent transcripts | `data/black_box/<agent>/*.jsonl` (one line per run) |
| Turn-level conversation store | `data/memory/conversations_vnext.db` |
| Citizens registry (last_seen, souls, model_server) | `data/citizens.db` |
| Automation catalog | `soveryn/automations/catalog.py` (specs are code) |
| Automation state / inbox / monitor state | `data/automations/` (+ `watches/` for monitor-mode) |
| Souls (agent rules) | `data/memory/souls/<agent>.md` — read fresh each AgentLoop init, no cache |
| Systemd user units | `~/.config/systemd/user/` — tracked copies in `systemd/` |
| Canva exports | `data/media/canva/` · ComfyUI stills `~/ComfyUI/output/eve_*.png` |
| Eve IG photos | `~/Desktop/CWG-Instagram` · profile `data/eve_ig_profile/` |
| Lattice (memory graph) | `data/lattice/` (nodes/edges; conclusions use provenance JSON) |
| Ledger receipts | `soveryn/platform/ledgers` + `ledger_ingest` tool |
| Gate/telemetry evidence | `data/acttruth/`, `data/telemetry/`, per-cwd `.soveryn/evidence/` |

## Agents & brains

- `ACTIVE_AGENTS = (aetheria, kernel, eve)` — enforced by
  `soveryn/agents/registry.py` + `soveryn/config/runtime.py` (RETIRED refuses
  resurrection: vett→eve, scotty→kernel).
- Brains: Aetheria Blackwell `:8090` · Eve Quadros `:8091` (+CX7 proxy) ·
  Kernel GLM EXL3 TP=2 `:8001` (via `kernel`/`soveryn` CLI → Pi 0.74.2).
  `kernel status` is brain truth; `packages/soveryn-cli/` is the harness
  (profiles SSOT `config/soveryn-cli/profiles.json`, park/unpark, gates,
  `doctor --json`).

## Key flows

- **Chat turn**: Messages UI → `routes/chat.py` → AgentLoop (`agents/loop.py`,
  2.4k lines: prelude = soul/pinned/spine/recall) → tool calls via platform
  registry → turn stored in conversations_vnext.db → UI renders.
- **Comfy stills in chat**: not attachments. `app/comfy_chat_urls.py` maps
  turn text → `/aetheria/img/<file>` URLs (needs the exact `eve_NNNNN_.png`
  filename or `#N` ref in text). Frontend stash (`sessionStorage`) +
  `mergeStashedComfy()` re-homes orphans by filename/hash/chronology —
  fixed 2026-09-13 never to dump onto the newest bubble (pic-migration bug).
- **Automations**: `soveryn-automations.service` ticks due crons → POSTs to
  :5001 live-run API → AgentLoop runs → delivery (Signal/Messages). Monitor-
  mode specs hash a watch file; unchanged = no LLM.
- **Heartbeat/dream/cognition/representation**: separate user services driving
  commissions in `data/citizens.db` + lattice writes. Representation daemon
  is DRY RUN (artifacts `data/memory/representation_dryrun.jsonl`).
- **Canva**: OAuth tokens `data/canva/tokens.json` (auto-refresh). Pipeline:
  `generate_image` → `canva_create_design` → `canva_export_design` →
  `compose_post` (Gate-gated for delivery).

## Gotchas learned the hard way

1. `journalctl -u soveryn-vnext` shows almost nothing — app logs to
   `logs/vnext.log`.
2. Ambient env when running CLI from inside a session: `SOVERYN_HARNESS`,
   `SOVERYN_CLI_DIR`, `SOVERYN_PROFILES_PATH` are exported — `env -u` them to
   test the other harness's view.
3. Templates: Flask restart required for `templates/*.html` JS changes.
   Souls: no restart (read per run).
4. `systemctl reset-failed <unit>` needed after removing a crashed unit, else
   it stays in `list-units --all` forever (crash-watch sees ghosts).
5. Generated configs (`config/pi`, `config/soveryn-cli`) must match
   `profiles.json` SSOT — `soveryn doctor` flags drift (exit 1).
6. Monitors can't see what doesn't log: crash-watch timer +
   `soveryn doctor --json` are the deterministic floors; house scan is the
   LLM layer on top.
