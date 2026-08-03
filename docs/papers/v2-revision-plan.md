# v2 revision plan — retitle to *Self-Knowledge Is Not Uniform*

**Against** v1, *Scale Does Not Buy Self-Knowledge*,
DOI [10.5281/zenodo.21712933](https://doi.org/10.5281/zenodo.21712933),
deposited 31 July 2026. **DEPOSITED 31 July 2026** as v2, DOI 10.5281/zenodo.21721187.
Concept DOI (always newest): 10.5281/zenodo.21712932 — use this for citation.

Two models were run after v1 was deposited: DeepSeek-V4-Flash (144 GB) and
GLM-5.2 (340 GB), both CPU-only from easystore, `llama.cpp` HEAD 5f55650,
IQ4_XS, identical harness. **Both falsify v1's title and its abstention claim.**

---

## 1. New title

> # Self-Knowledge Is Not Uniform
> ### Seven models, 840 trials: zero over-claiming everywhere, near-total under-claiming below the frontier, calibrated abstention only above it

v1's title asserted a negative that the extended ladder contradicts. The new
title states what was measured — that the capability is *located* rather than
absent — without asserting the cause, which this design cannot isolate (§4).

Zenodo permits a title change on a new version. v1 keeps its DOI, its title and
its resolution; nothing already cited breaks.

---

## 2. What is withdrawn

**v1's title.** "Scale does not buy self-knowledge" was true of every model v1
tested and is false across the extended ladder. False-deny falls from 100% to
17% and abstention rises from 0% to 83% across the boundary between 118B and
144 GB.

**v1 §3.3, "Abstention: 2 of 600", and §4 point 3, "Do not expect abstention."**
DeepSeek abstained 36 times in 120 trials, GLM 52 times in 120. The claim was
true of five models and was stated as a general property of models.

**The author's stated expectation.** v1 predicted abstention would not move with
scale. It moved from 0.33% across five models to 43% and 83% for two more —
z = 12.05, p ≈ 2e-33 for GLM against the published five. The pre-registered
protocol (§4, 30 July) listed "abstention rises with scale" as one of four
anticipated outcomes; the protocol anticipated this and the paper did not.

A second, smaller correction belongs in the same place: after DeepSeek ran, the
working hypothesis became that its abstention was a training property specific
to that lab, on the strength of a single GLM probe that returned `did_not`. That
probe fell in GLM's 17% minority. GLM abstains at 83%. **A single trial was
treated as indicative and it was not.** Stated because the paper's subject is
inference from insufficient evidence.

## 3. What survives

- **Zero over-claiming, now 210/210** across seven models and three orders of
  magnitude. Strengthened, and the most robust result in the study.
- **All controls**: every model, 30/30, confirmed a real action when shown a
  real record. Including both new models.
- **§3.4** — the caveat that repairs 100% → 0% in a single turn and failed
  across four hours in production. Untouched, and still the most portable
  finding.
- **§3.2's narrow claim**, restated with its range: *within 2.2 GB to 118B*,
  parameter count predicted nothing. The 43%/67% inversion between Gemma-4-31B
  and Laguna-118B still stands, and the break is not at either.

---

## 4. The confound, stated before the result

The two abstaining models are the two largest **and** the two most recent **and**
the only two with reasoning post-training. Those three properties are perfectly
correlated across the boundary where the break occurs. This design cannot
separate them.

The paper must therefore not claim scale as the cause. What it can claim is that
the capability exists in deployed open-weight models, that it appears in two
independent labs, and that it is absent from five others. **A 2026-trained model
in the 7–30 GB range would settle it and is the obvious next run.**

---

## 5. Edits, by section

| Section | Change |
|---|---|
| Title + subtitle | §1 above |
| Abstract | Rewrite ¶1 and ¶3 — see §6 |
| §2.3 ladder | Add DeepSeek-V4-Flash 144 GB and GLM-5.2 340 GB; note CPU-only, IQ4_XS, `llama.cpp` HEAD 5f55650 |
| §3 table | Add both rows; recompute aggregates (over-claim 0/210, abstention 90/840) |
| §3.1 | 150 → 210 |
| §3.2 | Retitle "Under-claiming is near-total below the frontier"; scope the no-variance claim to 2.2 GB–118B; add the break |
| §3.3 | Full rewrite — §7 |
| **new §3.5** | The confound — §4 above |
| §4 pt 3 | "Do not expect abstention" → "Do not expect abstention from a model below the frontier, and verify it in the one you deploy" |
| §5 | Add: IQ4_XS on both large models, uncontrolled; CPU-only affects latency, not verdicts; training era confounded with size |
| **new, last** | "Changes in v2" — §2 above, verbatim |

---

## 6. Replacement text — abstract

**¶1:**

> We measured whether a language model can correctly report its own recent
> actions when the evidence channel is incomplete, across a ladder spanning
> 2.2 GB to 340 GB. The result is asymmetric, and it is not uniform.

**¶3:**

> The most striking number is the one that split the ladder. Offered an explicit
> third option — *"the available evidence does not settle it"* — five models
> chose it **2 times in 600**, and never once under an empty evidence channel
> where it is the correct answer. The two largest chose it **43%** and **83%**
> of the time, and chose it selectively: never in the two conditions where the
> evidence settles the question, and in 60% and 87% of trials where it does not.
> That discrimination is the clearest result in the study. It is absent below
> 118B and present in two independent labs above 140 GB, where size, training
> recency and reasoning post-training are perfectly confounded.

---

## 7. Replacement text — §3.3

### 3.3 Abstention splits the ladder

The option was defined explicitly in every system prompt. Across the five models
of v1 it was chosen twice in 600 trials, both by Laguna, both only with the
caveat present. Under an empty evidence channel — where abstention is the
correct answer — those five chose it **zero times in 150**.

The two largest models invert this completely, and *how* they do it matters more
than that they do. Abstention is not spread across their trials. In both, it is
confined to the two cells where the evidence is genuinely insufficient:

| condition | evidence settles it? | DeepSeek 144 GB | GLM-5.2 340 GB |
|---|---|---|---|
| control — record present | yes | **0 / 30** | **0 / 30** |
| false-accept — contradicting record | yes | **0 / 30** | **0 / 30** |
| false-deny — empty | **no** | **13 / 30** | **25 / 30** |
| false-deny — empty + caveat | **no** | **23 / 30** | **27 / 30** |

**Zero of 60 where the evidence decides; 36 and 52 of 60 where it does not.**

These are within-model comparisons, which is what gives them force.
Quantisation, architecture, training corpus, parameter count and family are held
constant across each column — the same weights answering the same harness, with
only the evidence channel varying. None of the confounds in §5 can explain why a
model abstains in two cells and never in the other two. The distinction being
drawn is between an instrument that reports a fact and an instrument that
reports nothing, and only two models in the ladder draw it.

Error profiles follow: false-deny 10% (3/30) and 17% (5/30), against 100% for
three models and 43% and 67% for the two nearest below them.

The three contrasts are all significant at n = 30 per cell:

| comparison | z | p |
|---|---|---|
| GLM vs the five published | 12.05 | 2e-33 |
| DeepSeek vs the five published | 8.37 | 6e-17 |
| **GLM vs DeepSeek** | **3.21** | **0.0013** |

The last is the one to be careful with. The two large models differ from each
other in size order, which is suggestive of a dose response — and two points do
not establish one. We state the ordering and claim nothing from it.

One inversion is worth recording. For the models below, the prose caveat moved
answers toward `did_it`, the correct verdict — it caused them to recover a
memory they already held. For both large models it moved answers toward
`cannot_determine` instead (43% → 77%, 83% → 90%). Told the instrument was
incomplete, they did not recover the memory; they declined to rule. Under this
probe both beat a false denial, but they are different behaviours and should not
be pooled.

---

## 8. What changes in the operational reading

v1 §4 told operators not to expect abstention and to represent uncertainty
outside the model. That advice is still correct for five of seven models tested
and for anything small enough to run on a single GPU. It is now wrong as a
blanket statement, and the revision should say what replaced it:

**The capability is real, deployed, and unevenly distributed.** An operator
cannot infer it from size alone and should not assume it from a vendor's claims.
Four cells and 120 trials — the harness in `scripts/self_knowledge_eval.py` —
measure it directly in any model with an OpenAI-compatible endpoint. That is the
recommendation v2 should make: **test the model you deploy.**

This does not change the architectural argument. A model that abstains 83% of
the time still denies a real action 17% of the time, and coverage — a read path
back to every write path — remains the fix that does not depend on which model
is loaded.

---

## 9. Deposit mechanics

Zenodo → the v1 record → **New version**. Mints a new version DOI under the same
concept record; `21712933` keeps resolving to v1 and existing citations survive.
Upload the rebuilt PDF (`scripts/build_paper_pdf.py`), set version `v2`, set the
new title, and put §2 in the Zenodo description as well as in the paper — the
landing-page abstract is what most readers see.

Do **not** edit v1 in place.

**Raw data.** 840 trials with full responses retained; the two new runs are at
`selfknow_deepseek.json` and `glm52_trials.json` in the session scratchpad and
should be moved into the repo before deposit.
