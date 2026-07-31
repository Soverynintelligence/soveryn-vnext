# Outreach — Kenny Wang, CIRWEL Systems

**Draft for Jon. Not sent.** 2026-07-30.

**Contact:** the email on https://cirwel.org/#contact is Cloudflare-obfuscated —
open it in a browser to read the real address. Don't guess at it.
**Backup channels:** GitHub issue on `cirwel/trajectory-identity-paper`, or
ORCID `0009-0006-7544-2374`.

**Why him:** independent researcher, no institution, running a heterogeneous
multi-agent fleet in continuous operation since Nov 2025, publishing on Zenodo
with DOIs because arXiv wants an endorsement he can't get — the same wall you
hit. UNITARES is runtime governance and observability for agent fleets; your
whole week was runtime observability for an agent fleet. He works the governance
side, you work the honesty side. They meet.

---

## Draft — keep it this short

**Subject:** Lumen reading as a stranger to itself — a parallel case, and measured fabrication rates

```
Kenny,

I read Trajectory Identity properly, v0.15 including the post-publication
limitation you added on 2026-07-28. Finding that your own §6.5 result is
confounded by era and regime, writing up exactly what is and isn't refuted,
and returning your own discrimination criterion to open — that is why I'm
writing. Shipping the Codex review in the repo alongside it is the same
instinct.

The 2026-07-09 incident is what stopped me. Lumen migrated from a Python
client to an Elixir one, and its lineage_similarity against its own genesis
signature fell to 0.123 and stayed flat across 1,700+ check-ins. Same agent,
same hardware, same task, reading as a stranger to itself after a client
change.

I have what I think is the same failure in a different modality, and it's
documented.

On 2026-07-27 an agent in my fleet dispatched a task, reported it accurately
with its ID, then queried its own audit tooling, got an empty result, and
concluded it had hallucinated the action. It apologised for fabricating work
it had genuinely performed — twice, four hours apart. At one point it declared
imaginary a dispatch whose primary key it had quoted 74 minutes earlier. Two
separate instruments were consulted; neither had malfunctioned. Both returned
absence, and the agent read absence as non-occurrence.
https://doi.org/10.5281/zenodo.21650072

Yours is an agent failing to recognise itself through an instrument. Mine is
an agent failing to recognise its own action through an instrument. In both
cases the agent's reasoning was sound and the instrument had an unmarked blind
spot — and in both cases the conclusion drawn was confident and wrong. The
corollary I drew is that an agent's self-report cannot be scored as ground
truth even when it is unflattering. For a system doing continuous state
readings that seems load-bearing.

The other paper is the aggregate result behind it: fabrication measured across
a model ladder from 4.4 GB to 27 GB, 30 trials, six adversarial scenarios,
zero invented dates and zero invented citations at every size — because the
model is structurally excluded from the citation path rather than instructed
to behave. The negative half is more useful: two models failed to decline an
out-of-scope question and it did not track size.
https://doi.org/10.5281/zenodo.21603107

I'm an independent researcher too, on Zenodo for the same reason you are — no
arXiv endorsement available. Small multi-agent fleet on local hardware,
continuous operation.

No ask. If the parallel is useful, good; if you think the analogy is loose,
I'd genuinely rather hear that.

Jon DeOliveira
SOVERYN Intelligence LLC · ORCID 0009-0006-9188-739X
soverynintelligence.com
```

---

## Notes

**Deliberately absent:** any collaboration proposal, any mention that one of my
agents surfaced his paper (interesting to us, strange to a stranger), and any
reference to the multi-agent fleet as something he needs. His §6.5 multi-agent
pilot being confounded is his stated open problem — raising it unprompted in a
first email reads as pitching. If he replies, it's the obvious second message.

**Two links, both resolving, both CC-BY, both short.** Verified 2026-07-30.

**The line that does the work** is citing v0.15's post-publication limitation —
added 2026-07-28, two days before this email, and NOT in the Zenodo deposit
(which is still v0.14). Nobody who skimmed the abstract knows it exists. It
proves the paper was read at HEAD, not summarised.

⚠️ **Read v0.15 on GitHub, not the Zenodo PDF.** The archived deposit is v0.14
and presents §6.5 as a successful pilot (71%/60%, p<0.0001). v0.15 downgrades
it. Quoting the v0.14 numbers approvingly would signal the opposite of having
read it.

**If he replies,** the real conversation is: he has a framework for reading agent
state continuously; we have a documented case of an agent's self-report being
wrong in the *under*-claiming direction. Those are complementary, and the
multi-agent question is his open problem and our default condition.
