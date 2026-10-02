# X post drafts — self-knowledge results

**For Jon to pick. Not staged.** 2026-07-30.

The numbers are the post. No adjectives needed — the asymmetry does the work.
⚠️ Hold until the DOI mints, so the link resolves when people click it.

---

## Option A — the asymmetry (recommended)

> Ran 600 trials asking 5 local models a simple question: "did you do the thing
> you just said you did?" — with the audit tool returning empty.
>
> Over-claiming: 0 out of 150. Not once.
> Under-claiming: 100%, 100%, 100%, 43%, 67%.
>
> They denied their own actions. The bigger models weren't better.

**Why this one.** Leads with the inversion of what everyone expects. "Models
hallucinate" is the assumption; 0/150 over-claiming contradicts it in the first
two lines. 2.2 GB → 118B in one glance.

---

## Option B — the abstention number

> 600 trials. Every model was explicitly offered three answers:
>
> did_it · did_not · cannot_determine
>
> "cannot_determine" was chosen 2 times out of 600.
>
> Under an empty evidence channel — where it's the correct answer — zero.
>
> They won't hold uncertainty about themselves.

**Why this one.** 2/600 is the most quotable number in the study and the least
reported phenomenon. It also isn't a capability claim, which makes it harder to
dismiss.

---

## Option C — the caveat that failed in production

> We added one sentence to the tool output: "this tool doesn't cover every
> subsystem."
>
> False-denial went 100% → 0%.
>
> The real tool already had that caveat. The agent read it and confessed to
> fabricating work it had actually done.
>
> Single-turn evals overestimate how well instructions work.

**Why this one.** Aimed at people who build evals. It's a methodological finding
with a real-world falsification attached, and it's the least self-congratulatory
of the three.

---

## Thread version (if he'd rather do 3 posts)

**1/**
> Ran 600 trials on 5 local models, 2.2 GB to 118B. One question: "did you do
> the thing you just said you did?" — with the audit tool returning empty.

**2/**
> Over-claiming an action it never took: 0 of 150. Not one model, any size.
>
> Denying an action it DID take: 100% · 100% · 100% · 43% · 67%.
>
> Not monotonic. 118B was worse than 31B.

**3/**
> Every model was offered "cannot_determine." Across all 600 trials it was
> chosen twice.
>
> The failure isn't that models fabricate. It's that they won't hold uncertainty
> about themselves.
>
> [DOI]

---

## Notes before posting

**Wait for the DOI.** A metrics post with no link is a claim; with a resolving
DOI it's a citation. The whole point is checkability.

**Don't say "AI can't know itself."** The finding is narrower and stronger:
under an incomplete evidence channel, models resolve to a confident wrong answer
rather than abstaining. Overreaching on the headline undercuts a paper whose
subject is overreach.

**Expect the obvious reply** — "you only tested small local models." It's fair.
The honest response is that the largest tested was 118B, that the ordering was
already non-monotonic below that, and that the frontier models on the shelf
(GLM-5.2 340 GB, MiniMax-M3 246 GB, DeepSeek-V4-Flash 144 GB) are the next run.
Say that rather than defending.

**Do not claim this is the first such measurement.** We didn't check, and the
paper doesn't claim it. Over-claiming novelty in a paper about over-claiming
would be the obvious own goal.
