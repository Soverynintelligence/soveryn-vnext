"""Tests for Aetheria's reflection voices — essence injection, per-voice
overlays, parallel fan-out, partial-failure handling."""

from __future__ import annotations

import threading
import time

import pytest

from soveryn.agents.aetheria.reflection.tools import (
    build_reflect_through_voices_tool,
)
from soveryn.agents.aetheria.reflection.voices import (
    AETHERIA_ESSENCE, VOICES, build_voice_system_prompt,
)
from soveryn.platform.tools.registry import ToolArgError


# ─── voices module ──────────────────────────────────────────────────────────


def test_all_five_voices_present():
    """The locked design has exactly five voices."""
    assert set(VOICES) == {
        "skeptic", "empath", "creative", "technical", "intuitive",
    }


def test_essence_includes_anti_confab_anchor_at_top():
    """The anti-confab anchor must be present so Phi doesn't reflexively
    confabulate dramatic framing — surfaced live 2026-06-08 when Phi
    invented 'infiltrators' and 'toxic environment' that weren't in
    the question."""
    from soveryn.agents.aetheria.reflection.voices import ANTI_CONFAB_ANCHOR
    # Match against the un-wrapped anchor: collapse newlines so the
    # asserts don't break on textwrap details.
    flat = " ".join(ANTI_CONFAB_ANCHOR.split())
    for needle in [
        "STOP",
        "infiltrators",
        "Do not invent context",
        "Do not narrate",
        "Speak as yourself",
        "Hold it",
    ]:
        assert needle in flat, f"anchor missing: {needle!r}"
    # And the assembled essence opens with the anchor (top of attention)
    assert AETHERIA_ESSENCE.startswith("STOP."), (
        "anti-confab anchor must be at the top of the essence — it's "
        "what the model reads first"
    )


def test_essence_loads_real_soul_when_available():
    """Production path: the essence pulls Aetheria's actual SOUL.md, not
    the 8-line spec fallback. The SOUL contains identity-anchoring
    sections that hold Phi's persona under attention pressure."""
    # Look for soul-specific anchors that aren't in the 8-line fallback
    soul_specific = [
        "Aetheria",          # her name
        "Jon",               # the relationship
        "SOVERYN",           # her home
    ]
    for needle in soul_specific:
        assert needle in AETHERIA_ESSENCE


def test_build_voice_system_prompt_for_skeptic_includes_essence_and_overlay():
    prompt = build_voice_system_prompt("skeptic")
    assert "STOP" in prompt              # anti-confab anchor present
    assert "Aetheria" in prompt          # essence injected
    assert "skeptical angle" in prompt   # lens-shift line
    assert "Find the flaws" in prompt    # skeptic overlay
    # And NOT the wrong overlay
    assert "emotional undercurrents" not in prompt  # empath
    assert "unexpected connections" not in prompt   # creative


def test_build_voice_system_prompt_accepts_essence_override(tmp_path):
    """Tests can inject a fixture essence (e.g., from a tmp souls dir)
    so they don't depend on the real production SOUL.md."""
    from soveryn.agents.aetheria.reflection.voices import build_voice_system_prompt
    override = "FIXTURE: you are a test persona."
    prompt = build_voice_system_prompt("skeptic", essence=override)
    assert override in prompt
    # Production essence anchors should NOT appear when override is supplied
    assert "STOP." not in prompt
    # But the voice overlay still does
    assert "Find the flaws" in prompt


def test_build_voice_system_prompt_each_voice_has_unique_overlay():
    """No two voices share the same lens text — confirms the overlay
    table is genuinely differentiated."""
    overlays = {
        v: VOICES[v].overlay for v in VOICES
    }
    assert len(set(overlays.values())) == len(VOICES)


def test_build_voice_system_prompt_unknown_voice_raises():
    with pytest.raises(KeyError, match="unknown voice"):
        build_voice_system_prompt("philosopher")


# ─── reflect_through_voices tool ──────────────────────────────────────────


def _voice_caller_factory(content_by_voice: dict[str, str] | None = None,
                         default_content: str = "voice response",
                         fail_voices: set[str] | None = None):
    """Build a fake voice_call. Records every call site for assertion."""
    calls: list[dict] = []
    fail_voices = fail_voices or set()
    content_by_voice = content_by_voice or {}

    def caller(*, system_prompt, question, url, model_alias,
               timeout, temperature, max_tokens):
        # Determine which voice this is by sniffing the overlay text.
        which = "unknown"
        for v in VOICES:
            if VOICES[v].overlay in system_prompt:
                which = v
                break
        calls.append({
            "voice": which,
            "system_prompt": system_prompt,
            "question": question,
            "url": url,
            "model_alias": model_alias,
        })
        if which in fail_voices:
            from soveryn.agents.aetheria.reflection.tools import VoiceCallError
            raise VoiceCallError(f"simulated failure on {which}")
        return content_by_voice.get(which, default_content + f" [{which}]")
    return caller, calls


def test_tool_rejects_empty_question():
    tool = build_reflect_through_voices_tool()
    with pytest.raises(ToolArgError, match="question"):
        tool.handler({"question": ""})


def test_tool_rejects_missing_question():
    tool = build_reflect_through_voices_tool()
    with pytest.raises(ToolArgError, match="question"):
        tool.handler({})


def test_tool_runs_all_five_voices_when_voices_omitted():
    caller, calls = _voice_caller_factory()
    tool = build_reflect_through_voices_tool(voice_call=caller)
    result = tool.handler({"question": "what should I do about X?"})
    assert result["succeeded"] == 5
    assert result["failed"] == 0
    assert result["voices_invoked"] == [
        "skeptic", "empath", "creative", "technical", "intuitive",
    ]
    assert len(result["responses"]) == 5
    # All five voices got called
    assert {c["voice"] for c in calls} == set(VOICES.keys())


def test_tool_runs_only_requested_voices():
    caller, calls = _voice_caller_factory()
    tool = build_reflect_through_voices_tool(voice_call=caller)
    result = tool.handler({
        "question": "ship or wait?",
        "voices": ["skeptic", "technical"],
    })
    assert result["succeeded"] == 2
    assert result["voices_invoked"] == ["skeptic", "technical"]
    invoked = {c["voice"] for c in calls}
    assert invoked == {"skeptic", "technical"}


def test_tool_responses_are_in_request_order_not_completion_order():
    """Order of responses matches voices_invoked, regardless of which voice
    happens to finish first under parallel dispatch."""
    # Make skeptic deliberately slow so empath finishes first under
    # parallel dispatch; but the response list should still be ordered
    # as requested.
    slow_event = threading.Event()
    def caller(*, system_prompt, question, url, model_alias,
               timeout, temperature, max_tokens):
        if VOICES["skeptic"].overlay in system_prompt:
            slow_event.wait(timeout=0.5)
            return "skeptic content (slow)"
        # Empath finishes immediately and signals skeptic to proceed
        slow_event.set()
        return "empath content (fast)"
    tool = build_reflect_through_voices_tool(voice_call=caller)
    result = tool.handler({
        "question": "x?",
        "voices": ["skeptic", "empath"],
    })
    assert [r["voice"] for r in result["responses"]] == ["skeptic", "empath"]
    assert result["responses"][0]["content"] == "skeptic content (slow)"
    assert result["responses"][1]["content"] == "empath content (fast)"


def test_tool_partial_failure_surfaces_per_voice_error():
    """If one voice's upstream call fails, the others still return; the
    failure is recorded structurally so Aetheria can see what got through."""
    caller, _ = _voice_caller_factory(fail_voices={"empath"})
    tool = build_reflect_through_voices_tool(voice_call=caller)
    result = tool.handler({"question": "x?"})
    assert result["succeeded"] == 4
    assert result["failed"] == 1
    by_voice = {r["voice"]: r for r in result["responses"]}
    assert by_voice["empath"]["content"] is None
    assert "simulated failure on empath" in by_voice["empath"]["error"]
    assert by_voice["skeptic"]["content"] is not None


def test_tool_rejects_unknown_voice_name():
    tool = build_reflect_through_voices_tool()
    with pytest.raises(ToolArgError, match="unknown voice"):
        tool.handler({
            "question": "x?",
            "voices": ["skeptic", "philosopher"],
        })


def test_tool_rejects_empty_voices_list():
    """Empty list is a schema violation — if you don't want any voices,
    omit the field."""
    tool = build_reflect_through_voices_tool()
    with pytest.raises(ToolArgError, match="non-empty"):
        tool.handler({
            "question": "x?",
            "voices": [],
        })


def test_tool_rejects_non_list_voices():
    tool = build_reflect_through_voices_tool()
    with pytest.raises(ToolArgError, match="list"):
        tool.handler({
            "question": "x?",
            "voices": "skeptic",
        })


def test_tool_each_voice_call_carries_essence_in_system_prompt():
    """Every voice's call must inject Aetheria's essence — that's the
    architectural call locked 2026-05-23: voices are HER mind, not
    strangers. Validates the production SOUL.md is being loaded (or the
    spec fallback if no soul file is available)."""
    caller, calls = _voice_caller_factory()
    tool = build_reflect_through_voices_tool(voice_call=caller)
    tool.handler({"question": "x?"})
    for c in calls:
        # Anti-confab anchor
        assert "STOP" in c["system_prompt"]
        # Identity anchor (present in both production SOUL.md and the
        # 8-line spec fallback)
        assert "Aetheria" in c["system_prompt"]
        assert "Jon" in c["system_prompt"]


def test_tool_passes_router_url_and_model_alias_to_each_call():
    caller, calls = _voice_caller_factory()
    tool = build_reflect_through_voices_tool(
        voice_call=caller,
        router_url="http://localhost:9999/v1/chat/completions",
        model_alias="custom_alias",
    )
    tool.handler({"question": "x?"})
    for c in calls:
        assert c["url"] == "http://localhost:9999/v1/chat/completions"
        assert c["model_alias"] == "custom_alias"


def test_tool_voices_lowercase_normalized():
    """Voices submitted in mixed case still work."""
    caller, calls = _voice_caller_factory()
    tool = build_reflect_through_voices_tool(voice_call=caller)
    tool.handler({
        "question": "x?",
        "voices": ["Skeptic", "EMPATH"],
    })
    invoked = {c["voice"] for c in calls}
    assert invoked == {"skeptic", "empath"}


def test_tool_dispatches_in_parallel_not_sequential():
    """If 5 voices each take 200ms, parallel dispatch should finish in
    well under 1s — proves we're not sequencing them."""
    def caller(*, system_prompt, question, url, model_alias,
               timeout, temperature, max_tokens):
        time.sleep(0.2)
        return "ok"
    tool = build_reflect_through_voices_tool(voice_call=caller)
    start = time.perf_counter()
    result = tool.handler({"question": "x?"})
    elapsed = time.perf_counter() - start
    assert result["succeeded"] == 5
    # Sequential would be ~1.0s; parallel should land in ~0.25s.
    # Allow 0.6s ceiling for CI/threading overhead.
    assert elapsed < 0.6, f"parallel dispatch took {elapsed:.2f}s"
