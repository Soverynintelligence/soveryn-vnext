# Target compute layout — tower + Spark

**Date:** 2026-08-14  
**Status:** target (not fully applied)  
**Hardware truth:** EPYC 7763 (128 thr) · 512 GB RAM · 2× Quadro RTX 8000 NVLink · RTX PRO 5000 Blackwell 48 GB · DGX Spark 128 GB UMA · ConnectX-7 tower↔Spark  

**Measured lesson:** Dense / large models on **tower GPU (and even CPU for some loads)** beat **Spark** on tok/s. Spark is for **MoE + product apps + huge fit**, not dense day-to-day chat.

---

## 1. Role of each box

| Platform | Job | Not for |
|----------|-----|---------|
| **Blackwell 48 GB** | Aetheria face — best single-user chat quality | Parking Vett research, Comfy, embed |
| **2× Quadro 48 GB NVLink (96 GB)** | Dense quality, vision, TP heavy, bake-offs | Display-only junkyard (keep display on one, compute on both) |
| **Spark 128 GB UMA** | Always-on **MoE** agents (Lightning), PondWright / Atticus / tunnels | Dense 27B/70B daily chat |
| **EPYC + 512 GB** | Orchestration, dream/CPU models, Comfy fallback, indexes, headroom | Pretending CPU is the default chat path (GPU when interactive) |
| **CX-7** | One lab fabric — route by job, not by “everything local” | Running Spark models over Wi‑Fi |

---

## 2. Target map (who lives where)

### Blackwell (GPU2) — face

| Workload | Model | Port / unit | Notes |
|----------|--------|-------------|--------|
| **Aetheria** | Gemma-4-31B Q6 + mmproj | router :8090 → child ~39839 · `soveryn` fleet | **Keep.** ~30 GB. Do not co-tenant big second models. |

Optional later: tiny helpers only if free ≥12 GB sustained.

### Quadro NVLink pair (GPU0 + GPU1) — muscle

| Workload | Model | Target | Notes |
|----------|--------|--------|--------|
| **Dense quality / Vett bake-off** | Qwen3.8-27B (GGUF or vLLM) | GPU0+1 or single Quadro | **Faster than Spark** for dense — primary home for “try new Qwen” |
| **Vision** | Nano Omni GGUF/vLLM or Qwen2-VL | Quadro free space | Eyes for Vett via tool or route; not on Lightning |
| **Embeddings** | Nemotron-Embed-8B | GPU0 :8096 | Keep (~16 GB); already correct card |
| **Parakeet STT** | parakeet-tdt-0.6b | GPU1 :8087 | Keep (~5 GB); stay off Blackwell |
| **Messie** | Qwen3.5-9B | GPU1 :5066 | TGTHR; small |
| **Reflection** | Qwen3.5-9B | GPU0/1 | Aetheria reflect; keep modest |
| **F5-TTS** | local voice | GPU0 :8088-ish | ~1 GB; fine |
| **Display / desktop** | — | GPU1 | Prefer display on **one** Quadro only |

**Use NVLink** when loading one large dense/VL across both cards (TP). Idle NVLink = wasted opportunity.

### Spark — always-on agents + products

| Workload | Model | Port / unit | Notes |
|----------|--------|-------------|--------|
| **Vett + Scotty default** | **Nemotron 3.5 Lightning 30B-A3B** | :8001 `qwen-serve` / brain switch | Fast tools + thread; pin default |
| **Optional vision-on-Spark** | Nano Omni NVFP4 | second profile or swap | Only if not loaded on tower |
| **Product apps** | — | pondwright-*, atticus, soveryn-agent, tunnels | Stay on Spark |
| **Large MoE later** | Super 120B etc. | dedicated window | Accept lower tok/s or dual Spark |

**Do not** leave Qwen3.8 dense as Vett’s daily on Spark.

### CPU / 512 GB RAM — orchestration + heavy offload

| Workload | Target | Notes |
|----------|--------|--------|
| **vNext** | :5001 | Agent house |
| **Dream / cognition** | :8089 CPU today | OK on RAM; move to Quadro free slice if dream latency matters |
| **ComfyUI** | :8188 CPU today | Move to Quadro when generating seriously |
| **Indexes / lattice / browsers** | RAM | Headroom is a feature |

Honest: CPU large-model runs can beat Spark for **dense**; still prefer **Quadro** for interactive dense when GPU free.

---

## 3. Routing rules (CX-7 lab)

Single decision table for the house:

| Request shape | Backend |
|---------------|---------|
| Aetheria chat | Blackwell Gemma |
| Vett/Scotty research, tools, long thread | **Spark Lightning** |
| Dense quality / compare / “new Qwen” | **Tower Quadro** |
| Image / screenshot | **Tower VL / Omni** (or Omni swap) |
| PondWright / public products | Spark :8001 (prefer Lightning; keep alias aligned) |
| Huge MoE / Super | Spark dedicated or dual Spark later |

Implement with: existing `switch_vett_brain.sh` short-term · LiteLLM / Switchyard medium-term · SOVERYN `ModelServer` entries long-term.

---

## 4. Current → target deltas

| Item | Current (2026-08-14 snapshot) | Target |
|------|-------------------------------|--------|
| Vett brain | Qwen3.8 dense **on Spark** | **Lightning on Spark** daily |
| Dense Qwen3.8 | Spark only | **Serve on Quadros** for trials |
| Aetheria | Blackwell | Unchanged |
| Embed + STT + Messie + F5 | Quadros | Unchanged (tidy if needed) |
| Dream / Comfy | CPU | Optional GPU when free |
| NVLink | Idle for TP | Use for dense/VL TP |
| Super / large | Occasional Spark | Spark window; dual Spark when needed |

---

## 5. Buy-trigger (one more GPU)

**Do not buy** until after rebalance.

Buy **one more tower GPU** only if:

1. Aetheria must stay exclusive on Blackwell **and** you need a second concurrent high-quality chat/vision gen, **or**
2. Quadro free space stays &lt;12 GB while you need concurrent dense + VL + embed + STT.

Prefer: modern **48 GB+** next to Blackwell for parallel face/worker — **not** another slow card to “fix Spark.”

Buy **second Spark** when the goal is **200B+/405B-class** local, not mid MoE concurrency.

---

## 6. Large MoE test — Qwen3-235B-A22B (2026-08-14)

| Item | Value |
|------|--------|
| Weights | `Downloads/Qwen3-235B-A22B-Q4_K_M-*.gguf` (~133 GB) → symlink ` /mnt/soveryn_models/GGUF/qwen3-235b-a22b-q4km/` |
| Serve | `scripts/serve-qwen235-tower.sh` → **:8100** alias `qwen235-a22b` |
| Devices | **CUDA1+CUDA2** (two Quadros only; Blackwell left for Aetheria) |
| Offload | `-ot exps=CPU` · experts in RAM · non-experts on NVLink pair |
| Smoke | `QWEN235_OK` · **~10.9 tok/s** decode · ~4.5 tok/s prefill (first token cold) |
| Stop | `kill $(cat /tmp/qwen235-tower.pid)` · log `/tmp/qwen235-tower.log` |

Confirms: tower hybrid **can** host 235B MoE while Aetheria stays up. Not a daily Vett default — large lane.

## 7. Apply order

1. Pin Vett default → Lightning (`switch_vett_brain.sh lightning` + document as default).  
2. Stand up Qwen3.8 (or GGUF) on Quadro path for quality A/B when 235B is down.  
3. Wire attachment/vision route to tower VL/Omni.  
4. Align PondWright `model` alias with active Spark brain (or auto-pick first model).  
5. Optional: Comfy + dream onto free Quadro slices.  
6. Revisit hardware purchase.  
7. Optional: route “large” Vett turns to :8100 when 235B is up.
---

## 8. One-line doctrine

**Blackwell talks. Quadros think dense and see. Spark runs MoE agents and products. RAM orchestrates. CX-7 unifies. Spark is not the dense king — the tower already proved that.**
