"""Aetheria's reflection voices — Skeptic / Empath / Creative / Technical /
Intuitive facets of her mind, each running on a non-Gemma backend so the
voices aren't five flavors of the same model.

Architectural call (Jon, 2026-05-23, locked but deferred): make the
voices facets of HER mind (her essence injected into every voice), not
strangers wearing labels. A real mind has one self with multiple
angles; the voices' uniqueness comes from per-voice lens overlays, not
from model family.

v1 ship (2026-06-08): all 5 voices on Phi-3.5-mini-Uncensored
(provisioned as `reflection` alias on the router). Different family
from Aetheria's Gemma 4 31B. If voices read as five flavors of the same
answer, that's the data point to provision psych8k + a Qwen variant
for real model diversity.

See memory:project_soveryn_reflection_voices_persona_overlay.md.
"""
