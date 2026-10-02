# Path Consolidation Runbook

Spec: `docs/superpowers/specs/2026-06-10-path-consolidation-design.md`
Plan: `docs/superpowers/plans/2026-06-10-path-consolidation.md`

This runbook is for Jon to execute when ready. Subagents do NOT run the migration script. The maintenance-window timing is your call.

---

## Before the migration

1. **Confirm code commits have landed.** Each of these should be in `git log`:
   - T1: `feat(loader): EnvConfig.data_root + SOVERYN_DATA_ROOT env override`
   - T2: `feat(loader): default paths derive from data_root with cascade`
   - T3: `feat(daemons): module defaults compute off ~/soveryn_vnext/data/`
   - T4: `feat(startup): legacy templates default under ~/soveryn_vnext/data/`
   - T5: `infra(data): setup script for SOVERYN data root structure`
   - T6: `infra(data): migration script + runbook for path consolidation`

2. **Confirm tests are green:**
   ```bash
   cd ~/soveryn_vnext
   /home/jon-deoliveira/miniconda3/envs/soveryn/bin/pytest tests/ -q
   ```
   Expected: ~1677 passed, zero regressions from baseline.

3. **Run the setup script (idempotent):**
   ```bash
   bash ~/soveryn_vnext/scripts/setup_data_root.sh
   ```

4. **Optional backup snapshot:**
   ```bash
   tar czf ~/soveryn_complete_memory_backup_$(date +%Y%m%d-%H%M%S).tar.gz \
       -C ~/soveryn_complete soveryn_memory
   ```

5. **Confirm router preset path:** the migration script COPIES (not moves) the router preset to the new location. The router systemd unit at `~/.config/systemd/user/soveryn-router.service` still references `~/soveryn_complete/router-presets.ini`. Router updating is a follow-up; for now, both locations have it.

---

## Run the migration

```bash
bash ~/soveryn_vnext/scripts/path_migration.sh
```

Expected duration: ~30-60 seconds. The script:
1. Stops heartbeat, dream, signal-bridge, vett-patrol, vnext (in that order)
2. Moves `lattice_vnext.db`, `conversations_vnext.db`, `salience_vnext.db` (with `-wal` and `-shm` siblings) into `~/soveryn_vnext/data/memory/`
3. Moves `souls/` and `pinned_memory.md` into `~/soveryn_vnext/data/memory/`
4. Copies `templates/` → `~/soveryn_vnext/data/templates_legacy/`
5. Copies `router-presets.ini` → `~/soveryn_vnext/data/router-presets.ini` (router unit still reads old path)
6. Restarts vnext, then downstream daemons
7. Prints post-migration service state + quick probes

---

## Verification checklist

After the script completes:

- [ ] All services show `active` in the post-migration state table
- [ ] `/api/models` probe returned non-empty
- [ ] Conversations row count matches pre-migration count
- [ ] Open the UI at `http://127.0.0.1:5001/`, send Aetheria a chat — she responds
- [ ] Open an existing UI session, prior history is visible
- [ ] Send a test Signal message to Aetheria — she replies
- [ ] Within 30 minutes: heartbeat tick lands in `heartbeat_log` table (eligible row)
- [ ] Grep proof — no production code references `soveryn_complete/soveryn_memory`:
  ```bash
  grep -rE "soveryn_complete/(soveryn_memory|router-presets|templates|static)" \
      ~/soveryn_vnext/soveryn/ | grep -v __pycache__ | grep -vE "consolidate\.py|migration\.py"
  ```
  Expected: empty (clean — no production code references the old location).

---

## Rollback procedure

If anything breaks:

1. **Stop services:**
   ```bash
   systemctl --user stop soveryn-vnext soveryn-heartbeat soveryn-dream \
       soveryn-signal-bridge soveryn-vett-patrol
   ```

2. **Move data back:**
   ```bash
   for f in lattice_vnext.db lattice_vnext.db-wal lattice_vnext.db-shm \
            conversations_vnext.db conversations_vnext.db-wal conversations_vnext.db-shm \
            salience_vnext.db salience_vnext.db-wal salience_vnext.db-shm \
            pinned_memory.md; do
       [ -e ~/soveryn_vnext/data/memory/$f ] && \
           mv ~/soveryn_vnext/data/memory/$f ~/soveryn_complete/soveryn_memory/
   done
   [ -d ~/soveryn_vnext/data/memory/souls ] && \
       mv ~/soveryn_vnext/data/memory/souls ~/soveryn_complete/soveryn_memory/
   ```

3. **Revert the code commits** (in reverse order, so the loader is the last to revert):
   ```bash
   cd ~/soveryn_vnext
   # Revert T4 → T3 → T2 → T1 in that order
   git revert <T4-sha> <T3-sha> <T2-sha> <T1-sha>
   ```

4. **Restart services:**
   ```bash
   systemctl --user start soveryn-vnext  # cascades via systemd Requires/Wants
   ```

5. **Verify** old-location-working with the same checklist above (but expect data at `~/soveryn_complete/soveryn_memory/`).

---

## What's NOT decommissioned by this migration

- `~/soveryn_complete/` directory still exists (ComfyUI, archival journals, scripts). The memory tree under it has been emptied of vnext-runtime files, but other artifacts remain. **Decommissioning the museum directory is a separate decision** — see if anything still needs the journals / static assets / archives before deleting.
- `~/soveryn_complete/.env` — secrets file still lives there. Voice migration spec will consolidate it.
- Router preset at `~/soveryn_complete/router-presets.ini` — COPIED, not moved. Updating `soveryn-router.service` to point at the new location is a follow-up commit (not in this build's scope).
- `~/soveryn_complete/CLAUDE.md` — stale documentation (mentions retired agents). Either delete or update post-decommission.

---

## What happens next

After this migration lands and the verification checklist is clean:
- Path consolidation T7 (live verification + grep proof + shipped-memory note) closes
- Voice migration plan can be written (it depends on this landing first)
- Eventual rename of `~/soveryn_vnext/` → `~/soveryn/` becomes mechanical (one search-replace + symlink)
