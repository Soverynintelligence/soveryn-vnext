# Runtime Config — Tracked Source of Truth

This directory holds runtime configuration files that the SOVERYN systemd units read at startup. **These files are the canonical, version-controlled source.** Edit them here.

## Files

| Tracked file | Live location read by systemd | Owner unit |
|---|---|---|
| `router-presets.ini` | `~/soveryn_complete/router-presets.ini` | `soveryn-router.service` |

## Why this exists

Until 2026-06-11, the router preset lived only at `~/soveryn_complete/router-presets.ini` — outside any repo. The file had been silently edited multiple times during model swaps and rebalancing, and on 2026-06-01 a critical performance flag (`swa-full = true` for Aetheria) was dropped during a wholesale section rewrite. The loss caused intermittent 5-8 second cold-turn latency spikes for a week before being diagnosed on 2026-06-11. See `[[project-soveryn-swa-full-aetheria-2026-06-11]]` for the forensic timeline.

Tracking the file here gives us:

- **`git diff` visibility** on every change — no more silent flag drops
- **Reviewable commits** with the reasoning attached
- **Reverts** for any change that regresses behavior

## Editing workflow

When you need to change router preset behavior:

1. **Edit the tracked file:**
   ```bash
   $EDITOR ~/soveryn_vnext/docs/runtime-config/router-presets.ini
   ```

2. **Sync to the live location** (the systemd unit still reads from the museum path):
   ```bash
   cp ~/soveryn_vnext/docs/runtime-config/router-presets.ini ~/soveryn_complete/router-presets.ini
   ```

3. **Restart the router** to pick up the new preset:
   ```bash
   systemctl --user restart soveryn-router.service
   ```

4. **Verify the change took effect:**
   ```bash
   ps -o pid,cmd -C llama-server | grep aetheria   # check the actual flags
   journalctl --user -u soveryn-router.service --since "2 min ago" --no-pager | tail -20
   ```

5. **Commit the tracked change** with a message that explains the WHY (not just the WHAT):
   ```bash
   cd ~/soveryn_vnext
   git add docs/runtime-config/router-presets.ini
   git commit -m "config(router): <what changed> — <why>"
   ```

## Decommissioning the museum path (future)

This two-location split (tracked + live-in-museum) is transitional. When the `~/soveryn_complete/` decommission lands, the cleanup is:

1. Update `~/.config/systemd/user/soveryn-router.service` `ExecStart` to point at `~/soveryn_vnext/docs/runtime-config/router-presets.ini`
2. Update the `--models-preset` argument to match
3. `systemctl --user daemon-reload && systemctl --user restart soveryn-router.service`
4. Remove the live museum copy after verifying the router reads cleanly from the new path

Until that lands, the manual `cp` sync step is the seam.

## Other untracked runtime config worth bringing under control eventually

These are flagged for the same treatment when there's a quiet moment:

- `~/.config/systemd/user/soveryn-*.service` (unit files)
- `~/soveryn_complete/.env` (secrets — but they belong in a private repo or vault, not this directory)
- Anything else discovered during config audits

## See also

- `[[project-soveryn-swa-full-aetheria-2026-06-11]]` — the diagnosis that forced this question
- `[[project-soveryn-path-consolidation-shipped]]` — broader effort to pull SOVERYN runtime config out of the `soveryn_complete` museum
