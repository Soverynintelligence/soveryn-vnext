"""Salience Engine — Aetheria's substrate of attention.

Closes the Cognitive Gap diagnosed 2026-06-08: she has 1 lifetime
library write because conscious "save this" decisions mid-thought are
a recursive failure. The Salience Engine auto-flags candidate moments
on heuristic markers + embedding novelty; she reviews them at heartbeat
and promotes the resonant ones to library.

See docs/superpowers/specs/2026-06-08-salience-engine-design.md.
"""

from soveryn.platform.salience.markers import (
    MARKER_CATEGORIES,
    MarkerHit,
    detect_markers,
)
from soveryn.platform.salience.observer import (
    DAEMON_SESSION_TITLE_PREFIXES,
    SalienceObserver,
)
from soveryn.platform.salience.store import (
    SalienceCandidate,
    create_buffer_table,
    decay_old_pending,
    insert_candidate,
    mark_promoted,
    pending_candidates_since,
)

__all__ = [
    "DAEMON_SESSION_TITLE_PREFIXES",
    "MARKER_CATEGORIES",
    "MarkerHit",
    "SalienceCandidate",
    "SalienceObserver",
    "create_buffer_table",
    "decay_old_pending",
    "detect_markers",
    "insert_candidate",
    "mark_promoted",
    "pending_candidates_since",
]
