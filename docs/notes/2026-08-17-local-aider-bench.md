# Local Aider bench (2026-08-17)

Local-first coding harness. Aider runs on this machine and talks only to house
routers unless you deliberately point it at a cloud URL.

## Install

```bash
# dedicated venv (already created)
# ~/.venvs/aider  — python from soveryn conda, package aider-chat 0.86.2

# wrapper
# ~/bin/soveryn-aider
```

## Use

```bash
export PATH="$HOME/bin:$PATH"
cd /path/to/project
soveryn-aider                         # model: openai/aetheria @ :8090
soveryn-aider some_file.py

# quadro / other alias
AIDER_BASE=http://127.0.0.1:8091/v1 AIDER_MODEL=openai/vett-scotty soveryn-aider

# or pass through
soveryn-aider --model openai/vett-scotty
```

## Models on disk

**Warm now (typical):** aetheria on `:8090`, vett-scotty / MiniMax on routers.

### Kernel — house build brain (DeepSeek V4 Flash 0731 on NVMe)

House name **Kernel** (in-house pick). Weights / router alias still use Flash tech names.

```
/mnt/soveryn_models/GGUF/DeepSeek-V4-Flash-0731/UD-Q4_K_XL/
  DeepSeek-V4-Flash-0731-UD-Q4_K_XL-00001-of-00005.gguf   # entry shard (~5M meta)
  …-00002 … -00005                                       # weight shards (~145G total)
```

Wired as quadro router preset **`[bench-flash]`**  
(`runtime/router-presets-quadro.ini` → `:8091`).

Aliases: `bench-flash`, `kernel`, `deepseek-flash`, …

```bash
# pick up preset after editing router-presets-quadro.ini
systemctl --user restart soveryn-router-quadro.service

# confirm listed (starts unloaded — loads on first request)
curl -sS http://127.0.0.1:8091/v1/models | python3 -c \
  'import sys,json; print([m["id"] for m in json.load(sys.stdin)["data"]])'

# Command Center (easiest)
#   http://127.0.0.1:5001/  → Kernel card: Talk / Warm / Aider
#   http://127.0.0.1:5001/build  → Kernel chat
# API: GET /api/system/bench_flash  POST …/warm  POST …/chat  (tech path)

# Aider via Kernel (first call can take several minutes to load 145G)
# Loads data/memory/souls/kernel.md via --read automatically
soveryn-aider --kernel
# equivalent:
AIDER_BASE=http://127.0.0.1:8091/v1 AIDER_MODEL=openai/bench-flash soveryn-aider

# raw OpenAI-compat smoke
curl -sS http://127.0.0.1:8091/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"bench-flash","messages":[{"role":"user","content":"pong only"}],"max_tokens":8}'
```

**Note:** 145G will not fit even both Quadros. Default `[bench-flash]` uses `ngl=18` + RAM spill (coexists with embeddings / Messie / voice).

### Speed (measured 2026-08-17)

| Mode | ngl | Decode | Prefill | Requires |
|------|----:|-------:|--------:|----------|
| **Default** `bench-flash` | 18 | ~5.2–6.2 t/s | ~100 t/s | co-tenant OK |
| **Turbo** `bench-flash-turbo` | 24 | ~6.3–7.3 t/s (+15–20%) | ~128 t/s | stop embed + messie + parakeet + f5tts first |
| ngl=28 | — | OOM | — | do not use |

Raw: `/tmp/flash_bench/flash_speed.json`, `flash_speed_turbo_ngl24.json`

Turbo load (optional, temporary):
```bash
systemctl --user stop soveryn-embeddings tgthrmess-messie soveryn-f5tts parakeet
systemctl --user restart soveryn-router-quadro
# then request model bench-flash-turbo
# restore:
systemctl --user start soveryn-embeddings tgthrmess-messie soveryn-f5tts parakeet
```

**Easystore cold copies** (`/mnt/easystore/soveryn_models/GGUF/`): older Flash + GLM-5.2 etc. Safe to leave as backup; interactive path is NVMe.

## Split

| Work | Who |
|------|-----|
| Scaffold, tests, small edits | Local Aider + house model (aetheria) |
| Heavier local build | Local Aider + **Kernel** (`--kernel` / bench-flash) |
| Design, hard debug, product | Grok (this session) |

## Smoke test (passed 2026-08-17)

```bash
soveryn-aider --yes --message '…' hello.py
# Applied edit via openai/aetheria @ 127.0.0.1:8090 — no cloud call
```

Router restart + `bench-flash` listed on `:8091` verified 2026-08-17 after NVMe move.
