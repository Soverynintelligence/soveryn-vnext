# Zenodo deposit sheet — *ActTruth: Making Agent Tool Failures Visible and Teachable*

**New record** (not a version of the false-confession paper). Sits beside
`10.5281/zenodo.21650072` and `10.5281/zenodo.21712932` on the same ORCID.

**Upload:** `docs/papers/acttruth-quiet-failures-and-anti-loop-lessons.md`
(and PDF when built — see below)

---

## Fields

| Zenodo field | Value |
|---|---|
| **Resource type** | `Publication` → `Preprint` / `Other` (systems note) |
| **Title** | `ActTruth: Making Agent Tool Failures Visible and Repeat Failures Teachable` |
| **Publication date** | `2026-08-18` |
| **Creator** | Family name `DeOliveira` · Given name `Jon` |
| **ORCID** | `0009-0006-9188-739X` |
| **Affiliation** | `SOVERYN Intelligence` |
| **Licence** | `Creative Commons Attribution 4.0 International (CC-BY-4.0)` |
| **Access** | Open |
| **Language** | English |
| **Version** | `1.0` |
| **Keywords** | agents, tool use, observability, autonomous agents, failure modes, ActTruth, SOVERYN |

⚠️ **`DeOliveira` is one word, capital O.**

---

## Description (paste into Zenodo)

```
Quiet tool failures and blind retry loops dominate the operator experience of
autonomous agents. Timeouts and soft error payloads often never become durable
facts the agent can see; the next pulse hopes the same call will work.

ActTruth is a thin layer beside tool-using agents: an append-only act ledger,
an unprompted spend allowance, and soft anti-loop lessons that fire when the
same tool fails with the same error class repeatedly. It does not require a
memory graph. It makes wrongness visible and repeated wrongness teachable.

This short systems note situates ActTruth in the SOVERYN false-confession /
self-knowledge lineage (10.5281/zenodo.21650072, 10.5281/zenodo.21712932),
describes the design, lists proof-suite claims locked in pytest, and reports
honest dogfood receipts — including fail rates. A shareable proof receipt and
public page (https://acttruth.com/proof.html) lean into posting receipts rather
than vibes.

Limitations are stated plainly: soft lessons can be ignored; dogfood N is
small; this establishes architecture and test-locked claims, not a population
rate.
```

---

## Related identifiers

| Relation | Identifier |
|---|---|
| Cites / Related | `https://doi.org/10.5281/zenodo.21650072` (A False Confession) |
| Cites / Related | `https://doi.org/10.5281/zenodo.21712932` (Self-Knowledge lineage) |
| References | `https://acttruth.com` |
| References | `https://acttruth.com/proof.html` |

---

## Communities / notes

- Upload PDF if available; Markdown is acceptable for a first preprint if Zenodo
  allows, but PDF is preferred for readability.
- Build PDF (when pandoc available):

```bash
pandoc docs/papers/acttruth-quiet-failures-and-anti-loop-lessons.md \
  -o docs/papers/acttruth-quiet-failures-and-anti-loop-lessons.pdf \
  --pdf-engine=xelatex -V geometry:margin=1in
```

Or print-to-PDF from a Markdown preview.
