"""Tests for voice UI static assets — file presence + content sanity."""

from pathlib import Path


def test_orb_css_exists_and_defines_aetheria_theme():
    css_path = Path(__file__).parent.parent / "soveryn" / "static" / "voice" / "orb.css"
    assert css_path.is_file()
    content = css_path.read_text()
    assert ".orb-aetheria" in content
    assert "#7a6740" in content  # Lab gold dim — Command Center realignment
    # Per-agent CSS custom properties — Phase 1.5 ready
    assert "--orb-primary" in content


def test_voice_client_js_exists():
    js_path = Path(__file__).parent.parent / "soveryn" / "static" / "voice" / "voice_client.js"
    assert js_path.is_file()
    content = js_path.read_text()
    # Critical findings from spike: audio AND video transceivers
    assert 'addTransceiver("audio"' in content
    assert 'addTransceiver("video"' in content
    # SmallWebRTCTransport offer/answer pattern
    assert "/voice/" in content
    assert "createOffer" in content
    assert "setRemoteDescription" in content


def test_voice_client_js_uses_user_gesture_for_audio():
    """Browser autoplay policy requires user gesture; verify the JS waits
    for a click before initializing audio."""
    js_path = Path(__file__).parent.parent / "soveryn" / "static" / "voice" / "voice_client.js"
    content = js_path.read_text()
    assert "addEventListener" in content
    assert "click" in content


def test_orb_css_defines_all_state_machine_states():
    """The state machine has 6 states; the LivingPresence stylesheet must
    style every state voice_client.js can set on the orb (incl. interrupted)."""
    css_path = Path(__file__).parent.parent / "soveryn" / "static" / "voice" / "presence.css"
    content = css_path.read_text()
    for state in ("idle", "listening", "hearing", "thinking", "speaking", "interrupted"):
        assert f'data-state="{state}"' in content, f"missing state CSS: {state}"
    assert 'data-agent="eve"' in content
    assert 'data-agent="kernel"' in content


def test_voice_landing_roles_follow_live_roster():
    template_path = (
        Path(__file__).parent.parent / "soveryn" / "app" / "templates" / "voice_landing.html"
    )
    content = template_path.read_text()
    assert "agent == 'eve'" in content
    assert "agent == 'kernel'" in content
    assert "agent == 'vett'" not in content
    assert "agent == 'scotty'" not in content


def test_voice_html_template_loads_orb_css_and_voice_client():
    template_path = Path(__file__).parent.parent / "soveryn" / "app" / "templates" / "voice.html"
    content = template_path.read_text()
    assert "/static/voice/orb.css" in content
    assert "/static/voice/voice_client.js" in content
    assert 'id="orb"' in content
    assert '{{ agent }}' in content  # per-agent class
