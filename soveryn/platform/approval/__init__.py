"""Approval Gate — deterministic human-approval boundary for egress tool calls.

Every egress tool call (email, signal, messenger, web, x-post) is intercepted
at the tool-dispatch boundary before it leaves the house. The gate creates a
pending approval request, blocks the agent loop, and only releases the call
when a human explicitly approves it. On timeout the request expires and the
egress is denied — the fail-safe is that nothing leaves without a yes.

The public surface is intentionally small:

  - `store` — the :class:`ApprovalStore` (SQLite, deterministic ids, no
    wall-clock calls inside the module) and the :class:`ApprovalBroker`
    (blocking wait + decide, the thing the loop and the API route both touch).

This mirrors the sibling :mod:`soveryn.platform.verification` package in
shape: a small, pure, deterministic mechanism with a tiny public surface,
designed so the loop's integration is a few lines and a non-gated path is a
no-op.
"""

from __future__ import annotations

from soveryn.platform.approval.store import (
    STATE_APPROVED,
    STATE_DENIED,
    STATE_EXPIRED,
    STATE_PENDING,
    ApprovalBroker,
    ApprovalRequest,
    ApprovalStore,
)

__all__ = [
    "STATE_PENDING",
    "STATE_APPROVED",
    "STATE_DENIED",
    "STATE_EXPIRED",
    "ApprovalRequest",
    "ApprovalStore",
    "ApprovalBroker",
]
