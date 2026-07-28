# Open Secure AI Alliance — form fill sheet

**Form:** https://www.nvidia.com/en-us/open-secure-ai-alliance-contact-us/
**Status:** prepared 2026-07-28, NOT submitted. Jon submits.

Copy-paste values below. Everything is verified — the paper numbers come from
`docs/papers/honesty-is-architectural.md`, not from recall.

---

## Required

| Field | Value |
|---|---|
| First Name | `Jon` |
| Last Name | `DeOliveira` |
| Business Email Address | `jdeoliveira@soverynintelligence.com` |
| Organization / University Name | `SOVERYN Intelligence LLC` |
| Industry | `Other` — see note below |
| Job Title | `Founder & Principal Researcher` |
| Location | `United States` |
| How can we help? | `I'd like to inquire about joining the Open Secure AI Alliance` |
| Agreement checkbox | ✔ |

**Industry note.** There's no "AI research" option. `Other` is the honest answer
for SOVERYN itself. `Telecommunications` is defensible if you'd rather anchor to
Shepherd's FCC broadcast-compliance work, since that's the domain the published
measurements were taken in — it makes the paper land as applied rather than
academic. Your call; I'd take `Other` and let the free text do the work.

## Optional — fill these, they're where the case gets made

**GitHub Profile or Organization URL**
```
https://github.com/Soverynintelligence
```

**Company Size**
```
1-10
```

**Current community contributions** (select all that apply)
```
☑ Evaluations and Benchmarks     ← the primary fit
☑ Harnesses and Agent tools
☑ Agent controls
```

**Please describe your current community contributions**
```
Independent lab working on measurable honesty in agent systems — preventing
fabrication by architecture rather than by prompting.

Published, DOI'd, CC-BY: "Honesty Is Architectural" (14 July 2026,
10.5281/zenodo.21603107). We built a compliance system in which fabrication is
prevented by construction — the model is structurally excluded from the citation
and date path — and measured whether it holds across a model ladder from 4.4 GB
to 27 GB. Across 30 trials on six adversarial scenarios, every model produced
zero invented dates and zero invented citations; the 4.4 GB model was as reliable
as the 27 GB one.

We also published the negative result: two models failed to decline an
out-of-scope question, and it did not track size — a 7.0 GB model passed where a
larger 7.7 GB model failed. Factual grounding is architectural and near-free at
any scale; boundary discipline is empirical and must be measured per model. For a
defender choosing a model to run on their own infrastructure, that distinction is
operationally decisive and invisible on capability leaderboards.

We run a sovereign multi-agent stack on local hardware 24/7 — conversational
agent, sandboxed code executor, host-sentinel daemon — with a deterministic audit
trail treated as ground truth rather than agent self-report. This matches the
Alliance's framing that safety lives in the full agent stack (identity,
permissions, harnesses, guardrails, logs, evaluation) rather than in whether
weights are open. We hold and run frontier open-weight models locally, which is
the same posture that let Hugging Face conduct its own forensic analysis.

Offering to contribute: (1) the fabrication-measurement harness — adversarial
scenario set, scoring method and model-ladder protocol behind the published
results, released openly; (2) the deterministic tool-grounding pattern that
produced the zero-fabrication result, which transfers across model families;
(3) field findings on audit coverage in long-running agent systems, including a
recorded case of an agent reasoning in good faith from incomplete audit data to a
false confession — apologising for fabricating work it had genuinely performed.
Over-claiming is well documented; this is the same blind spot inverted, and it
argues audit tooling must be evaluated for coverage, not merely existence.
```

**URLs for contributions**
```
https://doi.org/10.5281/zenodo.21603107
https://github.com/Soverynintelligence/soveryn-vnext
https://soverynintelligence.com
```

**Upload Logo** — the copper/sage interlocking **S** mark, .SVG or .PNG.
Members are listed with logos; supply one.

**Newsletter opt-in** — your call.

---

## Before you hit submit

1. **The harness offer is a commitment.** Point (1) means packaging the scenario
   set and scoring for third-party use. It's real work. Say it only if you'll do it.
2. **Point (3) is unpublished.** Fully evidenced — timestamps, DB rows, the fix
   commit — but not written up. If anyone asks, it needs to be citable within
   days, not months. Worth drafting the write-up before or right after submitting.
3. **Have the logo file ready** before you open the form; some of these clear on
   navigation.
