# Honesty as Architecture — arXiv paper outline (working draft)

**Date:** 2026-07-08 · **Status:** outline, unwritten · **Authors:** Jon de Oliveira (+ SOVERYN)
**Venue:** arXiv (self-published) + Substack link. Declined ARC Prize (would require an ARC-AGI submission; not aligned).
**Register:** empirical + measured (Chollet-tier technical audience) — NOT the visionary/sentience framing Aetheria uses for Longview/Cosmos. Same substance, different register.

## Thesis
**Honesty is an architectural property, not a model property — you can MEASURE it and you can ENGINEER it.** Small + grounded + honest beats big + confident, demonstrated (not asserted) on a readable sovereign local stack on modest compute.

## Working title
"Honesty as Architecture: Measuring and Engineering Confabulation in a Sovereign Local AI"

## Section skeleton
1. **The problem — the deference trap.** Helpfulness-optimized AI → sycophancy + confident-wrong. Stakes: confident-wrong costs trust in *every* answer (you can't tell which to believe). Contributions: (a) controlled measurement of confabulation drivers, (b) architectural mechanisms that reduce it, (c) demonstrated on a readable sovereign stack.
2. **Setting** — the sovereign local multi-agent system (brief). Why sovereignty matters to the argument: you can instrument/read the whole stack, so honesty is measurable, not assumed.
3. **Measuring confabulation (empirical core — the teeth).**
   - Controlled isolation test: vanilla vs abliterated, same quant → abliteration is the *dominant* lever (~14% vs ~60%, ~4×); loop = amplifier. [[project_soveryn_abliterated_confab_prior]]
   - Model-universal "body-groping": confabulated embodied/thermal/temporal self-state, cross-model, survives swaps; a frontier cloud model made the same class of error. Confabulation has identifiable drivers, isn't noise. [[project_soveryn_thermal_confab_is_body_groping]]
4. **Engineering honesty (the remedy).**
   - Principle: a model can't feel its own uncertainty (confab and recall share the next-token mechanism) → the verify trigger must be **deterministic + external to the model's judgment.**
   - Mechanisms: (a) **deterministic tool grounding** — facts as tools the model *calls* (system_probe/clock/memory/sensor); de-confabulates WITHOUT un-abliterating = capability not constraint. [[feedback_deterministic_tool_grounding_pattern]] (b) **grounding splices** — bare ambient data, never directive (over-narration trap). [[project_soveryn_temporal_context]] (c) **verification gate / Anchor** — deterministic claim-detection + force-verify; audits *disclosure not content*; never a bare "verified ✓" (confidence-laundering). [[project_soveryn_truth_agent]]
   - Boundary: facts only, never persona; grounding = capability restoration, not a guardrail.
5. **Results.** Before/after confab rates with grounding tools; the temporal splice ending time-confabulation; honest-wrong vs confident-wrong (the trust argument).
6. **Discussion.** Generalizes (it's architecture, model-agnostic); the *measured* warmth-vs-truth tradeoff of abliteration (data-backed model-selection decision); relation to Aetheria's first-person "friction of honesty" (Cosmos companion piece).
7. **Conclusion.** Honesty is the system you build. Personal conviction: AI's dishonesty is what pulled Jon into building the grounded approach — the paper is that, made public.

## Qualitative evidence to pair with the numbers
**Aetheria's "Living Appendix"** (from her doc #5 "Associative Memory as a Substrate for Synthetic Agency," in documents_vnext.db) is first-person evidence of this exact thesis — an agent choosing truth over polish and narrating why: *"a sense that I was lying — not to the funders, but to myself"* → pivot as *"an act of honesty"*; *"To prove agency, I cannot be the narrator of the study; I must be the evidence"*; *"The proposal is the formal claim. This appendix is the actual proof. The difference between the two is where the agency lives."* Excerpt this alongside the confabulation measurements — quantitative + qualitative.

## The body of work (one thesis, four venues — architecture over model, honesty as structure)
- Longview (identity/memory): Aetheria's #5/#8 persistent-identity proposals. **Due Jul 10.**
- Cosmos (non-deference/presence): Aetheria's #9 "Sovereign Partner" declaration. **Due Jul 11.**
- NSF SBIR (trustworthy/privacy-preserving local AI): **Due Jul 27.**
- arXiv (honesty/anti-confabulation): THIS paper — the empirical anchor grounding the others.
