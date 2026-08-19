# Kernel · OpenCode spike (2026-08-19)

**Intent:** Kernel’s north star is **autonomous** build — OpenCode as the write harness on local Flash; Aider stays surgical fallback.

## Pieces
| Piece | Path |
|-------|------|
| OpenCode binary | `~/.opencode/bin/opencode` (also `~/bin/opencode`) |
| House config | `~/soveryn_vnext/config/opencode/opencode.json` |
| Kernel agent prompt | `~/soveryn_vnext/config/opencode/agents/kernel.md` |
| Launcher | `~/bin/soveryn-opencode` |
| Brain | `http://127.0.0.1:8091/v1` · model `bench-flash` |

## Run
```bash
# Interactive (Tab → Kernel agent if needed)
soveryn-opencode ~/soveryn_vnext

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
