from soveryn.platform.voice.sanitize import sanitize_for_tts


def test_strips_think_tags():
    raw = "<think>weighing this</think>The answer is forty-two."
    assert sanitize_for_tts(raw) == "The answer is forty-two."


def test_strips_nested_think_tags():
    raw = "<think>outer<think>inner</think>more outer</think>Hi."
    assert sanitize_for_tts(raw) == "Hi."


def test_strips_unclosed_think_tag_safely():
    raw = "<think>this should be dropped if no closer"
    # When a think tag opens but never closes, drop from the tag onward
    assert sanitize_for_tts(raw) == ""


def test_strips_tool_call_json():
    raw = '<tool_call>{"name":"x","args":{}}</tool_call>What I found:'
    assert sanitize_for_tts(raw) == "What I found:"


def test_strips_scratchpad_tags():
    raw = "[SCRATCHPAD: thinking aloud]\nThe call is locked."
    assert "SCRATCHPAD" not in sanitize_for_tts(raw)


def test_strips_resolve_defer_tags():
    raw = "[RESOLVE: yes] The migration shipped. [DEFER: next steps]"
    out = sanitize_for_tts(raw)
    assert "RESOLVE" not in out
    assert "DEFER" not in out
    assert "The migration shipped." in out


def test_collapses_excessive_whitespace():
    raw = "Hello   \n\n\nworld."
    out = sanitize_for_tts(raw)
    assert "   " not in out
    assert "\n\n\n" not in out


def test_strips_control_tokens():
    raw = "<|im_start|>hi<|im_end|> and hello."
    out = sanitize_for_tts(raw)
    assert "<|" not in out
    assert "|>" not in out


def test_preserves_natural_punctuation():
    """Sentence-ending punctuation matters for TTS prosody — don't strip it."""
    raw = "First. Second! Third? Yes."
    out = sanitize_for_tts(raw)
    assert "." in out
    assert "!" in out
    assert "?" in out


def test_empty_input_returns_empty():
    assert sanitize_for_tts("") == ""
    assert sanitize_for_tts("   ") == ""


def test_idempotent():
    raw = "<think>x</think>Hello."
    once = sanitize_for_tts(raw)
    twice = sanitize_for_tts(once)
    assert once == twice


def test_strips_heartbeat_markup():
    """[HEARTBEAT] and similar daemon-scoped markup shouldn't appear in TTS."""
    raw = "[HEARTBEAT 30min ago] Anything to act on?"
    out = sanitize_for_tts(raw)
    assert "[HEARTBEAT" not in out


def test_strips_emoji_that_break_prosody():
    """Emoji throw TTS prosody; strip them. Letters/punctuation stay."""
    raw = "Done ✓ ✨ — ready."
    out = sanitize_for_tts(raw)
    # We'd accept either fully stripped or replaced; the test passes as long
    # as no emoji chars remain
    assert "✓" not in out
    assert "✨" not in out
    assert "ready" in out


def test_passes_through_already_clean_text():
    """Pure prose with periods passes through unchanged."""
    raw = "The migration shipped. Aetheria reports stable."
    assert sanitize_for_tts(raw) == raw


def test_preserves_apostrophes_and_em_dashes():
    """Apostrophes and em-dashes read fine by TTS; preserve them."""
    raw = "It's locked — ready to ship."
    out = sanitize_for_tts(raw)
    assert "it's" in out.lower()
    assert "—" in out

def test_preserve_outer_whitespace_keeps_chunk_boundaries():
    raw = "hello   world"
    out = sanitize_for_tts(raw, preserve_outer_whitespace=True)
    assert out == "hello world"
    assert sanitize_for_tts("   ", preserve_outer_whitespace=True) == ""

def test_strips_markdown_asterisks():
    """F5 would speak leftover * / ** as 'asterisk'."""
    assert sanitize_for_tts("This is **bold** and *italic*.") == "This is bold and italic."
    assert "*" not in sanitize_for_tts("* bullet one")
    assert sanitize_for_tts("She said **yes**.") == "She said yes."
