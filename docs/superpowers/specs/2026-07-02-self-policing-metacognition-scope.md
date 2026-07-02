# Self-Policing Metacognition Layer (Scoping)

**Date:** 2026-07-02
**Status:** Scoping / design exploration — **not** a locked, buildable spec. Research-grade; some of
it will not pan out and must be *measured*, not assumed.
**Relationship:** Produces the **v2 trigger** for the Vett verification gate
(`2026-07-02-vett-verification-gate-design.md`). Same `ClaimRiskSignal` interface; the gate machinery
does not change.

## The goal, stated precisely

Build a layer that flags **the system's own uncertainty without external ground truth** — so the
model knows *when* it is probably confabulating, and can trigger "let me verify" from a real internal
signal rather than a regex proxy.

**What this is NOT:** it is not a truth oracle. It cannot tell you *what is true*. It is a **triage
layer** — it tells you *where to go look*. For "must be right" domains (Shepherd deadlines) you still
escalate to external ground truth + human. Self-policing lowers how often you must escalate; it never
removes escalation.

## The framing that keeps this honest

A single model in one forward pass **cannot** judge its own output — the generator and the judge would
be the same process, and "yes I'm sure" is itself a sampled (confabulatable) token. So "self-policing"
does **not** mean the model introspecting itself in-line. It means a **system** with a *separate
monitoring subsystem* watching the generator — exactly how human metacognition works (a slower
reflective process catches the fast one; you don't "just know" you're guessing either). We are
building that separate monitor. That is the raising of a trustworthy mind, not a restraint bolted onto
it.

## Three approaches (tractability-ordered; measure before committing)

### 1. Semantic entropy / self-consistency — **recommended first**
**Idea:** sample the model N times on the same question; cluster answers by *semantic equivalence*;
compute entropy over the clusters. A fact the model actually knows returns **stable** (one cluster,
low entropy); a confabulation **wobbles** (many clusters, high entropy). High entropy → flag.

- **Why first:** no weight surgery, no labeled training data, published and validated (Farquhar/Kuhn,
  *Nature* 2024). Works on any model behind an OpenAI-shape endpoint — including the router-served
  vanilla Qwen Vett already runs.
- **Cost:** N× inference per gated question (N≈5–10). Real on a compute-constrained box — so it fires
  **only when the cheap v1 detector already flagged risk**, not on every token. v1 heuristic = cheap
  pre-filter; semantic entropy = the confirming signal. They compose.
- **Mechanism sketch:** `SemanticEntropySignal.assess()` → resample the drafted answer's core claim N
  times at moderate temperature → cluster (embedding cosine via the existing nomic-embed backend, or
  an NLI-style equivalence check) → entropy over cluster masses → `risky = entropy > threshold`.
- **Open question to MEASURE first:** on *your* model, does semantic entropy actually separate
  confab from recall on a labeled hardware/spec set? Build the measurement harness before the
  production signal. (Verification-standard discipline: measure, don't assume.)

### 2. Logprob / entropy signal — cheap, weaker alone
**Idea:** low token-probability / high per-token entropy correlates (noisily) with hallucination.

- **Why relevant now:** the **DPO/logprob flagger sidecar already exists** (calibration mode,
  2026-05-21). This is a short hop from "log candidates" to "emit a live uncertainty score." Verify
  its current state before building on it (don't trust this memory blindly).
- **Limit:** correlation is weak and model-specific; good as a *cheap contributor* to a combined
  score, poor as a sole gate. Best used to *cheaply pre-rank* which questions deserve the expensive
  semantic-entropy pass.

### 3. Activation probes — strongest ceiling, sovereignty-only
**Idea:** train a small linear probe on the model's **hidden states** to detect "internally
represented as false/uncertain," which research shows can beat the model's *spoken* confidence.

- **Why it's uniquely ours:** requires access to the weights/activations. A corporate-API user
  **cannot** attempt this. SOVERYN's sovereignty is a real technical edge here, not just a value.
- **Cost/risk:** needs a labeled confab-vs-true dataset and **retraining on every model swap**
  (probe is model-specific). Highest engineering cost, highest potential payoff. Defer until #1 is
  proven and a model is stable enough to be worth probing.

## Recommended sequence

1. **Measurement harness first.** A labeled set of hardware/spec questions with ground truth (from
   `system_probe` + verified web). Run semantic entropy across it. **Does divergence separate confab
   from recall on the actual model?** Decision-gate the rest on this result.
2. If yes → build `SemanticEntropySignal` behind the gate's `ClaimRiskSignal` interface, fired only
   after the v1 heuristic pre-filter (cost control).
3. Fold in the logprob signal as a cheap pre-ranker (reuse the existing flagger).
4. Revisit activation probes once a model is stable and the payoff justifies the per-swap retrain.

## Cost & sequencing honesty (non-technical, load-bearing)

This is **weeks** of genuine, research-grade engineering — not a weekend, and not guaranteed to work
on the first model. It is almost certainly the single most important thing SOVERYN could build to
actually *be* what it claims (truthful AI that knows its own limits) rather than assert it. **But** it
competes directly with Shepherd-revenue-first. Recommendation: ship the **v1 gate** now (it delivers
the real behavior cheaply), stand up **only the measurement harness** for semantic entropy next (small,
decisive, tells us if the whole approach is viable on our model), and gate the multi-week build on
that measurement result **and** on Shepherd revenue landing.

## Open questions

- Threshold calibration for semantic entropy per model (needs the labeled set).
- Equivalence-clustering method: embedding-cosine (cheap, reuses nomic-embed) vs NLI (better,
  costlier). Measure both on the harness.
- Latency budget: N× inference on a gated question — acceptable for research/verification turns,
  likely not for latency-sensitive chat. Scope to Vett's research surface, not all agents.
- Interaction with abliterated agents (Aetheria): does semantic entropy behave differently on an
  abliterated model? (Cross-reference the abliterated-confab prior work.)
