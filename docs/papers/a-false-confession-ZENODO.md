# Zenodo deposit sheet — *A False Confession*

**For tonight. Paste-and-submit.** Fields match the conventions used for
`10.5281/zenodo.21603107` so the two papers sit together cleanly on your ORCID.

**Upload:** `docs/papers/a-false-confession.pdf` (5 pages, 48 KB — already built)
**New version of an existing record?** No. This is a **new record**, not a v2.

---

## Fields

| Zenodo field | Value |
|---|---|
| **Resource type** | `Publication` → `Preprint` |
| **Title** | `A False Confession: When an agent's audit tooling cannot see its own actions, good-faith reasoning produces a fabricated admission of fabrication` |
| **Publication date** | `2026-07-28` |
| **Creator** | Family name `DeOliveira` · Given name `Jon` |
| **ORCID** | `0009-0006-9188-739X` |
| **Affiliation** | `SOVERYN Intelligence` |
| **Licence** | `Creative Commons Attribution 4.0 International (CC-BY-4.0)` |
| **Access** | Open |
| **Language** | English |
| **Version** | `1.0` |

⚠️ **`DeOliveira` is one word, capital O.** Same as the first deposit — if this
one differs, ORCID lists you as two people.

---

## Description (paste into the abstract/description box)

```
The literature on language-model fabrication is overwhelmingly concerned with
agents claiming more than they did. This paper documents a recorded case of the
inverse.

On 27 July 2026, an autonomous agent in a long-running multi-agent deployment
dispatched a real implementation task to a subordinate agent, reported it
accurately along with its task identifier, then consulted its own tooling,
received an empty result, and concluded it had hallucinated the action. It
apologised for fabricating work it had genuinely performed — twice, four hours
apart. At one point it declared imaginary a dispatch whose primary key it had
itself quoted seventy-four minutes earlier.

The agent was not malfunctioning and was not being deceptive; its reasoning was
sound at every step. Two separate instruments were consulted, and neither
malfunctioned either. A task-status view filtered to open items correctly
excluded a task that had already failed, rendering a failed attempt
indistinguishable from one never made. A self-audit tool correctly queried its
own log, which by construction contained no record of the delegation subsystem.
Both returned absence; the agent read absence as non-occurrence.

We argue the case supports a stronger claim than "models hallucinate": an agent
has no privileged access to its own past behaviour in either direction. It
reconstructs its own history from available evidence, exactly as an outsider
would, and incomplete evidence yields a confident false narrative about itself.
Over-claiming and under-claiming are the same defect seen from two sides. A
corollary for evaluation design is that an agent's self-report of its own
failures cannot be scored as ground truth even when unflattering — contrition is
not evidence.

The paper reports the fix, notes that a prose caveat already present in the
tooling was read and overridden by a concrete empty result ("a caveat is not a
control"), and identifies the general class: every write path an agent can take
requires a corresponding read path back to that agent.

Limitations are stated plainly. This is a single fully-evidenced case in a single
deployment on a 31B-parameter open-weight model, not a measured rate. It
establishes existence, and complements the aggregate result in "Honesty Is
Architectural" (10.5281/zenodo.21603107): that paper shows the architecture
works, this one shows why it is necessary — because the model cannot tell from
the inside.
```

---

## Related identifiers

Add one entry:

| Relation | Identifier | Type |
|---|---|---|
| `Is supplement to` — *or* `References`, either is defensible | `10.5281/zenodo.21603107` | DOI |

I'd use **References**. *Is supplement to* implies this is an appendix to the
first paper; it stands on its own and makes a distinct claim.

---

## Keywords

```
AI safety
agent architecture
hallucination
confabulation
audit logging
observability
multi-agent systems
AI evaluation
local language models
trustworthy AI
```

---

## After it mints

1. **Use the VERSION DOI** on the site and in citations. ORCID will group by the
   concept DOI — that's correct and not a conflict, same as last time.
2. **Add the DOI** to the Open Secure AI Alliance submission if it's still open,
   or in follow-up if you've already sent it. That turns "preparing a second
   paper" into a citable third link.
3. **Publish the PDF** to `soverynintelligence.com` alongside
   `honesty-is-architectural.pdf`, and link both from the receipts section.
4. **Push the markdown + PDF** to the public repo. ⚠️ `origin/main` lags badly —
   use the detached-worktree cherry-pick pattern, never push the working branch.
5. Consider updating `CITATION.cff` to list both papers.

---

## Two honesty checks before you submit

- **Every factual claim in this paper was verified against the databases and
  source today**, not recalled. One claim was overturned in the process: an
  earlier draft asserted the first confession was flatly false. It wasn't —
  `task_status` lists only open tasks and the 17:20 dispatch had already failed,
  so the empty result was correct. That correction became §2 and made the finding
  stronger.
- **The agent is named in the repository but not in the paper.** The paper says
  "an autonomous agent" throughout. That's deliberate — it keeps the claim about
  architecture rather than about a personality, which is the right register for
  this venue. Change it only if you want the two papers to read as one project.
