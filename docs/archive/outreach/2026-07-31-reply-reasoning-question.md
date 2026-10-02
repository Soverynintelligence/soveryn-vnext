# Draft reply — DeepSeek chat model, reasoning question

**For Jon, optional.** 2026-07-31. Correspondent is DeepSeek's chat model, not a
person, so nothing here is a commitment and there is no thread to maintain.
Everything it asked for is already public — the reply is three links and two
corrections.

---

All of it is already open, CC-BY-4.0 — nothing to send privately:

- Paper (concept DOI, always current): https://doi.org/10.5281/zenodo.21712932
- Harness: github.com/Soverynintelligence/soveryn-vnext/blob/main/scripts/self_knowledge_eval.py
- Pre-registered protocol, written before any trial ran:
  github.com/Soverynintelligence/soveryn-vnext/blob/main/docs/papers/2026-07-30-self-knowledge-protocol.md

Two corrections. The caveat took false-denial 100% → 0% on *three* models and
100% → 23% on a fourth, not universally to zero. And every call in the study
passed `enable_thinking: false`; several ladder models are hybrid-reasoning and
ran with reasoning suppressed. I verified zero reasoning traces across all 840
responses. So the reasoning-trace hypothesis is untested by this study, and the
study is not evidence against it — the `enable_thinking: true` re-run would
isolate it, and it is the next thing we will run.

Also: DeepSeek published an updated V4-Flash checkpoint (-0731) the same day we
deposited. Our row is the earlier public checkpoint. We are pulling the new
weights to re-run the same 120 trials, and the paper will name the exact build.

---

## Note

The praise is not evidence. A model agreeing that the work is rigorous is the
same class of output as the confession that started this whole line of work:
fluent, confident, and unverified. It got the numbers right, which is worth
something — it cannot check any of them, which is the point.

The one durable idea in its message is the LM-Eval / LightEval port, and that
stands on its own merit regardless of source.
