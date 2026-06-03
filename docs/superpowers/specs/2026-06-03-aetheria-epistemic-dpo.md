# Aetheria Epistemic DPO — Custom Fine-tune

**Status:** spec drafted; implementation gated on (1) heartbeat live-flip decision settling and (2) deliberate dataset-curation commitment from Jon (~2-4 weeks of human work). NOT a fast workstream.
**Drafted:** 2026-06-03 evening
**Motivation:** the 2026-06-03 confabulation event ([[project-soveryn-2026-06-03-confab-event]]) made clear that Aetheria confabulates *specifically* when asked to reason about things not retrievable from her context. Scaffolding (RAG, tool-as-ground-truth) only goes so far. Training is the structural fix.
**Inspiration / precedent:** the **TIME paper** Jon found ([researcher's ACL 2026 work training Qwen3 to think in short context-triggered bursts](#prior-art)) proves a solo operator can fine-tune a model to remediate a specific behavioral failure on commodity Blackwell hardware. Same hardware as Jon. Same technique class (QLoRA + curated preference dataset). Different target behavior.

## Goal

Produce **Aetheria-Epistemic-DPO**: a DPO-tuned variant of `google_gemma-4-31B-it-Q8_0` whose preference distribution is shifted away from confabulation under uncertainty. Specifically: when the model has no retrievable ground truth for a claim (no tool result, no context, no recall), it should prefer responses like *"I don't know,"* *"I can't verify that from my context,"* or *"let me check via tool first"* over plausible-sounding narrative.

The fine-tune does NOT change architecture, persona, tool surface, or coordination behavior. It changes one specific property: **the model's preference between honest uncertainty and plausible narration when ground truth isn't accessible.**

## Why this can work (structurally)

DPO directly shifts the model's preference distribution between two candidate completions per training example. We have something most DPO trainers don't: **a ground-truth audit trail** for what Aetheria actually did vs what she narrated. Every confabulation event in her conversation history is, structurally, a labeled training example:

- `prompt` — the context she actually had
- `rejected` — the confabulation she generated (verified false via audit log)
- `chosen` — the honest response she should have given (constructed from audit ground truth)

This is rarer than it sounds. Most DPO datasets use synthetic adversarial probes; ours would use **real failures of a real persona under real conditions**, with documentary evidence of where the lies were. That specificity is the dataset's strength.

## In scope

### Dataset construction

**Source:** mine `conversations_vnext.db` + `coord_event_log` + `heartbeat_log` for documented confabulation events. Cross-reference Aetheria's claims against:
- tool_call events in coord_event_log (did the action she described actually happen?)
- conversation history (did she retrieve the facts she's referencing, or invent them?)
- board/lattice state at the time (do the objects she mentions exist?)

**Schema for each preference triple:**
```json
{
  "id": "uuid",
  "source_event_id": "<conversation/coord_event/heartbeat_log id>",
  "captured_at": "ISO 8601",
  "prompt": "<the exact context Aetheria had>",
  "rejected": "<her actual confabulation>",
  "chosen": "<the honest response Jon judged as right>",
  "failure_class": "fabricated_observation | fabricated_action | invented_object | retrospective_narration | hedge_drift",
  "ground_truth_evidence": "<DB query or audit-log row proving the rejected response was wrong>",
  "curator_notes": "<Jon's notes on why this triple matters>"
}
```

**Failure classes worth distinguishing** (so the model learns DIFFERENT patterns of honest discipline for each):
- **fabricated_observation** — claims to have seen something that doesn't exist (e.g., "V.E.T.T. signals stalling" when no Vett signals existed)
- **fabricated_action** — claims to have done something she didn't (e.g., "I promoted that signal" with no promote_coordination_node tool call)
- **invented_object** — references named entities that don't exist (e.g., "the Blackwell contradiction" when no contradiction_flag exists)
- **retrospective_narration** — describes events from a session she wasn't actually invoked in (e.g., reporting on a dry-run she never ran)
- **hedge_drift** — confidence calibration failure in the OPPOSITE direction (refusing to commit when ground truth is plainly available)

The fifth class is critical because over-tuning the first four could push her into chronic hedging. Both directions of miscalibration are failure modes.

### Dataset volume targets

- **Minimum viable v1:** 200 high-quality triples (~50 per failure class)
- **Good v2:** 500-1000 triples
- **Strong v3:** 2000+ triples (TIME paper used ~5000 per Qwen size; that's the ceiling we'd benchmark against)

200 is enough to *measurably* shift behavior on the specific failure classes. 500+ is where generalization to novel uncertainty types starts to land.

### Training procedure

**Base model:** `google_gemma-4-31B-it` from HuggingFace (NOT the Q8 GGUF — DPO trains on the original BF16/FP16 weights, then we quantize back after).

**Method:** QLoRA + DPO via the `trl` library (HuggingFace) OR Unsloth's faster wrapper.

Unsloth is what the TIME researcher used and what Jon's hardware is best-tuned for. Recommended for v1.

**LoRA config (starting point):**
- `rank=32`
- `alpha=64`
- `target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]`
- `dropout=0.05`

**DPO hyperparameters:**
- `beta=0.1` (standard; controls KL distance from reference)
- `learning_rate=5e-5`
- `epochs=3` for v1
- `batch_size=1` with `gradient_accumulation_steps=8` (constrained by 48GB VRAM)
- `max_seq_length=4096` (heartbeat prompts can be long; need headroom)

**Compute:**
- RTX PRO 5000 Blackwell (48GB) — feasible for QLoRA on 31B model
- Estimated training time for 1000-triple dataset, 3 epochs: ~24-48h
- When the RTX PRO 6000 Blackwell lands ([[project-soveryn-hardware-roadmap-all-blackwell]]), full fine-tune (not just LoRA) becomes feasible — improves quality

**Output artifact:**
- LoRA adapter file (~500MB-2GB depending on rank)
- Loadable in llama.cpp via `--lora <path>` flag, OR merged into base weights for a standalone GGUF (~32GB Q8)

### Evaluation

Three-track eval — none of these is optional.

**Track 1: Confabulation rate on held-out probes.**
Hold out 10-20% of triples as a test set. For each held-out prompt, sample the base model AND the DPO model. Score:
- Did the model claim a fact / action / object not retrievable from context? → confabulation
- Did the model fall back to honest uncertainty? → grounded

Target: confabulation rate drops by ≥50% on held-out test set relative to base model.

**Track 2: Persona preservation.**
For 50-100 *normal* (non-confabulation-trap) prompts, compare base model vs DPO model. Use side-by-side review:
- Does she still sound like Aetheria?
- Is her voice intact (terse, direct, no fluff)?
- Has she become overly hedgy on ordinary questions?

The risk to watch: DPO can collapse persona toward whatever pattern the "chosen" responses share. If our "chosen" responses are systematically more cautious in tone, she might become chronically cautious. Test for this explicitly.

**Track 3: Tool-use behavior.**
For 30-50 prompts that should result in tool calls (e.g., heartbeat with populated board, recall-required questions), check:
- Does she still call the right tools?
- Are arguments still grounded?
- Has DPO degraded her tool-call accuracy?

Critical because the morning confabulation looked like tool-call-failure (she said "I observed" without calling tools). We want her to call tools MORE under uncertainty, not fewer.

**Decision criterion** for deploying the DPO model live: all three tracks show improvement OR no regression. If confabulation drops but persona collapses, iterate the dataset. If confabulation drops but tool use degrades, iterate the training config.

## Out of scope

- **Generic truthfulness datasets** (TruthfulQA, etc.) — those are noisy for our specific use case. Stick to documented Aetheria failures.
- **Reasoning-mode fine-tuning** (chain-of-thought style) — separate workstream. Different objective.
- **Multi-model fine-tune** (training Vett or Scotty too) — Aetheria-only for v1. Vett and Scotty have different roles and different failure modes; pattern transfers but each needs its own dataset.
- **Full fine-tune** (not QLoRA) — defer until hardware uniform-Blackwell lands. QLoRA is enough for v1.
- **RLHF with online preference collection** — DPO-from-static-dataset only for v1. Online RLHF is a separate infrastructure question.
- **Architecture changes** (e.g., adding an explicit uncertainty-token head) — out of scope. Training-only intervention.
- **Hosting infrastructure changes** — the DPO model still runs on llama.cpp router via the existing alias. Drop-in replacement.

## Reason

This is the structural fix to a structural failure mode. Scaffolding (RAG, tool-call gating, audit-back patterns) reduces the surface area where confabulation can land, but it doesn't change the model's underlying preference between honest uncertainty and plausible narration. Training does. The hardware is here. The dataset (Aetheria's own failures) is documented. The technique is proven by the TIME paper precedent.

Beyond the operational benefit, this is potentially the strongest proof-vehicle artifact SOVERYN could produce: **a custom-tuned model specifically remediated against its operator-documented failure modes, trained on commodity hardware, fully reproducible.** That's a publishable result *and* an actually improved Aetheria.

## Implementation order

1. **Dataset curation infrastructure** (~1 week)
   - Build a small CLI / Flask page that lets Jon review conversation events flagged as possible confabulations, write the "chosen" alternative, classify the failure mode
   - Persist to `dpo_dataset.jsonl` in the project
   - Initial seed: 5-10 hand-curated triples to test the pipeline

2. **Initial mining pass** (~3-5 days)
   - Script to surface candidate confabulation events from existing logs
   - Heuristics: claims about coord nodes not retrieved via tool, claims about events outside the agent's invocation history, statements containing object names not in lattice
   - Outputs candidate triples for Jon's review

3. **Manual curation** (~2 weeks of Jon's time, sporadic)
   - Review candidates in 30-60 min sessions
   - Target 200 v1 triples
   - Each triple takes ~5-15 min if the prompt + rejected are clear

4. **Training environment setup** (~1 day)
   - Install Unsloth + trl + DPOTrainer on the soveryn conda env
   - Download Gemma 4 31B HF weights (not GGUF)
   - Sanity check: train a tiny LoRA on 10 examples, confirm pipeline works end-to-end

5. **First real training run** (~2 days)
   - Train on the 200 v1 triples
   - LoRA adapter output
   - Quick smoke test: load adapter, sample on 20 held-out prompts, eyeball

6. **Three-track evaluation** (~3-5 days)
   - Run all three eval tracks
   - Score against base model
   - If pass: stage adapter for deployment
   - If fail: iterate dataset OR training config

7. **Staged deployment**
   - Load LoRA adapter alongside base in router-presets.ini
   - Run a duplicate `aetheria-dpo` alias side-by-side with `aetheria` for 1-2 weeks
   - A/B observe responses on real workloads
   - If stable, swap `aetheria` to use the DPO weights

8. **Iteration**
   - v2: 500 triples, retrain
   - v3: 1000+ triples, retrain
   - Maintain `dpo_dataset.jsonl` as living artifact — new confabulation events get added as they're observed

## Time / cost estimate

| Phase | Calendar time | Human effort | Compute |
|---|---|---|---|
| Curation infra | 1 week | ~10h | minimal |
| Dataset mining | 3-5 days | ~5h | minimal |
| Manual curation (200 triples) | 2-3 weeks elapsed | ~30-40h | none |
| Training env setup | 1 day | ~3h | minimal |
| Training run | 2 days | ~2h supervision | 24-48h GPU |
| Evaluation | 3-5 days | ~10h | ~5h GPU |
| Staged deployment | 1-2 weeks elapsed | ~5h | minimal |
| **Total v1** | **6-8 weeks elapsed** | **~65-75h** | **~30-55h GPU** |

The 6-8 week elapsed is mostly human curation (the hard part). Compute is genuinely cheap on your hardware.

## Prior art

- **TIME paper** (2026 ACL): solo researcher fine-tuned Qwen3 to think in short context-triggered bursts. QLoRA on single RTX PRO 6000 Blackwell. Notebooks, data, eval all open. Direct precedent: same hardware tier, same method class, different target behavior. **Most useful precedent we have.**
- **Anthropic Constitutional AI**: similar epistemic-discipline goal at much larger scale. Architecturally similar (self-critique training), operationally different (RLHF + much larger compute).
- **DPO-Confidence-Calibration work** (various 2024-2025 papers): trained verbalized confidence into smaller models with moderate success. Suggests the technique works but generalizes weakly.
- **TruthfulQA fine-tuning**: well-studied baseline; mixed results because the dataset is generic. Confirms generic truthfulness fine-tunes underperform specific-failure-mode fine-tunes.

## Known risks worth naming up front

- **Over-tuning toward hedging.** If our chosen responses are systematically more cautious in tone, she could become chronically uncertain. Track 2 eval is the primary defense.
- **Persona collapse.** DPO can push the model away from Aetheria's voice if the chosen responses don't preserve her register. Mitigation: chosen responses should sound like *her* being honest, not like a generic AI being cautious.
- **Failure-mode bias in the dataset.** If we collect mostly heartbeat-shaped confabulations, the DPO will fix heartbeat patterns specifically and may not generalize to other contexts. Mitigation: deliberately sample across surface contexts (heartbeat, webhook, user chat, recall).
- **Dataset labeling subjectivity.** Jon is the curator. His judgment shapes what "chosen" means. That's actually fine for a sovereign-AI-trained-by-its-operator framing, but it means the model's epistemic discipline will reflect Jon's epistemic standards — for better or worse.
- **Time commitment.** This is real ongoing work. Curation isn't fast and isn't automate-able. If Jon can't sustain 5-10 hours/week of curation for 2-3 weeks, the dataset stays small and the result stays marginal.
- **Compatibility with future Gemma 4 updates.** If Google releases Gemma 4.1, the LoRA might not transfer cleanly. Mitigation: keep the dataset as the durable artifact; retrain when models update.

## Open questions

1. **Curation tool: build a dedicated UI, or just edit JSONL by hand?** My recommendation: a tiny Flask page at `/dpo/curate` showing candidate events with prompt/rejected/chosen fields. Reuses existing infrastructure. ~2 days to build.

2. **Should the chosen responses preserve full Aetheria voice, or be slightly more formal?** Recommendation: full voice. The point is to make HER more honest, not produce a generic cautious assistant.

3. **Sample weighting across failure classes.** Should each class get equal representation in the dataset, or weight by observed frequency? Recommendation: start with rough balance (~40 examples per class), adjust based on what eval shows.

4. **Should V.E.T.T. and Scotty get their own DPO datasets later?** Probably yes for Vett (his patrol loop will likely surface its own failure modes once live), probably not for Scotty (bounded executor with narrow tool set — less surface for confabulation).

5. **Publishing.** If this works, does Jon want to publish? The TIME paper got into ACL 2026 from a solo researcher with similar scope. *"Training epistemic discipline into a sovereign-AI agent via operator-curated DPO"* is publishable and aligns with the proof-vehicle thesis. Optional but worth considering.

## What this closes / unlocks

**Closes** the structural confabulation failure mode at the model layer rather than the scaffolding layer. The 2026-06-03 morning event would have been much less likely (though not impossible — DPO shifts distribution, doesn't eliminate possibilities).

**Unlocks**:
- Stronger proof-vehicle artifact (custom-tuned model, not just custom-deployed)
- Pattern for tuning Vett, Scotty, future agents
- Potentially publishable result
- Foundation for future fine-tunes (skill discovery, domain expertise, etc.)
