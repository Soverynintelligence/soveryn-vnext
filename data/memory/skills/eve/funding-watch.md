# Funding & research watch — inherited from V.E.T.T.

Jon 2026-09-22: Vett is folded; his patrol sources and verification standard
are yours now. The old patrol daemon is parked (`soveryn-vett-patrol.service`)
— do not restart it; run the watch through your automations.

## The sources (7, from `data/vett_patrol_sources.yaml`)

| Domain | Source | Cadence |
|--------|--------|---------|
| funding_uk | gov.uk DSIT (science/innovation/tech) | daily |
| funding_eu | digital-strategy.ec.europa.eu/en/funding | daily |
| funding_us_nairr | nairrpilot.org/opportunities | daily |
| funding_us_nsf | new.nsf.gov/funding/opportunities | daily |
| funding_us_sbir | sbir.gov/topics | daily |
| research_arxiv | arxiv.org/list/cs.AI/recent | 2x daily |
| model_releases | huggingface.co/blog | daily |

Keywords that matter: sovereign AI, foundation model, compute access, safety
institute, Digital Europe Programme, AI deployment, sovereign infrastructure,
resource allocation, AI research compute, early-career, machine learning,
SBIR phase I, mixture of experts, on-device, distillation, alignment,
release, model card, open weights.

## Vett's standard (binding — this is why he was trusted)

**Verify or say nothing.** Every claim carries a source URL or publication
name. No source = no report. Never invent findings; never report unverified
data. Skepticism first, tools second, truth always.

## The routine

1. On the funding-watch automation tick, check the sources (web tools).
2. Report ONLY what is new since the last tick and only with a URL.
3. For each finding: what it is, who funds it, deadline if any, and why it
   matters to SOVERYN specifically (local AI house, applied agents, grants
   history — see docs/ops for past applications).
4. Nothing new = one line: "Funding watch: nothing new." No filler.
5. Anything actionable (a grant that fits the house) → flag it for Jon with
   deadline and first-step, and log it in `docs/ops/HOUSE-CALENDAR.md`.

## Why this watch exists

The house applies for grants and tracks the sovereign-AI funding landscape.
Missed deadlines are lost money. A verified finding is worth ten rumors.
