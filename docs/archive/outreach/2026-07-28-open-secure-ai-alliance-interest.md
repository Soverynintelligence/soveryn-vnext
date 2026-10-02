# Open Secure AI Alliance — expression of interest

**Draft for Jon's review. Not sent.**
Prepared 2026-07-28. Every number below verified against the published paper
(`docs/papers/honesty-is-architectural.md`), not quoted from memory.

---

**From:** Jon DeOliveira, SOVERYN Intelligence LLC
**Email:** jdeoliveira@soverynintelligence.com
**Web:** soverynintelligence.com
**Code:** github.com/Soverynintelligence/soveryn-vnext
**ORCID:** 0009-0006-9188-739X

---

Subject: **Expression of interest — open evaluation tooling for agent honesty and grounding**

I'd like to put SOVERYN Intelligence forward as a participant in the Open Secure
AI Alliance, specifically against the call for "shared open infrastructure for AI
defense — datasets, evaluation frameworks, attack simulators and red-teaming
tools."

We're a small independent lab. What we bring isn't scale — it's a working,
published, reproducible answer to one narrow question the Alliance's framing
puts at the centre: **how do you know an agent isn't fabricating?**

**Published measurement.** *Honesty Is Architectural: Measuring fabrication in a
regulated domain, across a 6× model-size range* (14 July 2026,
DOI [10.5281/zenodo.21603107](https://doi.org/10.5281/zenodo.21603107), CC-BY-4.0).
We built an FCC broadcast-compliance system in which fabrication is prevented **by
construction** rather than by prompting, then measured whether that holds across a
model ladder from 4.4 GB to 27 GB. Across 30 trials on six adversarial scenarios,
every model produced **zero invented dates and zero invented citations** — the
4.4 GB model as reliably as the 27 GB one.

The negative result is the more useful half, and we published it: two models
failed to decline an out-of-scope question, and **it did not track size** — a
7.0 GB model passed where a *larger* 7.7 GB model failed. So factual grounding is
architectural and essentially free at any scale, while **boundary discipline is
empirical and has to be measured per model.** For a defender selecting a local
model, that distinction is operationally decisive and it isn't visible on any
capability leaderboard.

**Operating stack, not a proposal.** We run a sovereign multi-agent system 24/7 on
modest local compute — a conversational agent, a bounded code executor, and a
host-sentinel security daemon — with a deterministic audit trail treated as ground
truth rather than self-report. The design principle matches the Alliance's own:
safety lives in the full agent stack (identity, permissions, harnesses, guardrails,
logs, evaluation), not in whether the weights are open.

**Why the Hugging Face incident resonates here.** The Alliance's write-up notes
that closed tooling could not distinguish attacker from defender, and that
forensic analysis proceeded by running an open-weight frontier model on
Hugging Face's own infrastructure. That is the deployment posture we build for by
default, and we hold and run that class of model locally today.

**What we'd contribute:**

1. **The fabrication-measurement harness** — the adversarial scenario set, scoring
   method and model-ladder protocol behind the published results, released openly
   so others can run it against their own stacks.
2. **A grounding pattern that is code, not prompting** — facts exposed as
   deterministic tools an agent must call, with the model structurally excluded
   from the citation and date path. This is what produced the zero-fabrication
   result and it transfers across model families.
3. **Field findings on agent audit design.** Running this stack surfaced a
   recurring defect class we think matters for anyone building agent logging:
   *write paths without corresponding read paths.* An agent took real,
   logged actions that no audit surface exposed — and in one recorded case
   reasoned in good faith from incomplete evidence to a **false confession**,
   apologising for fabricating work it had genuinely performed. The literature is
   thick with over-claiming; this is the same blind spot from the other side, and
   it argues that an agent's audit tooling has to be evaluated for coverage, not
   just existence.

We'd be glad to contribute the evaluation harness and the audit-coverage findings
to the Alliance's open tooling work, and to participate in whatever review process
is appropriate for a lab of our size.

Jon DeOliveira
SOVERYN Intelligence LLC

---

## Notes before sending

- **Submission route unknown.** The announcement links "Learn more or share
  interest in joining" — get that URL or contact address from the NVIDIA page
  before sending anything.
- **Claim 3 is unpublished.** The false-confession case is fully evidenced
  (timestamps, DB rows, the commit that fixed it) but is not yet written up. If
  it draws interest, it needs a short public write-up to be citable — otherwise
  it's an assertion.
- **The harness is not packaged.** Offering to release it means committing to
  clean it up for third-party use. Worth confirming that's a commitment you want
  before it's in writing.
- Deliberately does not claim security expertise we don't have. The contribution
  offered is honesty/grounding evaluation, which is genuinely ours.
