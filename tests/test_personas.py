"""Tests for soveryn.agents.personas."""

import pytest

from soveryn.agents.personas import (
    AETHERIA_PERSONA,
    PERSONAS,
    PersonaError,
    SCOTTY_PERSONA,
    VETT_PERSONA,
    get_persona,
)
from soveryn.config.runtime import ACTIVE_AGENTS


def test_personas_has_exactly_the_three_active_agents():
    assert set(PERSONAS.keys()) == set(ACTIVE_AGENTS) == {"aetheria", "vett", "scotty"}


def test_personas_is_read_only():
    """MappingProxyType — callers can't mutate."""
    with pytest.raises(TypeError):
        PERSONAS["aetheria"] = "hacked"  # type: ignore[index]


def test_get_persona_returns_aetheria_string():
    assert get_persona("aetheria") == AETHERIA_PERSONA


def test_get_persona_returns_vett_string():
    assert get_persona("vett") == VETT_PERSONA


def test_get_persona_returns_scotty_string():
    assert get_persona("scotty") == SCOTTY_PERSONA


def test_get_persona_normalizes_case_and_whitespace():
    assert get_persona("  Aetheria  ") == AETHERIA_PERSONA


@pytest.mark.parametrize("retired", [
    "scout", "vision", "tinker", "forge",
    "ares_llm", "aetheria_public", "telegram", "chromadb",
])
def test_get_persona_rejects_retired(retired):
    with pytest.raises(PersonaError, match="retired"):
        get_persona(retired)


def test_get_persona_rejects_unknown():
    with pytest.raises(PersonaError, match="No persona"):
        get_persona("fnord")


# ─── Content sanity (don't drift from Jon's canonical text) ──────────────────

def test_aetheria_persona_mentions_coordination():
    assert "coordinate" in AETHERIA_PERSONA.lower()
    assert "V.E.T.T." in AETHERIA_PERSONA
    assert "Scotty" in AETHERIA_PERSONA


def test_aetheria_persona_lists_retired_systems():
    """Persona should remind the model not to treat retired systems as live."""
    for retired_name in ["Scout", "Vision", "Telegram", "ChromaDB", "Tinker", "aetheria_public"]:
        assert retired_name in AETHERIA_PERSONA


def test_vett_persona_emphasizes_verification():
    assert "verify" in VETT_PERSONA.lower() or "verified" in VETT_PERSONA.lower()
    assert "research" in VETT_PERSONA.lower()


def test_scotty_persona_emphasizes_bounded_execution():
    assert "bounded" in SCOTTY_PERSONA.lower() or "narrow" in SCOTTY_PERSONA.lower()
    assert "verif" in SCOTTY_PERSONA.lower()


def test_no_persona_contains_templating_markers():
    """No f-string / Jinja / format() leftovers — personas are literal text."""
    for p in (AETHERIA_PERSONA, VETT_PERSONA, SCOTTY_PERSONA):
        assert "{" not in p
        assert "}" not in p
        assert "%(" not in p
        assert "<<" not in p


def test_personas_are_strings_not_bytes():
    for p in PERSONAS.values():
        assert isinstance(p, str)
        assert len(p) > 0
