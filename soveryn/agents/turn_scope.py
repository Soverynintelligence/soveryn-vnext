"""Turn-scope helpers — when a user message needs zero tool surface.

Lightning / tool-eager MoEs will inventory coordination boards, lattice,
grants, personal files, etc. on a bare "hey" if every tool is offered
(observed 2026-08-14). Trivial social/ack turns must not advertise tools.
"""

from __future__ import annotations

import re

# Whole-message match only. Keep the pattern strict so "ok, check the GPUs"
# still gets a full tool surface.
_TRIVIAL_USER_RE = re.compile(
    r"(?is)^\s*("
    r"hi|hey+|hello|howdy|yo|sup|hiya|"
    r"good\s*(morning|afternoon|evening|night)|"
    r"gm|gn|"
    r"thanks?(?:\s+you)?|ty|thx|thankyou|"
    r"ok(?:ay)?|k|cool|great|nice|perfect|awesome|"
    r"got\s+it|sounds\s+good|makes\s+sense|"
    r"yes|yep|yeah|yup|sure|no|nope|nah|"
    r"continue|go\s+on|proceed|carry\s+on|"
    r"bye|later|night|"
    r"can\s+you\s+hear\s+me(?:\s+now)?|"
    r"you\s+there|anyone\s+there|"
    r"mm-?h+m+|uh-?huh|mhm|"
    r"testing|test\s+test|"
    r"\.{1,3}|!{1,3}|\?{1,3}"
    r")\s*[.!?]?\s*$"
)

# Soft max length — anything longer is treated as a real request even if it
# starts with "hey".
_TRIVIAL_MAX_LEN = 48


def is_trivial_user_turn(text: str) -> bool:
    """True for pure greetings / acks that must not open the tool menu.

    Returns False for empty (caller decides), research asks, or any message
    with extra content beyond a short social token.
    """
    t = (text or "").strip()
    if not t or len(t) > _TRIVIAL_MAX_LEN:
        return False
    return bool(_TRIVIAL_USER_RE.match(t))
