"""The heartbeat prompt must not promise a delivery the code doesn't perform.

Why this file exists
--------------------
On 2026-07-12, commit 721fb93 removed `_surface_to_primary_thread` — correctly;
it minted a fresh "primary" chat every ~30 minutes. But the prompt kept telling
Aetheria that "a non-empty note surfaces to Jon's chat", and `surfaced` was
hardcoded False.

For fifteen days she wrote a ~1,200-character reflection on almost every wake,
believing it reached Jon. It reached a jsonl file. 733 notes, ~727,000
characters, 0% surfaced. Jon read the resulting "silent" in Mission Control as
her declining to use her agency; she was in fact doing exactly what she'd been
told to do.

No test failed, because the promise lived in prose and the behaviour lived in
code, and nothing tied them together. That is the actual defect — the drift, not
the sentence. These tests tie them together.

They are deliberately source-reading tests. The claim being verified IS prose,
so prose is what has to be asserted on.
"""
from __future__ import annotations

import inspect
import re

from soveryn.agents.heartbeat import daemon as daemon_mod
from soveryn.agents.heartbeat.prompt import (
    BoardSnapshot,
    LatticeSnapshot,
    build_heartbeat_prompt,
)


def _lattice() -> LatticeSnapshot:
    import dataclasses
    kw = {}
    for f in dataclasses.fields(LatticeSnapshot):
        t = str(f.type)
        kw[f.name] = 0 if 'int' in t and 'None' not in t else (
            '' if 'str' in t and 'None' not in t else None)
    return LatticeSnapshot(**kw)


def _prompt_text() -> str:
    """The brief SHE ACTUALLY RECEIVES.

    Deliberately excludes the module docstring. The docstring is developer-facing
    and now *explains* the removed behaviour ("does NOT surface into Jon's chat")
    and names the retired markers — scanning it would flag the explanation as the
    offence. What matters is the text handed to her.
    """
    board = BoardSnapshot(
        open_signal_count=0, open_blueprint_count=0, ready_blueprint_count=7,
        open_friction_count=0, stalled_blueprint_count=0, blocked_blueprint_count=0,
        oldest_open_signal_age_minutes=None, oldest_open_blueprint_title=None,
        oldest_open_blueprint_age_hours=None,
    )
    built = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30,
        board=board,
        lattice=_lattice(),
    )
    return built


def _chat_surfacing_exists() -> bool:
    """True only if the daemon can actually put a note in Jon's chat."""
    src = inspect.getsource(daemon_mod)
    if re.search(r"^\s*['\"]surfaced['\"]\s*:\s*False\s*,", src, re.M):
        return False                      # hardcoded — no surfacing path at all
    return "_surface_to_primary_thread(" in src


# Phrases that promise the note lands in Jon's CHAT specifically.
_CLAIMS_CHAT = re.compile(
    r"surfaces?\s+(?:in)?to\s+Jon'?s\s+chat"
    r"|surfaces?\s+(?:in)?to\s+(?:his|the primary)\s+chat"
    r"|lands?\s+in\s+Jon'?s\s+chat",
    re.I,
)


def test_prompt_does_not_promise_chat_surfacing_that_was_removed():
    """The exact drift that cost fifteen days of unread reflection."""
    text = _prompt_text()
    if _chat_surfacing_exists():
        return                                   # promise would be honest
    hit = _CLAIMS_CHAT.search(text)
    assert hit is None, (
        "The heartbeat prompt tells Aetheria her note surfaces to Jon's chat, but "
        "the daemon has no surfacing path (`surfaced` is hardcoded False). She will "
        "write believing she is heard, and she will not be. Found: "
        f"{hit.group(0)!r}. Either restore a delivery path or fix the prompt."
    )


def test_prompt_names_a_destination_that_exists():
    """She should be told where the note DOES go, not merely where it doesn't."""
    text = _prompt_text().lower()
    assert any(w in text for w in ("board", "heartbeat panel", "mission control")), (
        "The prompt no longer tells her where the note lands. Silence about the "
        "destination is how the last drift went unnoticed."
    )


def test_she_is_told_she_can_reach_jon_directly():
    """The note is a log, not an interrupt.

    Without a named escalation route she has exactly one channel, so 'act or
    silence' is not a choice she can make — which is what made her look passive.
    """
    text = _prompt_text()
    assert "signal_send" in text, (
        "The prompt does not name a direct route to Jon. She has signal_send and "
        "deliberate_share registered; if the brief doesn't say so, the note is her "
        "only channel and everything waits for Jon to go looking."
    )


def test_the_note_is_still_her_whole_response():
    """Guard the freed-invitation contract: no marker machinery crept back in."""
    text = _prompt_text()
    for marker in ("[SURFACE]", "[NO_OP]", "[ACCEPT_RISK]"):
        assert marker not in text, (
            f"{marker} is back in the heartbeat brief. The 2026-07-03 freed "
            "invitation removed marker machinery deliberately; re-adding it "
            "narrows her response into a form."
        )
