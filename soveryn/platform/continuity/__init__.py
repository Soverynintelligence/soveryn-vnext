"""Cross-Surface Continuity — Aetheria's ambient cross-rail awareness.

Closes the gap she diagnosed 2026-06-09: she can push outbound to Signal
but can't read inbound Signal turns back into her working context. This
package builds the Recent Activity Brief that gets injected above pinned
memory on every non-daemon turn.

See docs/superpowers/specs/2026-06-09-cross-surface-continuity-design.md.
"""

from soveryn.platform.continuity.config import (
    AUTONOMOUS_SESSION_PREFIXES,
    ContinuityConfig,
    DEFAULT_PER_SESSION_CAP,
    DEFAULT_TOKEN_BUDGET,
    DEFAULT_WINDOW_HOURS,
)

__all__ = [
    "AUTONOMOUS_SESSION_PREFIXES",
    "ContinuityConfig",
    "DEFAULT_PER_SESSION_CAP",
    "DEFAULT_TOKEN_BUDGET",
    "DEFAULT_WINDOW_HOURS",
]
