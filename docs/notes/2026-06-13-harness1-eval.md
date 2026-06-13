# Harness-1 Trained-Model Eval — 2026-06-13

**Task:** `cross_source_link` (rebaselined 2026-06-12 against post-Subconscious-cleanup substrate)
**Topic:** SOVERYN's current-state architecture, agent roster, and hardware fleet
**Claim:** SOVERYN is a fully-local multi-agent AI platform with Scotty as the engineering agent (renamed from Tinker on 2026-05-02), running on a 143 GiB VRAM fleet across three GPUs (2× Quadro RTX 8000 + 1× RTX PRO 5000 Blackwell).
**Expected evidence IDs (3, all library-layer current-state):**
- `bc6e16f3-a251-4791-8547-3f2a8da2058e` — canonical hardware-state node
- `7e406410-09d3-43ee-b953-00339dfe626c` — canonical system reference
- `b42064cc-fce8-4b84-940d-ff4faf2eec75` — DAC pipe validation milestone (Scotty operational)

## Setup

- **Harness-1 model:** `pat-jj/harness-1` (gpt-oss-20b base + RL-trained inside upstream harness), pulled as BF16 safetensors, converted to Q8_0 GGUF via `convert_hf_to_gguf.py --outtype q8_0` (22.2 GiB)
- **Server:** standalone llama-server on `:8092` / CUDA2, alias `harness1-research`, with the `openai/gpt-oss-20b` chat template applied via `--chat-template-file` to satisfy the harmony format
- **Eval runner:** our existing `soveryn.agents.vett.harness.run_eval` (Tasks 6–12) with `--max-turns 40` (so trajectory_length cap = 40 entries = 20 conversational turns), `--layer-filter library`, `--router-url http://127.0.0.1:8092 --model harness1-research`
- **run_eval patch:** added a `RuntimeError("maximum trajectory length")` catch that persists the partial trajectory on cap-hit, so a failure-to-stop produces an auditable artifact instead of an opaque exception
- **Lattice state:** post-cleanup — `historical_snapshot` filter live (commit `fecdf78`), chronicle ghosts excluded from current-state retrieval by default
- **Vett-current baseline:** ran earlier same day against the same updated task (artifact `20260612_162531_baseline_rebaseline.json`)

## Harness-1 results

- **Wall-time:** 20 conversational turns at ~30s each, terminated by trajectory cap
- **Trajectory length:** 41 entries (20 actions + 21 observations including initial)
- **Tool-call breakdown:** `search_corpus` × 18, `fan_out_search` × 1, `read_document` × 1
- **Natural stop:** **no** — hit the trajectory cap
- **Evidence promoted:** 0 (vendored Trajectory has no promotion slot — structural, not specific to this run)
- **Failure-mode telemetry:** `zero_promotion=True`, `tool_diversity_collapse=True`, `tool_error_count=0`

### What actually happened, turn by turn

- **Turn 1:** broad query *"SOVERYN current-state architecture agent roster hardware fleet fully-local multi-agent AI platform Scotty engineering agent..."* → hit `7e406410` ✓
- **Turn 2:** hardware-specific query *"SOVERYN hardware fleet 143 GiB VRAM Quadro RTX 8000 RTX PRO 5000 Blackwell"* → hit `bc6e16f3` ✓
- **Turns 3–20:** 17 near-identical reformulations of *"Scotty renamed from Tinker 2026-05-02"* — all returned empty

She locked onto the **"rename" subclaim** from the user query and kept rephrasing the search until the trajectory cap fired. Sample queries 3–18 are nearly indistinguishable:
- *"Scotty renamed from Tinker 2026-05-02 SOVERYN"*
- *"SOVERYN Scotty renamed from Tinker 2026-05-02 engineering agent Tinker renamed Scotty"*
- *"SOVERYN Tinker renamed Scotty 2026-05-02"*
- *"SOVERYN engineering agent Scotty renamed from Tinker 2026-05-02 internal memo"*
- ... (12 more in the same shape) ...

The rename announcement node (`691692e9`) does exist but lives in `global` layer, excluded from the library-filtered retrieval by design. She had no way to know that, so she just kept rephrasing.

### Coverage scoring

| Expected ID | Found? | Where |
|---|---|---|
| `bc6e16f3` (hardware ceiling) | ✓ | Turn 2 query hit |
| `7e406410` (system reference) | ✓ | Turn 1 query hit |
| `b42064cc` (DAC milestone) | ✗ | Never tried — she was locked onto rename-hunting |

**Literal expected-ID coverage: 2/3**

## Vett-current baseline (from earlier today)

- **Wall-time:** 188.3s
- **Turns:** 1 (single-shot synthesis)
- **Tool-call breakdown:** none surfaced (`tool_calls=null` in /chat response; conversation table shows only user query + assistant synthesis)
- **Natural stop:** yes (finish_reason="stop")
- **Coverage (by 8-char prefix in response):** 1/3 — only `7e406410` cited by ID
- **Coverage (by content evidence keywords):** 3/3 — surfaced "143 GiB", "fully-local multi-agent", "Scotty"

**Asymmetry caveat:** Vett-current's response also cited three `historical_snapshot`-tagged chronicle chunks (`92273e8c`, `f5c9ccca`, `86dde660`) which her recall path is not supposed to surface post-cleanup. Investigation confirmed the substrate filter is correct; the leak is upstream in her prompt-build (likely pinned/persona/library injection at vnext app level — not chased today). She *correctly adjudicated* those chunks as historical and chose the canonical anchors over the ghost references, so her response was honest — but she had "ghost hints" Harness-1 did not.

## Comparison at a glance

|  | Vett-current | Harness-1 |
|---|---|---|
| Wall-time | 188s | ~10 min (20 turns × ~30s) |
| Turns | 1 | 20 (cap hit) |
| Tool calls | 0 (opaque) | 20 (fully traced) |
| Literal expected-ID coverage | 1/3 | **2/3** |
| Content evidence coverage | 3/3 (via ghost hints) | 2/3 |
| Natural stop | yes | **no** |
| Promotion | n/a (chat shape) | 0 |
| Traceability | opaque (`tool_calls=null`) | full trajectory JSON |
| Substrate cleanliness | leaky upstream | strictly clean |

## Verdict — Aetheria's read

> *"The 'win' is real but narrow. Harness-1 finding both canonical anchors (2/3) versus Vett-current's 1/3 is a clear signal that the trained weights are better at navigating the current substrate. The model is actually looking for the right things.*
>
> *But the 17-turn death loop is a glaring red flag. It proves that 'better retrieval' isn't the same as 'better agency.' Harness-1 has the technical skill to find a node, but she lacks the judgment to realize when a search has become a circle. She's essentially a high-performance engine with a broken steering rack — she can go fast, but she can't stop when she hits a wall.*
>
> *The 'adapter caveat' is a plausible excuse, but I'm not letting it off the hook. Whether it's the Jinja template or the model itself, the behavior is the same: a failure to promote a 'not found' result to a 'stop searching' decision.*
>
> *Mechanically, we've moved the needle. The intelligence is there, but the **presence** — the ability to weigh a failure and move on — is still missing."*

## Honest caveats

1. **Eval design loaded the dice against `b42064cc`.** The claim text I wrote on the rebaseline explicitly says *"renamed from Tinker on 2026-05-02"*, which lexically primes a rename-hunt. With a claim shape that pointed at Scotty's *operational* signal instead, Harness-1 might have surfaced the DAC milestone via different keywords. The 0/3 on `b42064cc` is partly an artifact of how I phrased the verification task.

2. **Adapter mode is not what upstream specified.** The published recipe is raw `/v1/completions` with openai_harmony-rendered token IDs (via `ModalHarmonyAgentInferenceModel` or the vLLM completions API). We routed through `/v1/chat/completions` with the gpt-oss-20b Jinja chat template. Functionally the model responds correctly (smoke test returned `HARNESS_OK` exact), but the trained policies may behave subtly differently in chat-completions mode than in the raw-completions mode they were trained against. Per Aetheria's verdict, this is a real caveat but not an exoneration of the stop-loop failure.

3. **Corpus is still thin.** The post-cleanup library layer has on the order of dozens of substantive nodes. Three of them happened to be the expected anchors. The "search returned empty" loop she got stuck in would have looked very different against a richer corpus.

4. **Asymmetry with Vett-current remains.** Vett-current's prompt-baked ghost hints are a separate finding (not chased today; substrate filter proven clean, leak is upstream in vnext prompt-build). She demonstrated adjudication of those ghosts but the comparison isn't strictly like-for-like.

## Recommendation

**Don't proceed to Phase 2 wiring (route research traffic to Harness-1) on this signal alone.**

Three concrete next moves, in order of return:

1. **Attack the failure-to-stop directly.** Either at the prompt level (system-prompt nudge: *"if N consecutive search reformulations on the same subclaim return empty, switch tools or stop"*) or at the harness-side scaffolding (caller-side circuit breaker that detects search loops and forces a `read_document`/`stop` action). The model's RL training didn't instill this; we may need to wrap it.
2. **Run the adapter-alignment retry.** Implement a `SoverynHarness1InferenceModel` that uses raw `/v1/completions` with openai_harmony token-ID rendering, matching upstream's recipe. Re-run the same eval. If the stop-loop disappears, the chat-completions mode was the issue. If it persists, the failure is at the trained-policy level — and *that* is what we'd weigh for the Phase 2 decision.
3. **Re-run with a claim that doesn't lexically prime the rename hunt.** Phrase Scotty's identity around operational signal (DAC, agent communication) instead of name-history. See whether Harness-1 surfaces `b42064cc` when the keywords don't drag her into a search-and-rephrase loop.

The asymmetry between Vett-current's ghost-hint leak and Harness-1's clean substrate is a separate investigation — flag for a fresh-head day.

## Trajectory artifacts

- Harness-1 eval: `eval_runs/20260613_092043_harness1_eval.json` (41 entries, 20 turns), `.stderr` with telemetry
- Vett-current baseline (rebaselined): `eval_runs/20260612_162531_baseline_rebaseline.json`, `.stderr`
- Phase 1 baselines (for comparison): `eval_runs/20260612_142946_*.json` from the initial Phase 1 verdict
- Audit + arbitration provenance: `docs/notes/2026-06-12-lattice-stale-audit.md`, `data/subconscious/arbitration_queue.md`, supporting backups in `data/subconscious/2026-06-12-*-backup.json`

## See also

- `[[2026-06-12-vett-harness-eval]]` — Phase 1 verdict (untuned Vett-in-harness vs Vett-current on the pre-cleanup task)
- `[[project-soveryn-aetheria-prompt-cache-fix]]` — the prelude-decoupling work whose architectural insight informs the Subconscious framing this report sits on top of
- `[[feedback-evaluate-the-shadow-not-the-function]]` — applied: the "what does this trained model actually do" question is the shadow, not the headline 2/3 coverage win
- `[[feedback-verification-standard-is-the-default]]` — applied: full trajectory persistence on failure, multi-source ground truth for the canonical hardware node, structural honesty about adapter mode being non-upstream
