"""Trivial-turn detection — greetings must not open the tool menu."""

from soveryn.agents.turn_scope import is_trivial_user_turn


def test_trivial_greetings_and_acks():
    for text in (
        "hi", "hey", "Hey!", "hello", "good morning",
        "ok", "okay", "thanks", "thank you", "yes", "nope",
        "got it", "sounds good", "cool",
    ):
        assert is_trivial_user_turn(text), text


def test_non_trivial_requests_keep_tools():
    for text in (
        "hey, check the GPUs",
        "ok check the repo",
        "what's on the boards?",
        "you going to check repo changes",
        "stuck on the Hardware Moat brief",
        "search for Nemotron NVFP4",
    ):
        assert not is_trivial_user_turn(text), text


def test_empty_and_long_not_trivial():
    assert not is_trivial_user_turn("")
    assert not is_trivial_user_turn("   ")
    assert not is_trivial_user_turn("x" * 80)
