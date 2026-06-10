# Path Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the path consolidation locked in `docs/superpowers/specs/2026-06-10-path-consolidation-design.md`. Move all SOVERYN runtime data + config out of `~/soveryn_complete/` into `~/soveryn_vnext/data/` (env-overridable via `SOVERYN_DATA_ROOT`). Update every hardcoded path in the code. Atomic data move during a maintenance window. End state: vnext is self-contained; `~/soveryn_complete/` is archivable.

**Architecture:** Code-first, then atomic data move. Tasks 1-5 are code-only — services keep running on cached imports with old paths until restart. Task 6 is the maintenance window: stop services, move data, start services, verify. Task 7 is the live verification + grep proof that no `soveryn_complete` strings remain in production code paths.

**Tech Stack:** Python 3.10+, stdlib `pathlib`, existing `EnvConfig` dataclass, systemd user services, sqlite3 (data files include `.db`, `.db-wal`, `.db-shm` triplets that must move together).

---

## File Structure

**Modified files:**
- `soveryn/config/loader.py` — add `data_root: Path` to `EnvConfig`; compute all `DEFAULT_*` path constants off it; keep per-path env overrides taking precedence
- `soveryn/agents/heartbeat/daemon.py` — `DEFAULT_LATTICE_DB` / `DEFAULT_CONV_DB` / `DEFAULT_SALIENCE_DB` recomputed off the new data root
- `soveryn/agents/dream/daemon.py` — same shape
- `soveryn/agents/vett/patrol/daemon.py` — same shape
- `soveryn/agents/signal_bridge/daemon.py` — same shape
- `soveryn/app/startup.py` — `SOVERYN_LEGACY_TEMPLATES_DIR` default → `~/soveryn_vnext/data/templates_legacy`
- `tests/test_launcher.py` — `_env()` helper updated with `data_root` field default
- Possibly `tests/test_continuity_startup_wiring.py` — same field addition if it constructs `EnvConfig` directly

**Created files (runtime, by Task 5 setup script):**
- `~/soveryn_vnext/data/memory/`
- `~/soveryn_vnext/data/voice/generated/`
- `~/soveryn_vnext/data/templates_legacy/`
- `.gitkeep` files where appropriate

**Created files (in-repo):**
- `scripts/path_migration.sh` — the maintenance-window data-move script (Task 6)
- `docs/PATH_CONSOLIDATION_RUNBOOK.md` — verification checklist + rollback procedure

**Not touched:**
- `soveryn/platform/lattice/consolidate.py` — archival script for the once-and-done 2026-06-01 prod→vnext lattice consolidation. Per spec: leave as-is. Modifying it would alter the historical record. If it ever needs to re-run, paths can be passed explicitly.

---

## Task 1: EnvConfig gains data_root field

**Files:**
- Modify: `soveryn/config/loader.py`
- Modify: `tests/test_launcher.py` (test fixture helper)
- Possibly modify: `tests/test_continuity_startup_wiring.py` if it constructs EnvConfig directly

- [ ] **Step 1: Read `soveryn/config/loader.py` end-to-end** to see the exact dataclass shape, parser helpers, and field ordering. Verify what fields exist today before changing them.

- [ ] **Step 2: Write the test for the new field default**

```python
# tests/test_loader_data_root.py (NEW)
from pathlib import Path
from soveryn.config.loader import load_env_config, DEFAULT_DATA_ROOT


def test_default_data_root_is_under_soveryn_vnext():
    cfg = load_env_config({})
    assert cfg.data_root == Path.home() / "soveryn_vnext" / "data"
    assert cfg.data_root == DEFAULT_DATA_ROOT


def test_data_root_env_override():
    cfg = load_env_config({"SOVERYN_DATA_ROOT": "/tmp/custom-data"})
    assert cfg.data_root == Path("/tmp/custom-data")


def test_data_root_empty_env_falls_back_to_default():
    cfg = load_env_config({"SOVERYN_DATA_ROOT": ""})
    assert cfg.data_root == DEFAULT_DATA_ROOT
```

- [ ] **Step 3: Verify the test fails** — `pytest tests/test_loader_data_root.py -v` reports ImportError or AttributeError on `DEFAULT_DATA_ROOT`.

- [ ] **Step 4: Add `DEFAULT_DATA_ROOT` constant + `data_root` field**

In `soveryn/config/loader.py`, after the existing `DEFAULT_*` constants near line 30:

```python
DEFAULT_DATA_ROOT = Path.home() / "soveryn_vnext" / "data"
```

Add to `EnvConfig` dataclass (after `recall_lattice_db`, before `salience_db` if present):

```python
data_root: Path
```

In `load_env_config()`:

```python
data_root=_parse_path(
    "SOVERYN_DATA_ROOT", env.get("SOVERYN_DATA_ROOT"),
    default=DEFAULT_DATA_ROOT),
```

(Place this resolution FIRST in the kwargs to `EnvConfig(...)` so subsequent path defaults can derive from it in Task 2.)

- [ ] **Step 5: Update the test fixture helper**

In `tests/test_launcher.py`, find the `_env()` helper (it constructs `EnvConfig` directly with kwargs). Add `data_root=tmp_path / "data"` (or whatever `tmp_path` fixture the helper uses; if it's static `data_root=Path("/tmp/test-data")` is fine — the launcher tests don't actually exercise the path).

- [ ] **Step 6: Run the launcher tests + the new test**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/pytest tests/test_loader_data_root.py tests/test_launcher.py -q
```

All pass.

- [ ] **Step 7: Run global pytest, expect zero regressions**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/pytest tests/ -q
```

Report before/after global count. If test_continuity_startup_wiring.py constructs EnvConfig and the new required field broke it, add the field there too with a sensible default.

- [ ] **Step 8: Commit**

```bash
git add soveryn/config/loader.py tests/test_loader_data_root.py tests/test_launcher.py
git commit -m "feat(loader): EnvConfig.data_root + SOVERYN_DATA_ROOT env override

First step of path consolidation. Spec:
docs/superpowers/specs/2026-06-10-path-consolidation-design.md."
```

Use `-c user.email=jdeoliveira@soverynintelligence.com`.

---

## Task 2: Loader DEFAULT_* constants refactored off data_root

**Files:**
- Modify: `soveryn/config/loader.py`
- Modify or extend: `tests/test_loader_data_root.py`

Replace the hardcoded `~/soveryn_complete/soveryn_memory/...` paths in loader constants. Each `DEFAULT_*` becomes a function of `data_root` so a `SOVERYN_DATA_ROOT` override cascades correctly into every derived path.

- [ ] **Step 1: Write tests covering the cascade**

```python
# Append to tests/test_loader_data_root.py
def test_lattice_db_default_derives_from_data_root():
    cfg = load_env_config({})
    assert cfg.lattice_db == cfg.data_root / "memory" / "lattice_vnext.db"


def test_conversations_db_default_derives_from_data_root():
    cfg = load_env_config({})
    assert cfg.conversations_db == cfg.data_root / "memory" / "conversations_vnext.db"


def test_souls_dir_default_derives_from_data_root():
    cfg = load_env_config({})
    assert cfg.souls_dir == cfg.data_root / "memory" / "souls"


def test_pinned_memory_default_derives_from_data_root():
    cfg = load_env_config({})
    assert cfg.pinned_memory_path == cfg.data_root / "memory" / "pinned_memory.md"


def test_recall_lattice_db_default_derives_from_data_root():
    cfg = load_env_config({})
    assert cfg.recall_lattice_db == cfg.data_root / "memory" / "lattice_vnext.db"


def test_salience_db_default_derives_from_data_root():
    cfg = load_env_config({})
    assert cfg.salience_db == cfg.data_root / "memory" / "salience_vnext.db"


def test_data_root_override_cascades_to_all_paths():
    cfg = load_env_config({"SOVERYN_DATA_ROOT": "/tmp/different"})
    assert cfg.lattice_db == Path("/tmp/different/memory/lattice_vnext.db")
    assert cfg.conversations_db == Path("/tmp/different/memory/conversations_vnext.db")
    assert cfg.souls_dir == Path("/tmp/different/memory/souls")
    assert cfg.pinned_memory_path == Path("/tmp/different/memory/pinned_memory.md")
    assert cfg.salience_db == Path("/tmp/different/memory/salience_vnext.db")


def test_per_path_env_override_wins_over_data_root_cascade():
    """If SOVERYN_LATTICE_DB is set explicitly, it overrides the data_root cascade."""
    cfg = load_env_config({
        "SOVERYN_DATA_ROOT": "/tmp/data",
        "SOVERYN_LATTICE_DB": "/explicit/path/lattice.db",
    })
    assert cfg.lattice_db == Path("/explicit/path/lattice.db")
    assert cfg.conversations_db == Path("/tmp/data/memory/conversations_vnext.db")  # cascade still applies
```

- [ ] **Step 2: Refactor loader.py**

Replace top-level constants:

```python
# Before (hardcoded museum paths)
DEFAULT_LATTICE_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice_vnext.db")
DEFAULT_CONVERSATIONS_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/conversations_vnext.db")
# ... etc

# After (functions of data_root)
def _memory_dir(root: Path) -> Path:
    return root / "memory"

def _default_lattice_db(root: Path) -> Path:
    return _memory_dir(root) / "lattice_vnext.db"

def _default_conversations_db(root: Path) -> Path:
    return _memory_dir(root) / "conversations_vnext.db"

def _default_souls_dir(root: Path) -> Path:
    return _memory_dir(root) / "souls"

def _default_pinned_memory_path(root: Path) -> Path:
    return _memory_dir(root) / "pinned_memory.md"

def _default_recall_lattice_db(root: Path) -> Path:
    return _memory_dir(root) / "lattice_vnext.db"  # same file as lattice_db (consolidated 2026-06-01)

def _default_salience_db(root: Path) -> Path:
    return _memory_dir(root) / "salience_vnext.db"
```

Update `load_env_config()` to resolve `data_root` FIRST, then use it as the default for each derived path:

```python
def load_env_config(env: dict[str, str] | None = None) -> EnvConfig:
    env = env if env is not None else dict(os.environ)
    data_root = _parse_path("SOVERYN_DATA_ROOT", env.get("SOVERYN_DATA_ROOT"),
                            default=DEFAULT_DATA_ROOT)
    return EnvConfig(
        app_port=...,
        model_root=...,
        health_timeout_seconds=...,
        data_root=data_root,
        lattice_db=_parse_path("SOVERYN_LATTICE_DB", env.get("SOVERYN_LATTICE_DB"),
                               default=_default_lattice_db(data_root)),
        conversations_db=_parse_path("SOVERYN_CONVERSATIONS_DB", env.get("SOVERYN_CONVERSATIONS_DB"),
                                     default=_default_conversations_db(data_root)),
        souls_dir=_parse_path("SOVERYN_SOULS_DIR", env.get("SOVERYN_SOULS_DIR"),
                              default=_default_souls_dir(data_root)),
        pinned_memory_path=_parse_path("SOVERYN_PINNED_MEMORY_PATH", env.get("SOVERYN_PINNED_MEMORY_PATH"),
                                       default=_default_pinned_memory_path(data_root)),
        recall_lattice_db=_parse_path("SOVERYN_RECALL_LATTICE_DB", env.get("SOVERYN_RECALL_LATTICE_DB"),
                                      default=_default_recall_lattice_db(data_root)),
        salience_db=_parse_path("SOVERYN_SALIENCE_DB", env.get("SOVERYN_SALIENCE_DB"),
                                default=_default_salience_db(data_root)),
        # ... cross_surface_* fields unchanged
    )
```

- [ ] **Step 3: Tests pass**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/pytest tests/test_loader_data_root.py tests/test_launcher.py -q
```

- [ ] **Step 4: Run global pytest** — zero regressions. If anything else in the codebase was importing the old `DEFAULT_LATTICE_DB` etc. names as module-level constants directly, fix those importers to use functions or `load_env_config()`.

```bash
grep -rn "from soveryn.config.loader import DEFAULT_" /home/jon-deoliveira/soveryn_vnext/soveryn/ tests/ 2>&1 | grep -v __pycache__
```

If any matches found, update those importers.

- [ ] **Step 5: Commit**

```bash
git add soveryn/config/loader.py tests/test_loader_data_root.py
git commit -m "feat(loader): default paths derive from data_root with cascade

All DEFAULT_* path constants in loader.py now compute off data_root.
Per-path env overrides still take precedence over the cascade."
```

---

## Task 3: Daemon module constants updated

**Files:**
- Modify: `soveryn/agents/heartbeat/daemon.py`
- Modify: `soveryn/agents/dream/daemon.py`
- Modify: `soveryn/agents/vett/patrol/daemon.py`
- Modify: `soveryn/agents/signal_bridge/daemon.py`

Each daemon has hardcoded module-level path constants pointing at `~/soveryn_complete/soveryn_memory/`. Replace with the same pattern as loader.py (derive from a module-level data root constant).

- [ ] **Step 1: Grep to confirm the exact set of constants to update**

```bash
grep -nE "Path\(.*soveryn_complete" /home/jon-deoliveira/soveryn_vnext/soveryn/agents/heartbeat/daemon.py /home/jon-deoliveira/soveryn_vnext/soveryn/agents/dream/daemon.py /home/jon-deoliveira/soveryn_vnext/soveryn/agents/vett/patrol/daemon.py /home/jon-deoliveira/soveryn_vnext/soveryn/agents/signal_bridge/daemon.py
```

Expected hits: `DEFAULT_LATTICE_DB`, `DEFAULT_CONV_DB`, `DEFAULT_SALIENCE_DB` per file (some have only a subset).

- [ ] **Step 2: Write tests for the new constants** (one test file shared)

```python
# tests/test_daemon_defaults.py (NEW)
from pathlib import Path


def test_heartbeat_daemon_defaults_under_data_root():
    from soveryn.agents.heartbeat import daemon
    assert daemon.DEFAULT_LATTICE_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
    assert daemon.DEFAULT_CONV_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "conversations_vnext.db"
    assert daemon.DEFAULT_SALIENCE_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "salience_vnext.db"


def test_dream_daemon_defaults_under_data_root():
    from soveryn.agents.dream import daemon
    assert daemon.DEFAULT_LATTICE_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
    assert daemon.DEFAULT_CONV_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "conversations_vnext.db"


def test_vett_patrol_daemon_defaults_under_data_root():
    from soveryn.agents.vett.patrol import daemon
    assert daemon.DEFAULT_LATTICE_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
    assert daemon.DEFAULT_CONV_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "conversations_vnext.db"


def test_signal_bridge_daemon_defaults_under_data_root():
    from soveryn.agents.signal_bridge import daemon
    assert daemon.DEFAULT_LATTICE_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"


def test_no_soveryn_complete_in_daemon_defaults():
    """Defense in depth: no daemon module default should mention soveryn_complete."""
    from soveryn.agents.heartbeat import daemon as hb
    from soveryn.agents.dream import daemon as dr
    from soveryn.agents.vett.patrol import daemon as vp
    from soveryn.agents.signal_bridge import daemon as sb
    for mod in (hb, dr, vp, sb):
        for name in dir(mod):
            if name.startswith("DEFAULT_") and name.endswith(("_DB", "_DIR")):
                value = getattr(mod, name)
                assert "soveryn_complete" not in str(value), f"{mod.__name__}.{name} still points at museum: {value}"
```

- [ ] **Step 3: Tests fail** (constants still point at soveryn_complete).

- [ ] **Step 4: Update each daemon's module constants**

In each daemon file, replace the hardcoded path with one derived from `Path.home() / "soveryn_vnext" / "data" / "memory" / ...`. Keep the constant name (other code may import it).

```python
# Before
DEFAULT_LATTICE_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice_vnext.db")

# After
DEFAULT_LATTICE_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
```

Same shape for DEFAULT_CONV_DB and DEFAULT_SALIENCE_DB in each file that has them.

- [ ] **Step 5: Tests pass + global pytest stays green**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/pytest tests/test_daemon_defaults.py -q
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add soveryn/agents/heartbeat/daemon.py soveryn/agents/dream/daemon.py soveryn/agents/vett/patrol/daemon.py soveryn/agents/signal_bridge/daemon.py tests/test_daemon_defaults.py
git commit -m "feat(daemons): module defaults compute off ~/soveryn_vnext/data/"
```

---

## Task 4: Startup legacy-templates path

**Files:**
- Modify: `soveryn/app/startup.py`

The Flask app `SOVERYN_LEGACY_TEMPLATES_DIR` config setdefault points at `~/soveryn_complete/templates`. Change to `~/soveryn_vnext/data/templates_legacy`.

- [ ] **Step 1: Find the exact line**

```bash
grep -n "SOVERYN_LEGACY_TEMPLATES_DIR\|soveryn_complete/templates" /home/jon-deoliveira/soveryn_vnext/soveryn/app/startup.py /home/jon-deoliveira/soveryn_vnext/soveryn/app/routes/ui_compat.py
```

- [ ] **Step 2: Add a test for the new default**

```python
# tests/test_startup_templates_path.py (NEW)
from pathlib import Path
from flask import Flask
from soveryn.app.startup import create_app


def test_legacy_templates_dir_default_under_data_root(tmp_path, monkeypatch):
    # Provide a tmp data_root so create_app doesn't try to read real prod files
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    # Stand up minimal env (other env vars get defaults)
    app = create_app()
    legacy = app.config["SOVERYN_LEGACY_TEMPLATES_DIR"]
    # Should be the new data-root-derived path (NOT under soveryn_complete)
    assert "soveryn_complete" not in str(legacy)
    assert "templates_legacy" in str(legacy)
```

(If the existing `test_continuity_startup_wiring.py` already exercises `create_app(env=...)`, reuse its setup pattern.)

- [ ] **Step 3: Update startup.py**

```python
# Before
app.config.setdefault(
    "SOVERYN_LEGACY_TEMPLATES_DIR",
    "/home/jon-deoliveira/soveryn_complete/templates",
)

# After
app.config.setdefault(
    "SOVERYN_LEGACY_TEMPLATES_DIR",
    str(Path.home() / "soveryn_vnext" / "data" / "templates_legacy"),
)
```

Make sure `Path` is imported at the top of startup.py (it likely already is).

- [ ] **Step 4: Tests pass + global pytest stays green**

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/startup.py tests/test_startup_templates_path.py
git commit -m "feat(startup): legacy templates default under ~/soveryn_vnext/data/"
```

---

## Task 5: Create data directory structure (setup script)

**Files:**
- Create: `scripts/setup_data_root.sh`

A small idempotent script that creates the directory structure under `~/soveryn_vnext/data/`. Run once before the migration. Safe to run repeatedly.

- [ ] **Step 1: Write the script**

```bash
#!/bin/bash
# Idempotent setup of the SOVERYN data root.
# Creates the directory structure that path-consolidated code expects.

set -eu

DATA_ROOT="${SOVERYN_DATA_ROOT:-$HOME/soveryn_vnext/data}"

echo "Setting up SOVERYN data root at: $DATA_ROOT"

mkdir -p "$DATA_ROOT/memory"
mkdir -p "$DATA_ROOT/memory/souls"
mkdir -p "$DATA_ROOT/voice/generated"
mkdir -p "$DATA_ROOT/templates_legacy"

# Gitkeep so empty dirs survive any git operations
for d in memory voice/generated templates_legacy; do
  touch "$DATA_ROOT/$d/.gitkeep"
done

echo "Directory structure ready:"
find "$DATA_ROOT" -maxdepth 3 -type d | sort
```

- [ ] **Step 2: Make executable + dry-run**

```bash
chmod +x /home/jon-deoliveira/soveryn_vnext/scripts/setup_data_root.sh
bash /home/jon-deoliveira/soveryn_vnext/scripts/setup_data_root.sh
ls -la ~/soveryn_vnext/data/
```

Confirm the structure is right and `find` shows `memory/`, `memory/souls/`, `voice/`, `voice/generated/`, `templates_legacy/`.

- [ ] **Step 3: Commit**

```bash
git add scripts/setup_data_root.sh
git commit -m "infra(data): setup script for SOVERYN data root structure"
```

---

## Task 6: Migration runbook (the maintenance window)

**Files:**
- Create: `scripts/path_migration.sh`
- Create: `docs/PATH_CONSOLIDATION_RUNBOOK.md`

THIS IS THE ATOMIC OPERATION. Services down, data moved, services up, verify. Jon-run; not subagent-dispatchable.

- [ ] **Step 1: Write the migration script**

```bash
#!/bin/bash
# scripts/path_migration.sh
# Atomic path consolidation: stop services, move data, restart services.
# Run during maintenance window. Reversible (data is moved, not transformed).

set -eu

OLD_MEMORY="$HOME/soveryn_complete/soveryn_memory"
NEW_MEMORY="$HOME/soveryn_vnext/data/memory"
OLD_TEMPLATES="$HOME/soveryn_complete/templates"
NEW_TEMPLATES="$HOME/soveryn_vnext/data/templates_legacy"
OLD_ROUTER_PRESET="$HOME/soveryn_complete/router-presets.ini"
NEW_ROUTER_PRESET="$HOME/soveryn_vnext/data/router-presets.ini"

echo "=== Path consolidation maintenance window ==="
echo "OLD: $OLD_MEMORY  →  NEW: $NEW_MEMORY"
echo

# Step 1: Confirm new structure exists
if [ ! -d "$NEW_MEMORY" ]; then
    echo "ERROR: $NEW_MEMORY does not exist. Run scripts/setup_data_root.sh first."
    exit 1
fi

# Step 2: Stop services that hold the DBs open
echo "[1/5] Stopping services..."
systemctl --user stop \
    soveryn-heartbeat.service \
    soveryn-dream.service \
    soveryn-signal-bridge.service \
    soveryn-vett-patrol.service \
    soveryn-vnext.service \
    || true  # ok if some are already stopped

sleep 2  # let SQLite WAL flush

# Step 3: Move data files (include WAL + SHM via glob)
echo "[2/5] Moving memory files..."
for prefix in lattice_vnext conversations_vnext salience_vnext; do
    for suffix in "" "-wal" "-shm"; do
        src="$OLD_MEMORY/${prefix}.db${suffix}"
        if [ -e "$src" ]; then
            echo "  mv $src → $NEW_MEMORY/"
            mv "$src" "$NEW_MEMORY/"
        fi
    done
done

# Souls directory
if [ -d "$OLD_MEMORY/souls" ] && [ -z "$(ls -A "$NEW_MEMORY/souls" 2>/dev/null)" ]; then
    echo "  mv $OLD_MEMORY/souls → $NEW_MEMORY/souls"
    rmdir "$NEW_MEMORY/souls" 2>/dev/null || true
    mv "$OLD_MEMORY/souls" "$NEW_MEMORY/"
fi

# Pinned memory
if [ -f "$OLD_MEMORY/pinned_memory.md" ]; then
    echo "  mv $OLD_MEMORY/pinned_memory.md → $NEW_MEMORY/"
    mv "$OLD_MEMORY/pinned_memory.md" "$NEW_MEMORY/"
fi

# Templates
if [ -d "$OLD_TEMPLATES" ] && [ ! -e "$NEW_TEMPLATES/_already_moved" ]; then
    echo "[3/5] Moving legacy templates..."
    cp -r "$OLD_TEMPLATES"/* "$NEW_TEMPLATES/" 2>/dev/null || true
    touch "$NEW_TEMPLATES/_already_moved"
fi

# Router preset
if [ -f "$OLD_ROUTER_PRESET" ] && [ ! -f "$NEW_ROUTER_PRESET" ]; then
    echo "[4/5] Copying router preset (kept in old location until router config updated)..."
    cp "$OLD_ROUTER_PRESET" "$NEW_ROUTER_PRESET"
fi

# Step 4: Restart services
echo "[5/5] Starting services..."
systemctl --user start soveryn-vnext.service
sleep 5  # let vnext warm

systemctl --user start soveryn-heartbeat.service soveryn-dream.service soveryn-signal-bridge.service soveryn-vett-patrol.service
sleep 3

# Step 5: Verify
echo
echo "=== Post-migration verification ==="
for s in soveryn-vnext soveryn-heartbeat soveryn-dream soveryn-signal-bridge soveryn-vett-patrol soveryn-router; do
    state=$(systemctl --user is-active "$s.service" 2>/dev/null)
    printf "  %-30s %s\n" "$s" "$state"
done

echo
echo "Quick probes:"
curl -s --max-time 10 http://127.0.0.1:5001/api/models 2>&1 | head -1 || echo "vnext /api/models failed"
echo
echo "=== Migration done ==="
echo "Verify: sqlite3 $NEW_MEMORY/conversations_vnext.db 'SELECT COUNT(*) FROM conversations;'"
echo "Smoke test: open the UI, chat with Aetheria, confirm conv history visible."
echo "Rollback: see docs/PATH_CONSOLIDATION_RUNBOOK.md"
```

- [ ] **Step 2: Write the runbook doc**

```markdown
# Path Consolidation Runbook

Spec: `docs/superpowers/specs/2026-06-10-path-consolidation-design.md`
Plan: `docs/superpowers/plans/2026-06-10-path-consolidation.md`

## Before the migration

1. Confirm all code commits from Tasks 1-5 have landed
2. Confirm `pytest tests/ -q` is green
3. Run `scripts/setup_data_root.sh` to create the directory structure
4. Snapshot a backup of the old memory directory (optional but recommended):
   ```bash
   tar czf ~/soveryn_complete_memory_backup_$(date +%Y%m%d-%H%M%S).tar.gz -C ~/soveryn_complete soveryn_memory
   ```

## Migration

Run `scripts/path_migration.sh`. Expected duration: ~30 seconds.

## Verification checklist

After the migration script completes:

- [ ] All services show `active` in the post-migration table
- [ ] `curl http://127.0.0.1:5001/api/models` returns 200
- [ ] `sqlite3 ~/soveryn_vnext/data/memory/conversations_vnext.db "SELECT COUNT(*) FROM conversations;"` returns the same row count as before migration
- [ ] Open the UI, send a chat to Aetheria, confirm she responds
- [ ] Open an existing UI session, confirm prior history is visible
- [ ] Signal: send a test message to Aetheria via Signal, confirm she replies
- [ ] Heartbeat: wait for next eligible tick, confirm it ran (check `heartbeat_log` table)
- [ ] Grep proof: `grep -r "soveryn_complete/soveryn_memory" ~/soveryn_vnext/soveryn/ | grep -v __pycache__` returns ONLY non-runtime references (comments, archival scripts) — no production code paths

## Rollback

If anything is broken:

1. Stop services: `systemctl --user stop soveryn-vnext soveryn-heartbeat soveryn-dream soveryn-signal-bridge soveryn-vett-patrol`
2. Move data back:
   ```bash
   for f in lattice_vnext.db lattice_vnext.db-wal lattice_vnext.db-shm \
            conversations_vnext.db conversations_vnext.db-wal conversations_vnext.db-shm \
            salience_vnext.db salience_vnext.db-wal salience_vnext.db-shm \
            pinned_memory.md; do
       [ -e ~/soveryn_vnext/data/memory/$f ] && mv ~/soveryn_vnext/data/memory/$f ~/soveryn_complete/soveryn_memory/
   done
   [ -d ~/soveryn_vnext/data/memory/souls ] && mv ~/soveryn_vnext/data/memory/souls ~/soveryn_complete/soveryn_memory/
   ```
3. Revert the code commits:
   ```bash
   git revert <each commit from Tasks 1-4 in reverse order>
   ```
4. Restart services: `systemctl --user start soveryn-vnext` (cascades)
5. Verify everything is back to old-location-working.

## What's NOT decommissioned by this migration

- `~/soveryn_complete/` still exists (ComfyUI, archival journals, scripts). Leaving in place pending separate decommission decision.
- `~/soveryn_complete/.env` — secrets still live there; consolidated when voice migration spec lands.
- The router preset file at `~/soveryn_complete/router-presets.ini` is COPIED (not moved) to the new location. The router systemd unit still reads the old path. Updating that unit is a follow-up.
```

- [ ] **Step 3: Make migration script executable**

```bash
chmod +x /home/jon-deoliveira/soveryn_vnext/scripts/path_migration.sh
```

- [ ] **Step 4: Commit**

```bash
git add scripts/path_migration.sh docs/PATH_CONSOLIDATION_RUNBOOK.md
git commit -m "infra(data): migration script + runbook for path consolidation"
```

- [ ] **Step 5: HOLD HERE.** Jon executes the actual migration via the runbook. No subagent runs the migration script — services-down is a maintenance-window decision that's Jon's call, not a build task.

---

## Task 7: Live verification + grep proof

**Files:** None — verification only

After Jon has run the migration script and the runbook checklist is clean:

- [ ] **Step 1: Probe each service**

```bash
echo "=== Service state ==="
for s in soveryn-vnext soveryn-router soveryn-heartbeat soveryn-cognition soveryn-dream soveryn-signal-bridge soveryn-ares soveryn-vett-patrol; do
  state=$(systemctl --user is-active "$s.service" 2>/dev/null)
  printf "  %-30s %s\n" "$s" "$state"
done

echo
echo "=== Aetheria end-to-end ==="
curl -s --max-time 30 -X POST http://127.0.0.1:8090/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"aetheria","messages":[{"role":"user","content":"reply with just: ok"}],"max_tokens":10,"stream":false}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('  finish_reason:', d['choices'][0]['finish_reason']); print('  content:', repr(d['choices'][0]['message']['content']))"

echo
echo "=== Data location confirmation ==="
ls -la ~/soveryn_vnext/data/memory/
```

- [ ] **Step 2: Grep proof — no production code references soveryn_complete**

```bash
echo "=== Production code paths still mentioning soveryn_complete ==="
grep -rE "soveryn_complete/(soveryn_memory|router-presets|templates|static)" \
  /home/jon-deoliveira/soveryn_vnext/soveryn/ \
  | grep -v __pycache__ \
  | grep -vE "(^#|\"\"\"|#.*soveryn_complete)" \
  | grep -vE "consolidate\.py|migration\.py" \
  || echo "  (clean — no production code references the old location)"
```

If anything appears that isn't:
- A comment / docstring referencing the historical location
- An archival migration script
- A doc file
- A test fixture

— it's a real issue and needs fixing before Task 7 closes.

- [ ] **Step 3: Save shipped-memory note**

`project_soveryn_path_consolidation_shipped.md` — record: commits, data location, what was moved vs left, the rollback procedure pointer, and the fact that `~/soveryn_complete/` is now archivable.

- [ ] **Step 4: Update memory index**

Add the shipped-memory note to `MEMORY.md`.

---

## Self-Review

**Spec coverage:**
- ✅ `data_root` field + SOVERYN_DATA_ROOT env override — Task 1
- ✅ All loader DEFAULT_* paths derive from data_root — Task 2
- ✅ Per-path env override wins over cascade — Task 2 test
- ✅ Daemon module defaults updated — Task 3
- ✅ Startup legacy templates path — Task 4
- ✅ Atomic data move during maintenance window — Task 6
- ✅ Rollback procedure documented — Task 6
- ✅ Live verification + grep proof — Task 7
- ⏸ `~/soveryn_complete/` decommission — explicitly out-of-scope per spec; separate follow-up
- ⏸ `~/soveryn_vnext/` → `~/soveryn/` rename — explicitly out-of-scope; separate follow-up
- ⏸ `.env` migration — deferred to voice migration spec

**Placeholder scan:**
- "If anything else in the codebase was importing the old DEFAULT_LATTICE_DB" (Task 2 Step 4) — acceptable; the grep step makes this concrete, not vague.
- No "TBD" or "implement later" anywhere. All code blocks contain real content.

**Type consistency:**
- `data_root: Path` field consistent across loader + tests.
- All `DEFAULT_*` constants are Path-typed.
- Daemon module constants follow the same shape.

---

## Execution sequencing

- **Tasks 1-5:** code changes. Each task is independently committable. Subagent-dispatchable.
- **Task 6:** maintenance-window script + runbook commit. The actual `path_migration.sh` execution is JON-RUN, not subagent. Atomic operation must happen during a window Jon chooses.
- **Task 7:** verification. Subagent-dispatchable IF Jon confirms he's run the migration first.

After all 7 tasks: voice migration plan can be written (it depends on this landing).

## See also

- `docs/superpowers/specs/2026-06-10-path-consolidation-design.md` — the spec this plan implements
- `docs/superpowers/specs/2026-06-10-sovereign-voice-design.md` — sibling spec, depends on this landing first
- [[project-soveryn-vnext-rebuild]] — broader migration ledger; this closes one of the remaining items
- [[feedback-agent-damage-is-load-bearing]] — applies: services-down maintenance windows are real, not nominal — Jon's call, not a subagent's
