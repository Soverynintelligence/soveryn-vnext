# soveryn-console

Jarvis-style HUD for the house. Textual TUI in the `soveryn` env (no new deps).

## Run

```bash
soveryn-console            # TUI
soveryn-console --once     # plain snapshot (CI/cron friendly)
```

Launcher: `~/.local/bin/soveryn-console` → `miniconda3/envs/soveryn/bin/python
packages/soveryn-console/console.py`.

## What it reads

- `~/.soveryn/kernel_brain` — active brain id
- `config/soveryn-cli/profiles.json` — that brain's endpoint
- `nvidia-smi` — live GPU rows
- `systemctl --user` — seat units (soveryn-nvfp4-vllm, vnext, router-quadro, embeddings)
- Probes: :8001 fold, :8090 eve, :8091 quadro, :8096 embeddings, :5001 vnext, :8087 stt, :8088 tts (`/healthz` — F5-TTS has no `/health`). Probe rule: any HTTP response = alive, only connection failure = DOWN.

## Input bar

Type any command and hit enter — runs through `bash -lc` with a 20s cap,
output streams into the LOG panel. Intended for `soveryn …` and `kernel …`
commands; it is a window onto the CLI, not a replacement.

Keys: `q` quit, `r` refresh now. Panels auto-refresh every 5s.
