# Kernel · OpenCode spike (2026-08-19)

**Intent:** Kernel’s north star is **autonomous** build — OpenCode as the write harness.  
**2026-08-19 update:** coding default briefly moved to **Qwen 3.8** on `:8090` (Flash lagged on multi-file OpenCode + blind search loops).  
**2026-08-20 update:** coding default **back to Flash** on `:8091` — real long-repo feel beats Qwen’s benchmark glow. Qwen stays as `soveryn-opencode --qwen` (larger ctx / speed). Flash preset is still **16k ctx** — search discipline required; bumping ctx is a separate VRAM call.

## Pieces
| Piece | Path |
|-------|------|
| OpenCode binary | `~/.opencode/bin/opencode` (also `~/bin/opencode`) |
| House config | `~/soveryn_vnext/config/opencode/opencode.json` |
| Kernel agent prompt | `~/soveryn_vnext/config/opencode/agents/kernel.md` |
| Launcher | `~/bin/soveryn-opencode` → synced from `scripts/soveryn-opencode` |
| Brain (default) | `http://127.0.0.1:8091/v1` · model `bench-flash` |
| Brain (alt) | `http://127.0.0.1:8090/v1` · model `aetheria` · `--qwen` |

## Run
```bash
# Interactive — Flash default
soveryn-opencode ~/soveryn_vnext

# Qwen large-ctx / speed lane
soveryn-opencode --qwen ~/soveryn_vnext

# Headless one-shot (auto-approve non-denied perms)
soveryn-opencode run --auto --dir ~/soveryn_vnext/tmp/kernel-opencode-spike \
  'Create hello_kernel.txt containing: Kernel spike ok'

# Surgical fallback
soveryn-aider --kernel
```

## Fence (v0)
- `edit` / most `bash`: allow (autonomous)
- `sudo`, force-push: ask / deny
- `external_directory`: ask
- Never secrets (prompt + ops discipline)

## Done (same day)
- CC Kernel card: **OpenCode** + Aider fallback; briefing “Kernel build”
- `/build`: Copy OpenCode + Copy Aider; autonomous called out
- Soul + `personas.KERNEL_PERSONA` softened for autonomy
- ActTruth plugin: `config/opencode/plugins/acttruth-kernel.js` → `scripts/acttruth_record_tool.py`  
  (dogfood: `opencode:write` on kernel ledger)

## Later
- Tighter workspace allowlist for house repos only
- Optional: CC deep-link that launches OpenCode (not just copy)
