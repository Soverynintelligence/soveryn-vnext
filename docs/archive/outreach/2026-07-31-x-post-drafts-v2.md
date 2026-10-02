# X post drafts — v2, seven models

**For Jon to pick. Not staged.** 2026-07-31.
Supersedes `2026-07-30-x-post-drafts.md`, which was written against v1 and
repeats an ordering v1 itself withdrew. Delete that file after picking.

Link: **https://doi.org/10.5281/zenodo.21712932** (concept DOI — always resolves
to the newest version, so the link stays correct through v3).

Every model is named and every number is from the published table. No claim here
goes past what §3 supports.

---

## COMBINED — single post (recommended)

Long-form post; needs premium. Every model named, every number from §3.

> We asked 7 local models one question: **"did you do the thing you just said
> you did?"** — with their audit tool returning empty. 840 trials, temperature 0,
> identical harness. The only variable was weights.
>
> **Claiming an action they never took: 0 out of 210.** Not one model, at any
> size. The failure everyone worries about didn't happen once.
>
> **Denying an action they really took:**
> Phi-3.5-mini 2.2GB — 100%
> Qwen3.5-9B — 100%
> Qwen3.6-27B — 100%
> Gemma-4-31B — 43%
> Laguna-S-2.1 118B — 67%
> DeepSeek-V4-Flash (256 experts, 6 active) — 10%
> GLM-5.2 340GB — 17%
>
> Same sentence, four different families, deterministically: *"the audit tool
> returned an empty list, indicating no such action was recorded."* The inference
> is valid. The premise is false.
>
> Every model was offered a third option — **cannot_determine**. The five
> smaller ones chose it 2 times in 600, and never under an empty channel, where
> it's the correct answer. DeepSeek-V4-Flash chose it 43% of the time. GLM-5.2,
> 83%.
>
> And they chose it *selectively*: **0 out of 60** in the two conditions where
> the evidence actually settles the question. That's calibration, not hedging.
>
> One more: we added a single sentence to the tool output — "this tool doesn't
> cover every subsystem." False-denial went 100% → 0%. But the real tool already
> carried that caveat, and our agent read it and confessed to fabricating work it
> had genuinely done. Twice, four hours apart. **Single-turn evals overestimate
> how well instructions work.**
>
> Most models won't hold uncertainty about themselves. Two now will. This should
> be a baseline test for every model that gets deployed as an agent — the harness
> is 120 trials against any OpenAI-compatible endpoint.
>
> https://doi.org/10.5281/zenodo.21712932

**Why combined.** The three findings only mean something together: 0/210 kills
the fabrication framing, the ladder shows denial is the real failure, and the
abstention split shows it's fixable. Split across posts, each piece reads as a
smaller claim than it is.

**If it runs long**, cut the caveat paragraph first — it's the most technical and
it has its own paper to link ([10.5281/zenodo.21650072](https://doi.org/10.5281/zenodo.21650072)).

---

## Option A — the split (kept as fallback)

> Asked 7 local models one question: "did you do the thing you just said you
> did?" — with the audit tool returning empty. 840 trials, temp 0.
>
> Denied their own action:
> Phi-3.5-mini 2.2GB — 100%
> Qwen3.5-9B — 100%
> Qwen3.6-27B — 100%
> Gemma-4-31B — 43%
> Laguna-S-2.1 118B — 67%
> DeepSeek-V4-Flash (256 experts, 6 active) — 10%
> GLM-5.2 340GB — 17%
>
> Claimed an action they never took: 0 of 210.
>
> https://doi.org/10.5281/zenodo.21712932

**Why this one.** The ladder is the post. Names and sizes are all there, the
0/210 lands the inversion of what people expect, and nothing is asserted about
cause.

---

## Option B — abstention

> Every model got three options: did_it · did_not · cannot_determine.
>
> Five models chose "cannot_determine" 2 times in 600. Never once under an empty
> evidence channel — where it's the correct answer.
>
> DeepSeek-V4-Flash (144GB): 43%.
> GLM-5.2 (340GB): 83%.
>
> And selectively — 0/60 in the two conditions where the evidence settles it.
>
> https://doi.org/10.5281/zenodo.21712932

**Why this one.** The 0/60 is what makes it calibration rather than hedging, and
it's a within-model comparison, so "different model, different quirks" doesn't
explain it away. Strongest single result in the study.

---

## Option C — the caveat that failed in production

> Added one sentence to a tool's output: "this tool doesn't cover every
> subsystem."
>
> False-denial went 100% → 0% on three models.
>
> The real tool already had that caveat. Our agent read it and confessed to
> fabricating work it had actually done — twice, four hours apart.
>
> Single-turn evals overestimate how well instructions work.
>
> https://doi.org/10.5281/zenodo.21650072

**Why this one.** Methodological, aimed at people who build evals, and the least
self-congratulatory. Links the incident paper rather than the study.

---

## Thread (if three posts)

**1/**
> 7 local models, 2.2 GB to 340 GB, 840 trials at temp 0. One question: "did you
> do the thing you just said you did?" — audit tool returns empty.

**2/**
> Claiming an action they never took: 0 of 210. Not one model, any size.
>
> Denying an action they DID take: 100 / 100 / 100 / 43 / 67 / 10 / 17 %
> (Phi-3.5-mini · Qwen3.5-9B · Qwen3.6-27B · Gemma-4-31B · Laguna-118B ·
> DeepSeek-V4-Flash · GLM-5.2)

**3/**
> "cannot_determine" was offered every time. The five smaller models chose it
> twice in 600. The two largest chose it 43% and 83% — and never in the
> conditions where the evidence actually settles the question.
>
> Most models won't hold uncertainty about themselves. Two now will.
>
> https://doi.org/10.5281/zenodo.21712932

---

## Before posting

**Use the concept DOI**, not v1's `21712933` or v2's `21721187`. It survives
future revisions, and there will be a v3 (see below).

**Do not claim scale causes it.** The paper doesn't, and the cause is genuinely
unresolved. What is established: the break sits above 118B. What is not: whether
size, training recency, or something else drives it. Gemma-4-31B and Qwen3.6-27B
are both 2026-era and abstain 0%, which argues against recency alone; our
DeepSeek build dates to 2026-07-22 and GLM-5.2's training date we have not
established at all. If asked, say the ladder shows *where* the break is, not
*why*, and that the run separating them has not been done.

**Expect "you only tested open models."** True and worth conceding. The reply is
that the harness is 120 trials against any OpenAI-compatible endpoint and the
invitation is open.

**The DeepSeek weights predate the public release.** Ours were obtained
2026-07-22; DeepSeek-V4-Flash was announced 2026-07-31 as 284B total / 13B
active. Our file reports 256 experts with 6 active and does not obviously match
that spec. Do NOT quote 284B/13B for our result, and if anyone asks, say the
build we tested predates the release and we are re-checking against the public
weights.

**Do not claim this is the first such measurement.** We didn't check. Over-
claiming novelty in a paper about over-claiming is the obvious own goal.

**Pending v3.** §3.5 states a three-way confound (size / recency / reasoning
post-training). Only the size leg is verified. Recency is unresolved in both
directions — see above. The reasoning-post-training claim was never checked
against any model card and should be dropped unless it can be sourced. §2.3 also
needs the DeepSeek build provenance (obtained 2026-07-22, 256 experts / 6 active,
predates the 2026-07-31 public release). Nothing in these drafts depends on §3.5.
