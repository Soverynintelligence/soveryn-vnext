"""Cross-Surface Continuity — Aetheria's ambient cross-rail awareness.

Closes the gap she diagnosed 2026-06-09: she can push outbound to Signal
but can't read inbound Signal turns back into her working context. This
package builds the Recent Activity Brief that gets injected above pinned
memory on every non-daemon turn.

See docs/superpowers/specs/2026-06-09-cross-surface-continuity-design.md.
"""

from soveryn.platform.continuity.brief import (
    BLOCK_FOOTER,
    BLOCK_HEADER,
    CONTENT_HEAD_CHARS,
    build_recent_activity_brief,
    estimate_tokens,
)
from soveryn.platform.continuity.config import (
    AUTONOMOUS_SESSION_PREFIXES,
    ContinuityConfig,
    DEFAULT_PER_SESSION_CAP,
    DEFAULT_TOKEN_BUDGET,
    DEFAULT_WINDOW_HOURS,
)
from soveryn.platform.continuity.store import (
    DEFAULT_PER_SESSION_PAIRS,
    PairedTurn,
    SessionTail,
    recent_cross_session_tails,
)

__all__ = [
    "AUTONOMOUS_SESSION_PREFIXES",
    "BLOCK_FOOTER",
    "BLOCK_HEADER",
    "CONTENT_HEAD_CHARS",
    "ContinuityConfig",
    "DEFAULT_PER_SESSION_CAP",
    "DEFAULT_PER_SESSION_PAIRS",
    "DEFAULT_TOKEN_BUDGET",
    "DEFAULT_WINDOW_HOURS",
    "PairedTurn",
    "SessionTail",
    "build_recent_activity_brief",
    "estimate_tokens",
    "recent_cross_session_tails",
]
