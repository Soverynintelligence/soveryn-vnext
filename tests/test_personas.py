"""Tests for soveryn.agents.personas."""

import pytest

from soveryn.agents.personas import (
    AETHERIA_PERSONA,
    FORGE_PERSONA,
    PERSONAS,
    PersonaError,
    SCOTTY_PERSONA,
    VETT_PERSONA,
    baked_persona,
    get_persona,
)
from soveryn.config.runtime import ACTIVE_AGENTS


@pytest.fixture
def no_persona_overrides(tmp_path, monkeypatch):
    """Isolate from live data/memory/personas overrides."""
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))


def test_personas_cover_all_active_agents():
    assert set(PERSONAS.keys()) == set(ACTIVE_AGENTS) == {
        "aetheria", "forge", "eve",
    }


def test_personas_is_read_only():
    """MappingProxyType — callers can't mutate."""
    with pytest.raises(TypeError):
        PERSONAS["aetheria"] = "hacked"  # type: ignore[index]


def test_get_persona_returns_aetheria_string(no_persona_overrides):
    assert get_persona("aetheria") == AETHERIA_PERSONA


def test_get_persona_rejects_folded_vett_and_scotty(no_persona_overrides):
    with pytest.raises(PersonaError):
        get_persona("vett")
    with pytest.raises(PersonaError):
        get_persona("scotty")


def test_get_persona_forge_is_baked_and_not_kernel(no_persona_overrides):
    """The 2026-09-29 identity split: the citizen is Forge, never the tower
    prompt, never the build brain's name. The old behavior — the citizen
    wearing config/opencode/agents/kernel.md — was the identity theft."""
    from soveryn.agents import personas as personas_mod

    text = get_persona("forge")
    assert text.startswith("You are Forge")
    assert "NOT Kernel" in text or "not Kernel" in text
    assert "This door (Messages)" in text
    assert personas_mod.persona_source("forge") == "baked"
    # The tower prompt must not leak into the citizen persona.
    from soveryn.agents.personas import read_kernel_tower_prompt
    tower = read_kernel_tower_prompt()
    if tower is not None:
        assert not text.startswith(tower)


def test_get_persona_kernel_is_not_a_citizen(no_persona_overrides):
    """'kernel' is the build brain (Pi harness), not a Messages citizen —
    asking for its persona is a PersonaError, same as retired names."""
    with pytest.raises(PersonaError):
        get_persona("kernel")


def test_forge_chess_is_unparked_wargames_line(no_persona_overrides):
    text = get_persona("forge")
    assert "How about a nice game of chess?" in text
    assert "Unparked" in text


def test_get_persona_returns_eve_string(no_persona_overrides):
    # Assembled default includes builtin CWG fragments; the PERSONAS
    # constant is the core template with <<PLUGIN_FRAGMENTS>>.
    assert get_persona("eve") == baked_persona("eve")
    assert "<<PLUGIN_FRAGMENTS>>" not in get_persona("eve")
    assert "eve_gbp_status" in get_persona("eve")


def test_eve_persona_mentions_decode_qr(no_persona_overrides):
    text = get_persona("eve")
    assert "decode_qr" in text
    assert "pixels" in text.lower()
    assert "make_qr" in text
    assert "compose_image" in text
    assert "make_canvas" in text
    assert "draw_rect" in text
    assert "draw_text" in text


def test_persona_override_round_trip(tmp_path, monkeypatch):
    from soveryn.agents.personas import (
        clear_persona_override,
        persona_source,
        save_persona_override,
    )

    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    assert persona_source("eve") == "baked"
    assert get_persona("eve") == baked_persona("eve")
    save_persona_override("eve", "Eve override for tests.")
    assert persona_source("eve") == "override"
    assert get_persona("eve") == "Eve override for tests."
    clear_persona_override("eve")
    assert persona_source("eve") == "baked"
    assert get_persona("eve") == baked_persona("eve")


def test_get_persona_normalizes_case_and_whitespace(no_persona_overrides):
    assert get_persona("  Aetheria  ") == AETHERIA_PERSONA


@pytest.mark.parametrize("retired", [
    "scout", "vision", "tinker",
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
    # Fleet freeze: Messages peers are Kernel / Eve; Vett/Scotty/Grok parked.
    assert "Kernel" in AETHERIA_PERSONA
    assert "Eve" in AETHERIA_PERSONA
    assert "folded" in AETHERIA_PERSONA.lower()
    assert "route" in AETHERIA_PERSONA.lower() or "Messages" in AETHERIA_PERSONA


def test_aetheria_persona_lists_retired_systems():
    """Persona should remind the model not to treat retired systems as live.

    Teammates Critic/Scout are live overnight outside eye (Messages inboxes) —
    do NOT list bare "Scout" as retired. Legacy stack leftovers stay named.
    """
    for retired_name in ["Vision", "ChromaDB", "Tinker", "aetheria_public"]:
        assert retired_name in AETHERIA_PERSONA
    assert "Messages" in AETHERIA_PERSONA
    assert "Critic" in AETHERIA_PERSONA
    assert "read_overnight_brief" in AETHERIA_PERSONA
    # Must not invent a "Scout is retired" world-model (Teammates Scout is live).
    assert "Scout, Vision" not in AETHERIA_PERSONA


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
    assert "<<" not in get_persona("eve")
    assert "<<" not in baked_persona("eve")


def test_personas_are_strings_not_bytes():
    for p in PERSONAS.values():
        assert isinstance(p, str)
        assert len(p) > 0
