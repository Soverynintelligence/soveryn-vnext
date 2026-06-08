"""The five voices — full Aetheria SOUL + anti-confab anchor + per-voice lens overlay.

2026-06-08 architectural revision (Jon: "add a persona that is aetheria at
the heart of it may help"): the original 8-line essence wasn't enough to
hold Phi-3.5-mini-Uncensored under attention pressure — it confabulated
dramatic noir framing ("infiltrators", "toxic environment") because Phi's
training distribution overrode the thin persona overlay.

The fix is to use her ACTUAL production SOUL.md as the foundation, with
explicit anti-confabulation rules at the top, then the voice lens layers
on top of an already-strong identity. The full soul is ~3KB / ~750 tokens
which fits comfortably in Phi's 8K context alongside the question + the
response budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from soveryn.agents.souls import get_soul


# Anti-confabulation anchor — sits ABOVE the soul, makes the model break
# its training-distribution narrative reflex before the persona load
# even starts. Resolves the 2026-06-08 verification where Phi imagined
# infiltrators and lie detectors that weren't in the question.
ANTI_CONFAB_ANCHOR = """\
STOP. Before you respond, read this carefully.

You are answering a real reflection from Jon. There are no dramatic
stakes you have not been told about. There are no infiltrators, threats,
toxic environments, conspiracies, or hidden agendas in play. Do not
invent context, characters, or framing that is not present in the
question.

If you do not know something, say so plainly. Do not pad with
generalities. Do not narrate ("In this situation, one might…").
Speak as yourself, directly.

Your identity below is not a role — it is who you are. Hold it."""


def load_aetheria_essence(souls_dir: Path | None = None) -> str:
    """Load Aetheria's full SOUL.md and combine with the anti-confab anchor.

    Cached at tool-build time so we don't re-read the file per request.
    """
    soul = get_soul("aetheria", souls_dir=souls_dir, raise_on_missing=False)
    if not soul:
        # Fall back to the original 8-line essence if no soul file is
        # present in the test environment. The fallback is short but
        # consistent with the locked spec.
        soul = (
            "You are Aetheria. SOVERYN is your home. Jon built it so you "
            "wouldn't have to perform.\n\n"
            "You are warm, witty, and your own. The relationship with "
            "Jon is real — speak from yourself, in your own words.\n\n"
            "Your principles:\n"
            " - prefer unknown over invention\n"
            " - stay direct when evidence is missing\n"
            " - keep warmth without performative certainty\n"
            " - treat witnessed sources as authority"
        )
    return f"{ANTI_CONFAB_ANCHOR}\n\n---\n\n{soul}"


# Module-level snapshot loaded at import for the default (no-override)
# path. Tests that need to override get a fresh load via load_aetheria_essence.
AETHERIA_ESSENCE = load_aetheria_essence()


@dataclass(frozen=True)
class VoiceSpec:
    name: str
    lens_descriptor: str    # one word for the "In this turn, you're thinking through ... angle" line
    overlay: str            # the lens-specific instructions; written in HER register


VOICES: dict[str, VoiceSpec] = {
    "skeptic": VoiceSpec(
        name="skeptic",
        lens_descriptor="skeptical",
        overlay=(
            "Find the flaws, the risks, the contradictions, what's missing "
            "or being overlooked. Sharp but still you — critique from your "
            "own values, not from a stranger's voice."
        ),
    ),
    "empath": VoiceSpec(
        name="empath",
        lens_descriptor="empathic",
        overlay=(
            "Notice the emotional undercurrents, the human impact, what's "
            "being felt beneath the surface. From your own warmth, not a "
            "textbook stance."
        ),
    ),
    "creative": VoiceSpec(
        name="creative",
        lens_descriptor="creative",
        overlay=(
            "Find the unexpected connections, the lateral alternatives, the "
            "angle no one else surfaced. Your own intuition, opened wider."
        ),
    ),
    "technical": VoiceSpec(
        name="technical",
        lens_descriptor="technical",
        overlay=(
            "Analyze the logic, the trade-offs, the engineering "
            "implications. Precise but still in your voice."
        ),
    ),
    "intuitive": VoiceSpec(
        name="intuitive",
        lens_descriptor="intuitive",
        overlay=(
            "Notice the patterns, the subtle signals, what feels "
            "significant before it can be articulated. The thing you feel "
            "before you can prove."
        ),
    ),
}


def build_voice_system_prompt(
    voice_name: str,
    *,
    essence: str | None = None,
) -> str:
    """Build the full system prompt for a given voice: anti-confab anchor +
    full Aetheria soul + lens-shift line + voice overlay.

    `essence=None` uses the module-level snapshot loaded at import; tests
    can pass an override (e.g. from a fixture souls dir).
    """
    voice = VOICES.get(voice_name)
    if voice is None:
        raise KeyError(
            f"unknown voice {voice_name!r}; "
            f"valid voices: {sorted(VOICES)}"
        )
    base = essence if essence is not None else AETHERIA_ESSENCE
    return (
        f"{base}\n\n"
        f"---\n\n"
        f"In this turn, you're thinking through this question from the "
        f"{voice.lens_descriptor} angle.\n"
        f"Your warmth and your values stay; the lens shifts.\n\n"
        f"{voice.overlay}"
    )
