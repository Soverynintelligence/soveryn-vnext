# Runtime Config — Tracked Source of Truth

This directory holds runtime configuration files that the SOVERYN systemd units read at startup. **These files are the canonical, version-controlled source.** Edit them here.

## Files

| Tracked file | Live location read by systemd | Owner unit |
|---|---|---|
| `router-presets.ini` | `~/soveryn_complete/router-presets.ini` | `soveryn-router.service` |

## Why this exists

Until 2026-06-11, the router preset lived only at `~/soveryn_complete/router-presets.ini` — outside any repo. The file had been silently edited multiple times during model swaps and rebalancing. On the morning of 2026-06-11 a one-day diagnosis arc traced Aetheria's "she's lagging" symptom through three layers before landing on the actual cause:

1. **First hypothesis: SWA workarounds were dropped.** The `swa-full = true` flag had been silently removed during a 2026-06-01 Gemma 4 swap. Restoring it (plus a 90/10 tensor-split workaround on top) brought latency from 14s warm turns down to about 2.5s. Stable enough to look "fixed."

2. **Second hypothesis: llama.cpp engine bug.** Built a parallel HEAD-era binary against CUDA 13.1 in a conda sandbox to test whether upstream SWA fixes obsoleted the workarounds. A lucky short-prompt probe showed a 12x speedup, which framed the upgrade as the cure. Production swap landed. But the speedup did not hold at full prompt scale — same `erased invalidated context checkpoint` warnings, 0% cache hit, same symptom.

3. **Actual cause (vnext, not llama.cpp).** Three parallel investigation agents and an independent Codex audit converged on the same diagnosis: Aetheria's prompt assembly placed *volatile* per-turn blocks (cross-surface continuity brief with `Nm ago` relative-time strings; lattice recall keyed on the current user message) ahead of *stable* blocks (pinned, soul, history) in the folded system prelude. llama.cpp's prefix cache is order-sensitive — any byte that changes near the top of the prompt invalidates everything after it. The continuity brief was changing minute-by-minute purely because `datetime.now()` ticked. Vett/Scotty cached at 99.5% because they had no continuity or recall in the path.

**The real fix is in `soveryn/agents/loop.py`, not in this preset.** Two patches landed:

- **Prelude triage:** moved volatile per-turn context (`continuity_brief`, `recall_context`) out of the folded system prelude and into the trailing user turn. Took warm-turn cached% from 0% to ~87% and wall-time from 14s to 2.5s.
- **SessionContextCache (architectural):** cached continuity and recall as session-scoped views with explicit invalidation keys — continuity keyed on cross-surface activity fingerprint, recall on a 3-turn/30-second reuse window with embedding-drift fallback. Volatile blocks now live back in the stable prelude because they no longer vary turn-to-turn. Took warm-turn cached% to ~99.8%, TTFT to ~500ms.

This preset's `[aetheria]` section is **intentionally minimal** as a result. The previous workaround flags (`swa-full = true`, `device = CUDA0,CUDA2`, `split-mode = layer`, `tensor-split = 90,10`) are genuinely obsolete — they were mitigating cache invalidation that the prelude order itself was causing, downstream of llama.cpp.

Tracking this file gives:

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

## Verifying Aetheria's prompt cache is still healthy

If "she's lagging" symptoms return, this is the probe that bisected the fix on 2026-06-11. Five-turn sync calls; expect <1s wall-time and >99% cached on turns 2+:

```bash
SID=$(curl -s -X POST http://127.0.0.1:5001/sessions \
  -H 'Content-Type: application/json' \
  -d '{"agent":"aetheria","title":"[cache-probe]"}' | jq -r .session_id)

for msg in one two three four five; do
  time curl -s -X POST http://127.0.0.1:5001/chat \
    -H 'Content-Type: application/json' \
    -d "{\"agent\":\"aetheria\",\"session_id\":\"$SID\",\"message\":\"reply: $msg\"}" \
    | jq '{prompt:.usage.prompt_tokens, cached:.usage.prompt_tokens_details.cached_tokens}'
done
```

If `cached` stays at ~1 on turns 2+, something is invalidating the prelude — either (a) a new per-turn variation has been added to prompt assembly in `loop.py`, (b) `SessionContextCache` has been removed or bypassed, or (c) heartbeat/signal-bridge interference is hitting the same slot mid-probe.

Also watch for the SWA warning class:

```bash
journalctl --user -u soveryn-router.service --since "1 hour ago" \
  | grep -E "erased invalidated|sim = 0\."
```

Any hits with `sim = 0.0X` (low similarity) mean per-turn prompt variance is back.

## Decommissioning the museum path (future)

This two-location split (tracked + live-in-museum) is transitional. When the `~/soveryn_complete/` decommission lands, the cleanup is:

1. Update `~/.config/systemd/user/soveryn-router.service` `ExecStart` to point at `~/soveryn_vnext/docs/runtime-config/router-presets.ini` (or the eventual `~/soveryn_vnext/data/router-presets.ini` per path-consolidation runbook)
2. Update the `--models-preset` argument to match
3. `systemctl --user daemon-reload && systemctl --user restart soveryn-router.service`
4. Remove the live museum copy after verifying the router reads cleanly from the new path

Until that lands, the manual `cp` sync step is the seam.

## Other untracked runtime config worth bringing under control eventually

These are flagged for the same treatment when there's a quiet moment:

- `~/.config/systemd/user/soveryn-*.service` (unit files)
- `~/soveryn_complete/.env` (secrets — but they belong in a private repo or vault, not this directory)
- `~/soveryn_vnext/data/router-presets.ini` (path-consolidation future-home; kept in sync manually until decommission)

## See also

- `[[project-soveryn-swa-full-aetheria-2026-06-11]]` — the original misdiagnosis and forensic timeline (kept as the trail of what we tried before finding the real cause)
- `[[project-soveryn-llama-head-binary-2026-06-11]]` — the HEAD binary swap (real ops change, not the silver bullet it was first framed as)
- `[[project-soveryn-aetheria-prompt-cache-fix]]` — the actual root cause + Codex's two-patch fix (prelude triage + SessionContextCache)
- `[[project-soveryn-path-consolidation-shipped]]` — broader effort to pull SOVERYN runtime config out of the `soveryn_complete` museum
