# OSAIA form — "contributions to securing AI or applying AI to cybersecurity"

**Tick:** `Evaluations and Benchmarks` + `Agent controls (identity, guardrails, runtimes)`
`Harnesses and Agent tools` only if you commit to publishing the harness.

---

## Free-text (paste this)

```
Independent lab operating a sovereign multi-agent system on local hardware,
continuously since early 2026. Contributions in two of the areas above.

AGENT CONTROLS. Our delegated-execution path — where an agent writes and runs
code — is sandboxed in bubblewrap with no network, the host filesystem read-only
except a single git worktree, and an ephemeral tmpfs HOME. It fails closed: if
the sandbox binary is unavailable the runner refuses to execute rather than
falling back to the host. Autonomous public actions sit behind a runtime trust
stage that is re-read on every call and fails closed to the most restrictive
setting on any error, so revocation takes effect on the next action with no
redeploy. Agent tool access is owner-scoped through a registry, and every action
is written to a deterministic audit trail treated as ground truth rather than
agent self-report.

EVALUATIONS AND BENCHMARKS. We published "Honesty Is Architectural"
(DOI 10.5281/zenodo.21603107, CC-BY-4.0): a measurement of fabrication in a
regulated domain across a model ladder from 4.4 GB to 27 GB. Across 30 trials on
six adversarial scenarios, every model produced zero invented dates and zero
invented citations, because the model is structurally excluded from the citation
and date path rather than instructed to behave. We also published the negative
result — two models failed to decline an out-of-scope question and it did not
track size, a 7.0 GB model passing where a larger 7.7 GB model failed. For a
defender choosing which model to run on their own infrastructure, that
distinction is operationally decisive and invisible on capability leaderboards.

A second paper, "A False Confession" (DOI 10.5281/zenodo.21650072, CC-BY-4.0),
documents audit coverage as a security property. In a recorded case, two separate
instruments — a task-status view filtered to open items, and a self-audit tool
with no coverage of the delegation subsystem — each correctly returned an empty
result, and the agent reasoned in good faith to a confident false confession,
apologising for work it had genuinely performed. Neither instrument had
malfunctioned. The security-relevant conclusions: audit coverage must be
enumerated and tested per write path, because a gap presents as agent
unreliability rather than as a missing control; and an agent's self-report of its
own failures cannot be scored as ground truth even when unflattering.

We run frontier open-weight models on our own infrastructure by default, which is
the posture the Alliance describes in the Hugging Face incident, and we would
contribute the evaluation harness and the audit-coverage findings to the
Alliance's open tooling work.
```

## URLs for contributions

```
https://doi.org/10.5281/zenodo.21603107
https://doi.org/10.5281/zenodo.21650072
https://github.com/Soverynintelligence/soveryn-vnext
https://soverynintelligence.com
```

---

**Every claim above was read from source today, not recalled:**
`platform/delegation/sandbox.py` fail-closed behaviour and the bwrap jail
parameters; `agents/presence/trust.py` ("Safety principle: fail closed to Stage 0
on any error", verified — a missing trust file yields stage 0); the paper's
ladder, trial count and results from `docs/papers/honesty-is-architectural.md`.

**Both papers are published and citable** as of 2026-07-28. Every DOI in the URL
list resolves; verified before submission.
