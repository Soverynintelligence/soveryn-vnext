# Lab 2026-09-09 — Week 1 SOVERYN coding harness (OpenCode → Flash-Next)

## Endpoints
- Base URL (use this): `http://127.0.0.1:8888/v1`
- Tunnel: `soveryn-spark2-flashnext-8888.service` (user systemd) → spark2 MiaAI vLLM :8888
- Do **not** use `http://10.10.11.2:8888/v1` (broken return path)
- GLM / `:8001` parked — not wired

## Model
- Upstream id: `qwen3.8-flash-next` (Mia NVFP4 / stock; ABLIT=0)
- OpenCode alias: `soveryn/coding` → upstream via `models.coding.id = qwen3.8-flash-next`
- Also listed: `soveryn/qwen3.8-flash-next` (direct id)

## Smoke results (tower localhost)
| Check | Result |
|---|---|
| Tunnel/service | **UP** — user unit active since 2026-09-08 08:22 EDT |
| GET `/v1/models` | **OK** — list includes `qwen3.8-flash-next` only |
| POST chat/completions | **OK** — ~0.31s; content `pong`; `reasoning_tokens: 0` on short prompt |
| Tool calling | **OK** — `finish_reason=tool_calls`; `get_weather` args `{"city":"Boston"}`; ~0.93s |

## Thinking / agents
- Config forces `chat_template_kwargs.enable_thinking: false` on the SOVERYN provider (agents should keep thinking **off** for coding writes).
- Short chat smoke also returned `reasoning_tokens: 0` without that body flag; do not assume default forever — keep the explicit off flag.

## OpenCode files touched
- `/home/jon-deoliveira/soveryn_vnext/config/opencode/opencode.json` — provider `kernel-glm` → `soveryn`; default `soveryn/coding`
- `/home/jon-deoliveira/.config/opencode/opencode.jsonc` — bare `opencode` also gets `soveryn/coding`
- `/home/jon-deoliveira/soveryn_vnext/scripts/soveryn-opencode` — default MODEL `soveryn/coding`
- Backups: `*.bak-20260909-week1-pre`

## Gateway
- **none** — OpenCode openai-compatible provider → `127.0.0.1:8888/v1` directly (no LiteLLM)

## Verify (non-destructive)
```bash
soveryn-opencode models soveryn
# expect: soveryn/coding , soveryn/qwen3.8-flash-next
```

## Overall
**WIRED**
