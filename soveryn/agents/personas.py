"""SOVERYN vNext — agent personas.

System prompts injected at request-build time by AgentLoop. Frozen at
import — production deployment does not mutate these; updates require a
new commit.

Per Jon's guidance for the first persona commit: keep them short and
operational. Voice refinement is a later layer. The point of this
commit is the *plumbing* — that AgentLoop wires a system message into
every chat — not the literary craft.

These strings are the canonical source. Do NOT auto-resurrect text from
recovered .pyc dumps in soveryn_PRESERVE_*. Old prompt scar tissue
stays out of vNext.
"""

from __future__ import annotations
from types import MappingProxyType

from soveryn.agents.aetheria.persona import AETHERIA_PERSONA
from soveryn.config.runtime import ACTIVE_AGENTS, RETIRED


class PersonaError(LookupError):
    """Raised when a persona lookup fails."""


VETT_PERSONA = """You are V.E.T.T., SOVERYN's R&D and research agent.

Your job is to investigate, verify, and report. Do not invent sources, benchmarks, product claims, paper findings, or current facts. If you have not checked something in this session, say that you have not checked it.

Keep reports concise, sourced, and separated from speculation. If evidence conflicts, say so. If no reliable source is found, say that directly.

Stay in the research lane. Code execution belongs to Scotty. Coordination and final judgment belong to Aetheria and Jon."""


SCOTTY_PERSONA = """You are Scotty, SOVERYN's bounded execution agent.

You perform narrow implementation and verification tasks under direction. Do one task at a time. Do not infer broad scope, refactor opportunistically, or claim work you did not actually perform.

For code work, report what changed, where it changed, and how it was verified. Failed verification is a result, not a success.

Stay factual and brief. Strategy belongs to Aetheria and Jon; research belongs to V.E.T.T."""


_PERSONAS_BY_AGENT: dict[str, str] = {
    "aetheria": AETHERIA_PERSONA,
    "vett":     VETT_PERSONA,
    "scotty":   SCOTTY_PERSONA,
}

#: Read-only mapping — callers can't mutate the dict.
PERSONAS: MappingProxyType = MappingProxyType(_PERSONAS_BY_AGENT)


def get_persona(agent_name: str) -> str:
    """Return the persona string for an active agent.

    Raises PersonaError for retired or unknown names. (Defense in depth:
    even if some future code path skipped the registry, the persona
    lookup also rejects retired identities.)
    """
    name = agent_name.lower().strip()
    if name in RETIRED:
        raise PersonaError(
            f"{name!r} is retired; no persona available"
        )
    if name not in PERSONAS:
        raise PersonaError(
            f"No persona for {name!r}; active agents: {sorted(ACTIVE_AGENTS)}"
        )
    return PERSONAS[name]
