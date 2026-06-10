# Path Consolidation — Design

**Status:** locked (Jon, 2026-06-10)
**Author:** Claude (Jon's instruction); reflects state as of this morning
**Goal:** Move all SOVERYN runtime data + config out of the `~/soveryn_complete/` museum tree into a single dedicated data root, so vnext is genuinely self-contained and the museum can be archived without losing anything. Sets up the eventual `~/soveryn_vnext/` → `~/soveryn/` rename.

---

## The asymmetry

vnext code is at `~/soveryn_vnext/`. But every runtime data/config file the vnext code reads is still rooted in `~/soveryn_complete/`:

- `~/soveryn_complete/soveryn_memory/lattice_vnext.db` — Aetheria's memory
- `~/soveryn_complete/soveryn_memory/conversations_vnext.db` — all chat history
- `~/soveryn_complete/soveryn_memory/salience_vnext.db` — Salience Engine buffer
- `~/soveryn_complete/soveryn_memory/souls/` — Aetheria's identity files
- `~/soveryn_complete/soveryn_memory/pinned_memory.md` — pinned context
- `~/soveryn_complete/router-presets.ini` — router child config
- `~/soveryn_complete/templates/` — legacy template fallback dir
- `~/soveryn_complete/.env` — ELEVENLABS_API_KEY and friends
- `~/soveryn_complete/voices-v1.0.bin` — Kokoro voice model (voice migration will use this)
- `~/soveryn_complete/static/voice_aetheria_*.wav` — runtime-generated audio

vnext's `soveryn/config/loader.py` hardcodes paths under `~/soveryn_complete/`. Daemon defaults (`heartbeat/daemon.py`, `dream/daemon.py`, `vett/patrol/daemon.py`, `signal_bridge/daemon.py`) hardcode the same. The museum can't be archived because the system would stop working.

## The thesis

**One data root, env-driven, with sane default.** Pick a target location. Move the files. Update the hardcoded defaults. Make every path computable from `SOVERYN_DATA_ROOT` (or its absence's default). Verify everything still works. Then `~/soveryn_complete/` becomes truly archivable.

---

## Target location

**Default: `~/soveryn_vnext/data/`.**

- Convention: Python projects put data under `data/`. Familiar shape.
- Self-contained: vnext is now genuinely a single tree.
- Rename-safe: when `soveryn_vnext/` becomes `soveryn/` later, the data path becomes `~/soveryn/data/` cleanly.
- Override: `SOVERYN_DATA_ROOT=/some/other/path` lets ops decide otherwise without code changes.

Alternative considered (`~/soveryn_data/` as sibling): rejected. Adds a second top-level dir to remember; tighter coupling between code and data is a feature not a bug for a single-developer system.

Already-in-place precedent: vnext's `data/` directory exists with subdirs `ares/` and `lattice/` (per `.gitignore`). This consolidation extends what's already there.

## What moves

```
~/soveryn_complete/                          ~/soveryn_vnext/data/
├── soveryn_memory/                          ├── memory/
│   ├── lattice_vnext.db          →          │   ├── lattice_vnext.db
│   ├── conversations_vnext.db    →          │   ├── conversations_vnext.db
│   ├── salience_vnext.db         →          │   ├── salience_vnext.db
│   ├── souls/                    →          │   ├── souls/
│   └── pinned_memory.md          →          │   └── pinned_memory.md
├── router-presets.ini            →          ├── router-presets.ini
├── templates/                    →          ├── templates_legacy/
├── voices-v1.0.bin               →          ├── voice/voices-v1.0.bin
├── static/voice_aetheria_*.wav   →          ├── voice/generated/*.wav
└── .env                          →          (left in soveryn_complete; copied for now)
```

The `.env` migration is deferred to a follow-up — it's been used as a shared cross-repo secrets file. Path consolidation copies it forward but doesn't yet decommission the museum copy. ElevenLabs key and friends will be moved cleanly when voice migration lands (see [[2026-06-10-voice-migration-design]]).

## What doesn't move

- `~/soveryn_complete/.beads/` — old project tracking; obsolete with vnext.
- `~/soveryn_complete/__pycache__/`, `.pytest_cache/` — caches.
- `~/soveryn_complete/ComfyUI/` — separate project, lives in its own systemd unit.
- `~/soveryn_complete/chroma_db/`, old archives, backups, etc. — these are museum artifacts.
- `~/soveryn_complete/aetheria_journal*.md`, `*.jsonl` files — historical record. Snapshot and archive separately.

## Code changes

### `soveryn/config/loader.py`

- Add `data_root: Path` field to `EnvConfig`, sourced from `SOVERYN_DATA_ROOT` env var, defaulting to `~/soveryn_vnext/data`.
- Replace all `DEFAULT_*` constants that point into `~/soveryn_complete/` with values computed off `data_root`:

```python
DEFAULT_DATA_ROOT = Path.home() / "soveryn_vnext" / "data"

def _default_lattice_db(root: Path) -> Path:
    return root / "memory" / "lattice_vnext.db"

def _default_conversations_db(root: Path) -> Path:
    return root / "memory" / "conversations_vnext.db"
# ... etc for souls_dir, pinned_memory_path, salience_db, recall_lattice_db
```

- In `load_env_config()`, resolve `data_root` first, then resolve every other path. If a specific path env override is set (e.g., `SOVERYN_LATTICE_DB`), it wins over the derived default.

### Daemon defaults

Files with hardcoded paths under `~/soveryn_complete/`:
- `soveryn/agents/heartbeat/daemon.py`
- `soveryn/agents/dream/daemon.py`
- `soveryn/agents/vett/patrol/daemon.py`
- `soveryn/agents/signal_bridge/daemon.py`

These compute their own `DEFAULT_LATTICE_DB`/`DEFAULT_CONV_DB`/etc as module-level constants. They should switch to reading from `loader.load_env_config()` at module import OR accept the resolved paths from systemd unit `Environment=` directives. Simpler: change the module constants to compute off `Path.home() / "soveryn_vnext" / "data" / "memory" / "..."`, mirroring loader's structure.

### `soveryn/platform/lattice/consolidate.py`

Has `DEFAULT_LEGACY_DB` pointing at `~/soveryn_complete/soveryn_memory/lattice.db` — the *original* prod lattice (not vnext). This file participated in the Phase 2b-ii-b1 migration once. Leave as-is — it's an archival script that ran once and produced the Attic; modifying it would break the historical record. If it ever needs to be re-run, paths can be passed explicitly.

### `soveryn/app/startup.py`

Has `SOVERYN_LEGACY_TEMPLATES_DIR` setdefault pointing at `~/soveryn_complete/templates`. Change default to `~/soveryn_vnext/data/templates_legacy`.

### Systemd unit `Environment=` directives

Once the new defaults land, the systemd units (`~/.config/systemd/user/soveryn-*.service`) can have any explicit `Environment=SOVERYN_*_DB=...` overrides REMOVED — they should rely on the code defaults pointing at the new location. Cleaner.

## Migration procedure

The actual file move needs to happen with services down, otherwise SQLite WAL files will end up at one location and the main DB at another. Concretely:

1. Stop services: `systemctl --user stop soveryn-heartbeat soveryn-dream soveryn-vnext soveryn-vett-patrol soveryn-signal-bridge`
2. Move directories under `~/soveryn_vnext/data/memory/`:
   ```bash
   mkdir -p ~/soveryn_vnext/data/memory
   mv ~/soveryn_complete/soveryn_memory/lattice_vnext.db* ~/soveryn_vnext/data/memory/
   mv ~/soveryn_complete/soveryn_memory/conversations_vnext.db* ~/soveryn_vnext/data/memory/
   mv ~/soveryn_complete/soveryn_memory/salience_vnext.db* ~/soveryn_vnext/data/memory/
   mv ~/soveryn_complete/soveryn_memory/souls ~/soveryn_vnext/data/memory/
   mv ~/soveryn_complete/soveryn_memory/pinned_memory.md ~/soveryn_vnext/data/memory/
   ```
3. Move other artifacts: router preset, templates, voice assets.
4. Deploy the new code (loader.py + daemon defaults updated).
5. Restart services: `systemctl --user start soveryn-vnext` (cascades).
6. Smoke verify: `/v1/models` on router, `/chat` on vnext, heartbeat ticking, conv_store readable, salience accessible.

If something breaks in production state during the move, rollback is `mv` the files back to `~/soveryn_complete/soveryn_memory/` and revert the code. The procedure is reversible because the data is the same, only the location changes.

## What's NOT in v1

- **The actual rename of `~/soveryn_vnext/` → `~/soveryn/`** — that's a separate (later) operation. Path consolidation prepares for it but doesn't execute it.
- **Decommissioning `~/soveryn_complete/`** — also separate. After consolidation, that directory becomes archivable; whether to actually `tar` + `rm -rf` is a follow-up decision.
- **Moving `.env`** — deferred until voice migration spec consolidates the secrets question.
- **Migrating ComfyUI** — separate project, separate scope.

## Re-evaluation triggers

- A service starts pointing at the old location after restart → check systemd `Environment=` overrides; an explicit path override is shadowing the new default.
- SQLite errors on startup ("malformed disk image") → WAL/SHM files weren't moved together with the main DB. Stop everything, move .db + .db-wal + .db-shm as a unit, restart.
- A daemon module silently writes to the old location → grep for any remaining hardcoded `soveryn_complete` strings, must be zero after consolidation.

## See also

- [[project-soveryn-vnext-rebuild]] — the broader migration ledger this closes one item from
- `~/soveryn_vnext/docs/superpowers/specs/2026-06-10-voice-migration-design.md` — sibling spec; voice's generated wav location depends on this consolidation landing first
