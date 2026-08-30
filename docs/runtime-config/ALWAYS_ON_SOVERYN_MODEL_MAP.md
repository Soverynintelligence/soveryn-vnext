# Always-On SOVERYN — Model Map

| Field | Value |
|-------|-------|
| **Status** | Target SSOT + live snapshot. **§4 is a dated 2026-08-12 snapshot and is now partly stale — read §0 first.** |
| **Date** | 2026-08-12 · corrections appended 2026-08-20 |

---

## 0. ⚠️ Corrections since 2026-08-12 (verified live 2026-08-20)

Four things moved after this document was written. The 08-12 rows below are left
intact deliberately — this file's own convention is *recorded, not buried* — but
**where they disagree with this section, this section is right.**

| What | Doc says (08-12) | Live 2026-08-20 | Verify with |
|------|------------------|-----------------|-------------|
| **Spark worker model** | `qwen36-35b` | **`lightning-30b`** — Nemotron-3.5-Lightning-30B-A3B-NVFP4 | `curl 10.10.10.2:8001/v1/models` |
| **Aetheria's soul** | Gemma 4 31B Q6 | **Qwen3.8-27B-UD-Q6_K_XL**, ctx 65536 (cutover 08-17, ctx raised 08-19) | `curl 127.0.0.1:8090/v1/models` |
| **Embeddings** | `soveryn-embeddings.service`, Quadro `…990a` :8096 | **`soveryn-embed.service` on the SPARK**, `10.10.10.2:8096` | `embeddings_url()` |
| **Quadro router tenants** | vett-scotty / cognition / reflection | + **Kernel** (`bench-flash`, DeepSeek-V4-Flash) — the house build brain and Eve's brain | `router-presets-quadro.ini` |
| **Kernel (2026-08-30)** | Flash/Qwen on Quadros `:8091` / `:8090` | **GLM-5.3-Flash NVFP4 TP=2**, `http://10.10.10.2:8001`, alias `glm-5.3-flash`, ctx **32768**, RedHat `compressed-tensors` (LibertAI ModelOpt retired — token corruption / tool loops). Lightning parked. Eve + public stay on Quadro Qwen `:8091`. Librarian embed on helper Quadro `:8096`. | `curl 10.10.10.2:8001/v1/models` · `~/.soveryn/kernel_brain` = `glm` |

### The Spark alias is now a switch, not a constant

This is why the `qwen36-35b` rows below rotted. `runtime.py` resolves the Spark
worker brain at import from **`~/.soveryn/vett_brain`** (override:
`$SOVERYN_VETT_BRAIN`), across three profiles:

| Key | Alias | Weights |
|-----|-------|---------|
| `qwen36` | `qwen36-35b` | Qwen3.6-35B-A3B-NVFP4 |
| `qwen38` | `qwen38-27b` | Qwen3.8-27B-NVFP4 |
| `lightning` | `lightning-30b` | Nemotron-3.5-Lightning-30B-A3B-NVFP4 ← **current** |

⚠️ **`resolve_vett_brain()` falls back to `qwen36` if that file is missing or
unreadable.** The file currently reads `lightning` (set 2026-08-17). If it is
ever lost, the config silently claims an alias the Spark is not serving.

⚠️ **The unit is still named `qwen-serve.service` and still describes itself as
the "Qwen" brain. It has not served Qwen since 08-17.** Do not read the unit
name, the unit description, or this document to learn which model is loaded —
**ask the port.** The same class of drift put `qwen36-35b` in Vett's census note
for eight days; that note is now *derived* from the resolver
(`citizens/census.py::_alias_of`) so it cannot lie again.
| **Hardware** | Tower (~144 GiB VRAM, 512 GiB RAM) + DGX Spark (`10.10.10.2`) |
| **Premise** | Local Grok-Bot-class fleet: models stay resident; agents work 24/7; Aetheria never shares her card |
| **Related** | `soveryn/config/runtime.py`, `runtime/router-presets-blackwell.ini`, `runtime/router-presets-quadro.ini`, user systemd units |

---

## 1. Hardware truth (live 2026-08-12)

### Tower GPUs (~147 GiB total VRAM)

| nvidia-smi idx | Name | UUID (pin with this, never index) | VRAM |
|---------------:|------|-----------------------------------|-----:|
| 0 | Quadro RTX 8000 | `GPU-50b41c93-e957-fe4a-eb4d-001d7e7d990a` | 48 GiB |
| 1 | Quadro RTX 8000 | `GPU-305d1801-319e-3330-d75e-0676387a91f2` | 48 GiB |
| 2 | NVIDIA RTX PRO 5000 **Blackwell** | `GPU-946b08b0-e9d3-949b-6eab-b6c5b8a5f5cd` | ~48 GiB |

**Rule:** CX-7 renumbered PCI; **always pin by UUID**. Index 0/1/2 is not stable.

### Interconnect (important)

| Link | Topology (nvidia-smi topo) | Meaning for SOVERYN |
|------|---------------------------|---------------------|
| **GPU0 ↔ GPU1 (Quadros)** | **NV2** (bonded NVLink) | Fast peer link — the two Quadros are a **pair**, not two random PCIe cards |
| **GPU0/1 ↔ GPU2 (Blackwell)** | **NODE** (PCIe within NUMA) | No NVLink to Blackwell — treat as a **separate island** |
| NVLink rate (live) | ~25.8 GB/s per link × 2 on each Quadro | Suitable for **tensor-split / multi-GPU one model** on the Quadro pair only |

```text
  [Quadro 0] ══NVLink══ [Quadro 1]     ← paired (96 GiB effective pool for multi-GPU)
        \                 /
         \    PCIe NODE  /
          \             /
           [Blackwell]               ← alone (Aetheria); never NV-split with Quadros
```

**Implications:**

1. **Always-on helpers** on the Quadro pair can use **single-GPU** slots (embed on one, reflection on the other) *or* one **larger model tensor-split across both Quadros** via NVLink when needed.
2. **Never** tensor-split Aetheria across Blackwell + Quadro (history: PCIe activation exchange → Xid-8 class). Blackwell stays solo; Quadros stay a self-contained pair under `:8091`.
3. Quadro router `CUDA_VISIBLE_DEVICES` correctly lists **both** Quadro UUIDs so llama.cpp can place layers on either/both; Blackwell UUID must **not** appear on that unit.
4. Optional future: one mid-large always-on model (~50–70 GiB weights+KV) **on the NVLinked pair** if Spark is saturated — only if multi-GPU preset is known-good on this stack.

### Host RAM

| | Live snapshot |
|--|---------------|
| Total | ~**503 GiB** (512-class) |
| Use | Prompt-cache host store (`cache-ram`), OS, CPU-only surfaces, queues |

### DGX Spark

| | |
|--|--|
| Host | `10.10.10.2` (CX-7 link) |
| Role | Always-on **worker** brain, shared by every Spark-served agent |
| Stack | vLLM, port **8001** (`qwen-serve.service` — ⚠️ the name is historical). Alias is **resolved at import**, currently **`lightning-30b`**; see §0. |
| ⚠️ Laguna | `laguna-serve` **stopped and disabled** since 2026-08-12 — see §3.4. Weights remain on disk. Anything in this file still saying `laguna` / `:8000` is stale; §3.4 is the record. |

---

## 2. Target architecture (always-on constellation)

Not one model awake for everything — a **small permanent set** of resident models + daemons.

```text
                         ┌─────────────────────────────┐
                         │  vNext :5001 + Bot runtime  │
                         │  (agents, tools, queues)    │
                         └──────────────┬──────────────┘
                ┌───────────────────────┼───────────────────────┐
                ▼                       ▼                       ▼
        ┌───────────────┐       ┌─────────────────────────┐       ┌───────────────┐
        │ BLACKWELL     │       │ QUADRO PAIR (NVLink)    │       │ DGX SPARK     │
        │ :8090 router  │       │ :8091 router            │       │ 10.10.10.2    │
        │ Aetheria ONLY │       │ 96 GiB pool / multi-GPU │       │ :8001 vLLM    │
        └───────────────┘       └─────────────────────────┘       └───────────────┘
                │                       │                       │
                │                       ├─ embed / cognition / reflection
                │                       ├─ optional tensor-split mid model
                │                       └─ never share with Blackwell
                │
        512 GiB RAM ── cache-ram (Aetheria), buffers, CPU dream
```

### Permanent pins (target)

| Lane | Hardware | Always loaded | Consumers |
|------|----------|---------------|-----------|
| **Self** | Blackwell alone (no NVLink to Quadros) | **Aetheria** — Qwen3.8-27B UD-Q6_K_XL, ctx 65k (was Gemma 4 31B Q6 until 08-17, §0) | Chat, heartbeat, Signal, tools |
| **Workers** | Spark | **resolved alias** (`lightning-30b` as of 08-17, §0) — shared by Vett, Scotty, PondWright, Atticus, Seneca | Research, repair, patrol, delegation, products |
| **Librarian** | One Quadro of the NVLink pair (`…990a` today) | **Nemotron-3-Embed-8B** :8096 | Lattice recall / write embeds |
| **Cognition** | Other Quadro and/or NV-split small model | Small Gemma / dream surface | Dream multi-pass, background reason |
| **Reflection** | Quadro pair (single-GPU slot) | Qwen 9B-class | Multi-voice / reflection tools |
| **Optional mid** | **Both Quadros via NVLink** tensor-split | One larger helper if Spark busy | Overflow research / synthesis |
| **Host** | CPU / no GPU | Ares (no LLM) | Sentinel only |

Optional always-on (only if VRAM headroom after pins):

| Lane | Role |
|------|------|
| **Messie** | Small Qwen 9B :5066 messenger-adjacent (if still needed) |
| **Shepherd** | Compliance drafts — only if product is live; else **do not** keep three shepherd presets warm |

---

## 3. Model SSOT table (target = intended product)

### 3.1 Chat agents → inference

| Agent | Logical server (`runtime.py`) | Endpoint | Alias | Hardware | Always-on? |
|-------|------------------------------|----------|-------|----------|------------|
| **Aetheria** | `aetheria_primary` | `http://127.0.0.1:8090` | `aetheria` | Blackwell via router | **YES — never unload** |
| **Vett** | `vett_scotty_shared` | `http://10.10.10.2:8001` | resolved — `lightning-30b` (§0) | Spark vLLM | **YES** |
| **Scotty** | `vett_scotty_shared` | same | resolved — `lightning-30b` (§0) | Spark vLLM | **YES** (shared weights OK) |
| **Kernel** | `kernel_build` | `http://127.0.0.1:8091` | `bench-flash` | Quadros via router | On demand |
| **Eve** | `kernel_build` | `http://127.0.0.1:8091` | `bench-flash` | Quadros via router | On demand |

⚠️ **This table is where INFERENCE happens, not where the PROCESS runs.** The two
were conflated twice in one day (2026-08-13) and it changes decisions:

| Agent | Process runs on | Inference from | HTTP endpoint of its own |
|---|---|---|---|
| Aetheria | tower — heartbeat / dream / cognition / signal-bridge units | Blackwell `:8090` | none |
| **Vett** | **tower** — `soveryn-vett-patrol.service` | Spark `:8001` | **none** — she patrols, she does not listen |
| **Scotty** | **tower**, and **not resident** — invoked on demand, no unit | Spark `:8001` | **none** |
| PondWright | Spark `:8200` | Spark `:8001` | yes |
| Atticus | Spark `:8500` | Spark `:8001` | yes |
| Seneca | Spark `:8400` | Spark `:8001` | yes |

Verified on both machines 2026-08-13: the Spark holds no vett/scotty unit,
process, port or directory. "Vett and Scotty moved to the Spark" refers to their
**model**, which is true and is what `runtime.py` encodes.

### 3.2 Supporting models

| Logical name | Endpoint | Alias | Intended hardware | Always-on? | Notes |
|--------------|----------|-------|-------------------|------------|-------|
| **Embeddings** | `http://127.0.0.1:8096` | (server self-contained) | Quadro `…990a` | **YES** | Nemotron-3-Embed-8B; **not** nomic on :8091 |
| **Cognition / dream brain** | Prefer single SSOT (see §5) | `dream` *or* `cognition` | Quadro **or** CPU | **YES** for dream | Today dual stories — must unify |
| **Reflection** | `http://127.0.0.1:8091` | `reflection` | Quadro router | **Warm on demand or pin if used daily** | Voices / multi-pass tools |
| **ComfyUI** | `:8188` | — | CPU/RAM | Optional | Images; not LLM |
| **Parakeet STT** | `:8087` | — | CPU | **YES** if voice on | |
| **F5-TTS** | (unit) | — | — | Optional | Local voice |

### 3.3 Aetheria slot contract (non-negotiable)

| Knob | Target |
|------|--------|
| Router | `:8090` only; `CUDA_VISIBLE_DEVICES=<Blackwell UUID>` |
| Preset file | **`runtime/router-presets-blackwell.ini` only** |
| Model | `google_gemma-4-31B-it-Q6_K_L.gguf` (+ mmproj) |
| `ctx-size` | 32768 |
| `cache-ram` | **≥ 32768** (host MiB) — never 0 on live path |
| Co-tenants | **None** on Blackwell |
| CUDA | Toolkit/driver that **supports Blackwell (sm_120)**. **Confirmed mechanism 2026-08-12:** `cuobjdump --list-elf libcublas.so.12` (CUDA 12.8) returns **sm_50…sm_90 and no sm_120**; cuBLAS 13.2 has it. Prefill is almost entirely cuBLAS GEMM, so it collapsed **13×**; decode runs ggml's *own* sm_120 kernels and only sagged. **That asymmetry is what disguised it as a prompt-size problem for three days.** |
| Build | llama.cpp built against the **cuda131** toolkit. `~/llama.cpp_head/build` is a **symlink** → `build-cuda131`; the broken tree is kept at `build-cuda128-broken-20260808`. Both routers share that path. |
| ✅ Verify after **every** rebuild | `ldd ~/llama.cpp_head/build/bin/libggml-cuda.so.0 \| grep cublas` **must print `.so.13`**. `LD_LIBRARY_PATH` cannot rescue a wrong build: a binary linked against 12.8 asks for soname `libcublas.so.12`, cuda131 ships only `.so.13`, so the loader falls through to `/usr/local/cuda-12.8`. |
| `swa-full` | **false** (2026-08-12). Measured: +52% prefill, **13.2 GiB VRAM freed**, and checkpoint reuse did **not** break — 6-token warm re-prefill, same as with it on. The 2026-06-11 comment asked for a cold/warm probe before changing it; it has one. |
| KV cache | `q8_0`. f16 tested and reverted: **166.5 vs 169.1 tok/s — no difference.** KV quantization is not a bottleneck here. Don't re-test. |

### 3.4 Spark worker contract

| Knob | Target |
|------|--------|
| Host | `10.10.10.2:8001` (was `:8000`) |
| Alias | **Resolved, not fixed** — `resolve_vett_brain()` → `qwen36` \| `qwen38` \| **`lightning`** (current, 08-17). See §0. Was `laguna` before 08-12. |
| Unit | **`qwen-serve.service`** (systemd **user** unit, `Restart=always`, lingering on, survives reboot). `laguna-serve.service` is **stopped and disabled**. |
| Agents | **Everything on the Spark shares this one model** (decided 2026-08-12): Vett, Scotty, PondWright (`:8200`), Atticus (`:8500`), Seneca (`soveryn-agent`, `:8400`). |
| ⚠️ Stopping this unit | takes **all five** down. `laguna-serve`'s own description said "Vett, Scotty and PondWright" — it was **incomplete**, and trusting it meant Atticus and Seneca stayed pointed at a dead port. **Sweep for `:8001` consumers before stopping, don't read the description.** |
| Per-agent wiring | each app's `config.json` (`laguna_url` + `model`) and `laguna.py`. **`chat_template_kwargs {"enable_thinking": false}` is required in `laguna.py`** — without it Qwen3.6 spends the whole `max_tokens` budget inside `<think>` and the app shows an empty reply or its fallback message. |
| Laguna | `laguna-serve` **stopped and disabled** — it does not return on reboot, deliberately. Weights remain at `~/models/Laguna-S-2.1-NVFP4`. |
| Multi-system messages | `supports_multi_system_messages=False`. Stock Qwen3.6 returns `400 System message must be at the beginning`; `True` was only ever correct for the patched Qwen template the old router child used. |
| Why | Laguna (~85 GiB) and Qwen (~48 GiB) cannot coexist in 121 GiB, and the Spark was needed for the 2026-08-11 honesty bake-off. **Known tradeoff, recorded not buried:** on the self-report harness Qwen3.6-35B false-denies **30/30**, Laguna **18/30**. This is a knowing step onto the worse model for Vett's core failure mode; revisit when the next Qwen lands. |
| Thinking | `enable_thinking: false` unless a controlled A/B says otherwise |
| Revert | Documented in `runtime.py` (local vett-scotty on Quadro) |

---

## 4. Live snapshot vs target (2026-08-12 — **historical; see §0 for corrections**)

### What matches target

| Item | Live |
|------|------|
| Dual routers | `:8090` blackwell + `:8091` quadro — **active** |
| Aetheria pin | Blackwell UUID on `soveryn-router.service` |
| Spark workers | `runtime.py` → `10.10.10.2:8001` / `qwen36-35b` (**changed 2026-08-12**; `laguna-serve` stopped + disabled) |
| Spark app agents | PondWright `:8200`, Atticus `:8500`, Seneca `:8400` — all repointed to `:8001` / `qwen36-35b` 2026-08-12 |
| Ares surface probe | `qwen-spark` → `:8001` (was `laguna-spark` → `:8000`; left as-is it would page forever about a service stopped on purpose). **Correction 08-20:** it does *not* expect `qwen36-35b` — `expect_contains="owned_by"` matches the stable vLLM list shape on purpose, so a brain swap doesn't page. Ares was right; this row was wrong. |
| Embeddings | `soveryn-embeddings.service` on Quadro `…990a` :8096 |
| vNext | `:5001` active |
| Heartbeat / dream / patrol / signal | user units active |
| Aetheria `cache-ram` | 32768 in blackwell preset — **now committed** (`1a83cb8`); it had been working-tree-only, one `git checkout` from silently reverting to 0 |
| Aetheria prefill | **1,592 tok/s** verified 2026-08-12 (was 111) |
| PondWright | repointed to `qwen36-35b`; `laguna.py` now sends `chat_template_kwargs {"enable_thinking": false}` at both payload sites — without it Qwen3.6 spends the whole `max_tokens` budget inside `<think>` and returns **empty content** |

### Drift to fix (always-on hygiene)

| Issue | Live | Target |
|-------|------|--------|
| Cognition URL/alias | Unit on **:8089** alias **`dream`** (CPU-only 26B-A4B); `runtime.py` still says **:8091** `cognition` E4B | **One** brain endpoint + one alias; all dream/cognition/representation clients agree |
| Quadro preset still lists **vett-scotty** 27B | Preset section exists; vNext no longer routes agents there | Remove or mark **RETIRED** so nobody loads 30 GB by accident |
| Quadro **embeddings** nomic section | Still in `router-presets-quadro.ini` | Prefer standalone :8096 only; drop orphan nomic from live max-instances pressure |
| Three **shepherd** presets | In quadro ini | Pin only if Shepherd product is live; else unload |
| `messie` :5066 | Process present | Document as always-on or retire |
| Dangerous preset copies | `runtime/router-presets.ini` / `data/router-presets.ini` with **cache-ram=0** | Never load for production; watermark or delete |
| CUDA story | Unit comments: driver 570 + cuda131 compat | After Blackwell fix: document **working** driver/toolkit pair + tok/s acceptance |

---

## 5. Cognition / dream — unify before calling it “always on”

Today three stories fight:

1. **Dedicated unit** `soveryn-cognition.service` → `:8089` alias `dream`, Gemma 4 26B-A4B Q5, **CPU** (`CUDA_VISIBLE_DEVICES=` empty)  
2. **runtime.py** → port **8091**, alias **`cognition`**, E4B path  
3. **Quadro preset** `[cognition]` E4B on CUDA0 of quadro router  

**Target decision (pick one and lock):**

| Option | Pros | Cons |
|--------|------|------|
| **A. Keep :8089 `dream` CPU** | Does not steal Quadro VRAM; matches dream client `model=dream` | Slow; dual with router cognition |
| **B. Pin small Gemma on Quadro as `dream`** | Faster dream; one GPU helper | VRAM pressure |
| **C. Spark-side small model for dream** | Frees tower | Network hop |

**Recommendation:** **B or A, but not both.**  
- If dream must be always-on and non-blocking for Aetheria: **A (CPU) or small Quadro pin**, alias **`dream`**, set `SOVERYN_DREAM_COGNITION_URL=http://127.0.0.1:8089` (or new port) everywhere.  
- Delete or stop dual `cognition` alias confusion in `runtime.py` / clients that still send `model=dream` to wrong hosts.

---

## 6. Always-on process map (systemd)

### Inference (models)

| Unit | Port / role | Always-on |
|------|-------------|-----------|
| `soveryn-router.service` | :8090 Blackwell | **YES** |
| `soveryn-router-quadro.service` | :8091 Quadros | **YES** |
| `soveryn-embed.service` (**on Spark**) | `10.10.10.2:8096` Librarian — Nemotron-3-Embed-8B. Moved off the tower; `soveryn-embeddings.service` here is **inactive**. | **YES** |
| `soveryn-cognition.service` | :8089 dream brain — Gemma-4-26B-A4B, **CPU-only** (`--device none`, 48 threads) | **YES** (until unified) |
| `qwen-serve.service` (on Spark host) | :8001 — ⚠️ **name lies**, serves `lightning-30b` (§0) | **YES** |

### Control plane

| Unit | Role | Always-on |
|------|------|-----------|
| `soveryn-vnext.service` | Chat / tools / loops | **YES** |
| `soveryn-public-gate.service` | Auth front door | **YES** if public |
| `soveryn-heartbeat.service` | Aetheria pulse | **YES** |
| `soveryn-dream.service` | Quiet-hours reflection | **YES** (quiet schedule internal) |
| `soveryn-vett-patrol.service` | Vett initiation | **YES** if product on |
| `soveryn-signal-bridge.service` | Direct Line | **YES** if Signal on |
| `soveryn-ares.service` | Host sentinel (no LLM) | **YES** |
| `soveryn-searxng.service` | Search | **YES** if web tools on |
| `soveryn-cognition-cycle.service` | Deep cycle | Optional / gate carefully |
| `soveryn-representation.service` | Conclusions | Optional; note dry-run default |
| `parakeet.service` / `soveryn-f5tts.service` | Voice | As needed |
| `soveryn-medic.service` | Auto-heal | Optional; never restarts routers by policy |
| `soveryn-router-watchdog.service` | Dead slot recovery | Recommended **YES** once trusted |

---

## 7. VRAM budget (target, approximate)

| Card | Resident | Headroom goal |
|------|----------|---------------|
| **Blackwell** | Aetheria 31B Q6 + ctx + mmproj (~40–45 GiB peak under load) | ≥3–5 GiB free for spikes |
| **Quadro pair (NVLink)** | Treat as **up to ~96 GiB** for *one* multi-GPU model **or** two independent ~48 GiB single-GPU residents | Prefer: embed on one + mid helper on the other; optional tensor-split only with known-good preset |
| **Quadro A (`…990a`)** | Embeddings (~15–20 GiB used live) + optional small slots | Don’t park orphan 27B “just because preset exists” |
| **Quadro B (`…91f2`)** | Reflection / cognition helper / slack | Keep ≤80% for stability unless intentional NV-split |
| **Spark** | Laguna NVFP4 | Per Spark ops; not tower VRAM |
| **System RAM** | `cache-ram` 32 GiB+ for Aetheria; OS; CPU dream weights if any | Prefer cache over third big GGUF on CPU |

**NVLink use cases (Quadros only):**

| Pattern | When |
|---------|------|
| Two single-GPU models (one per Quadro) | Default always-on helpers — simple, stable |
| One model tensor-split across both | Need more than 48 GiB weights+KV for a *helper* (not Aetheria) |
| Blackwell + Quadro tensor-split | **Forbidden** — PCIe path, Xid-8 history |

**Anti-pattern:** Loading quadro preset `vett-scotty` 27B Q8 while Spark already serves workers — wastes ~30 GiB and heats a card for nothing.

---

## 8. Always-on operating rules

1. **Aetheria never shares Blackwell.** No embed, no dream, no vett on that UUID.  
2. **Quadros are an NVLink pair** — multi-GPU helpers only *within* that pair; never NV/tensor-split Aetheria onto a Quadro.  
3. **Pin by UUID** in every unit.  
4. **One live blackwell preset path** — never `cache-ram = 0` on production.  
5. **CUDA/driver/arch match Blackwell** — verify with tok/s, not “model loaded.”  
6. **Warm cache** after any router restart: one short completion before declaring healthy.  
7. **Spark is workers; tower is self + Quadro helpers.**  
8. **Dry-run daemons are not “always-on intelligence”** — flip env only when you want writes.  
9. **Unload unused shepherd/messie** unless a product path needs them daily.  
10. **Acceptance probe after any CUDA or preset change:**
   - Short: “OK” &lt; 1 s after warm  
   - Large: ~8–17k prompt prefill rate logged (target: hundreds+ tok/s on Blackwell once CUDA is correct)  
11. **SSOT for routing:** `soveryn/config/runtime.py` must match live units; comments that say 8089 vs 8091 must be fixed when you unify cognition.

---

## 9. Implementation checklist (bring live → target)

- [x] **Confirm Blackwell prefill tok/s after CUDA fix — DONE 2026-08-12.** Same 14,899-token probe: **111 → 1,592 tok/s**. Router logs date the regression to the hour: Jun 25–Aug 7 steady 1,300–1,800; Aug 8 12h **1,383**; Aug 8 13h **97**; flat ~90–110 until fixed. The llama.cpp rebuild at 11:49 that morning is the delta.  
- [ ] Watermark/delete `runtime/router-presets.ini` and `data/router-presets.ini` if they still ship `cache-ram = 0`  
- [ ] Retire or comment out `[vett-scotty]` on quadro preset (Spark owns workers)  
- [ ] Unify dream/cognition: one URL, one alias, one unit  
- [ ] Align `runtime.py` MODEL_SERVERS cognition row with that choice  
- [ ] Drop orphan nomic embeddings from quadro max-load path  
- [ ] Document messie :5066 keep/kill  
- [ ] Enable router-watchdog if recovery policy is trusted  
- [ ] Optional: Bot registry + workspaces (local Grok Bot layer) on top of this map  

---

## 10. Quick reference — ports

| Port | Owner |
|-----:|-------|
| 5001 | vNext Flask |
| 5066 | messie (optional) |
| 8000 | Spark Laguna (remote) — **stopped + disabled 2026-08-12** |
| 8001 | Spark Qwen3.6-35B-A3B (remote) — Vett, Scotty, PondWright, Atticus, Seneca |
| 8200 | PondWright agent (on Spark) |
| 8400 | Seneca / soveryn-agent (on Spark) |
| 8500 | Atticus (on Spark) |
| 8087 | Parakeet STT |
| 8089 | Dream/cognition surface (live unit alias `dream`) |
| 8090 | Blackwell router (Aetheria) |
| 8091 | Quadro router |
| 8095 | SearXNG |
| 8096 | Nemotron embeddings |
| 8188 | ComfyUI |

---

## 11. One-page mental model

```text
ALWAYS ON
  Self:     Aetheria @ Blackwell :8090          (identity + chat + pulse)
  Workers:  Qwen3.6-35B @ Spark :8001         (Vett, Scotty, PondWright,
                                               Atticus, Seneca -- ALL of them)
  Helpers:  Quadro pair NVLink :8091           (embed / cognition / reflection;
            optional tensor-split mid model on BOTH Quadros only)
  Memory:   Embed   @ one Quadro :8096         (lattice)
  Mind-bg:  Dream   @ :8089 (until unified)    (quiet reflection)
  Host:     Ares    (no LLM)
  App:      vNext   :5001

NEVER
  Co-tenant Aetheria's GPU
  Tensor-split Blackwell ↔ Quadro (no NVLink; Xid history)
  Load cache-ram=0 presets in prod
  Keep dead 27B on Quadro after Spark move
  Trust "model loaded" without tok/s
  Rebuild llama.cpp without checking `ldd ... | grep cublas` says .so.13
```

---

*This map is the intended always-on constellation for SOVERYN on tower + Spark. Update §4 live snapshot when hardware or ports change. Prefer editing this file over inventing a third router preset.*
