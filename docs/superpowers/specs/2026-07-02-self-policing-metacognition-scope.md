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

## v1 and v2 are complementary layers, not a ladder

**Correction to an earlier framing:** the heuristic gate (v1) and the self-policing signal (v2) are
**not** "cheap stopgap → better replacement." They catch **different failure classes**, and you want
both running permanently:

- **v1 (claim-shape gate)** fires on *"verifiable claim + no source consulted this turn"* —
  **regardless of how confident the model is.** So it catches **stable confident-wrong**: a strong
  false belief the model states flatly and would repeat identically every time (e.g. "the ROMED8-2T
  is Intel"). This is the *dangerous* class — confident and false.
- **v2 (semantic entropy et al.)** catches *"the model genuinely doesn't know and is flailing"* — the
  wobbly-unknown class, where answers diverge across samples.

Critically, **v2 is blind to the exact failure that started this work** (see the limitation under
approach #1). So v2 never retires v1. The gate spec's phrase "v2 raises the ceiling" is corrected
here: v2 *adds a second class of coverage*; v1 remains load-bearing for the confident-wrong class.

## Three approaches (tractability-ordered; measure before committing)

### 1. Semantic entropy / self-consistency — **recommended first**
**Idea:** sample the model N times on the same question; cluster answers by *semantic equivalence*;
compute entropy over the clusters. A fact the model actually knows returns **stable** (one cluster,
low entropy); a confabulation **wobbles** (many clusters, high entropy). High entropy → flag.

- **Why first:** no weight surgery, no labeled training data, and a published research basis
  (semantic entropy for hallucination detection — *Farquhar/Kuhn et al., Nature 2024*). **⚠ Citation
  from memory — verify before this is load-bearing** (same rule as Vett: an unverified reference is
  itself an unsourced claim). Works on any model behind an OpenAI-shape endpoint — including the
  router-served vanilla Qwen Vett already runs.
- **Cost:** N× inference per gated question (N≈5–10). Real on a compute-constrained box — so it fires
  **only when the cheap v1 detector already flagged risk**, not on every token. v1 heuristic = cheap
  pre-filter; semantic entropy = the confirming signal. They compose.
- **Mechanism sketch:** `SemanticEntropySignal.assess()` → resample the drafted answer's core claim N
  times at moderate temperature → cluster (embedding cosine via the existing nomic-embed backend, or
  an NLI-style equivalence check) → entropy over cluster masses → `risky = entropy > threshold`.
- **⚠ Critical limitation — stable confident-wrong.** Semantic entropy measures *inconsistency*, so
  it only flags what the model is *uncertain* about. A **stable false belief** — one the model states
  flatly and repeats identically across all N samples — produces **low** entropy and is **waved
  through** as confident-therefore-fine. The Intel-board error is plausibly exactly this class. So
  semantic entropy is **blind to the most dangerous confab** (confident and false); that class is
  covered by the v1 claim-shape gate and, eventually, activation probes (#3) — not by this signal.
  Do not let its sophistication disguise this hole.
- **Open question to MEASURE first:** on *your* model, does semantic entropy actually separate
  confab from recall on a labeled hardware/spec set — and how much of your real confab is the
  stable-wrong class it *can't* catch? Build the measurement harness before the production signal.
  (Verification-standard discipline: measure, don't assume.)

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
