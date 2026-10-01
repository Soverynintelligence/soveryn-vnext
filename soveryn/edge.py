"""Trust mark between the public gate and the app.

The gate dials the app from 127.0.0.1, so the socket peer is not proof the
caller is on this machine. The gate strips any client-supplied copy of
EDGE_HEADER and sets it to EDGE_PUBLIC on every proxied request. Direct
fleet calls to :5001 do not set it. A caller who sets the header on :5001
themselves only gives up localhost privilege.
"""
from __future__ import annotations

EDGE_HEADER = "X-Soveryn-Edge"
EDGE_PUBLIC = "public"

_LOOPBACK = frozenset({"127.0.0.1", "::1"})


def is_operator_local(remote_addr: str | None, headers) -> bool:
    """True only for a direct loopback connection that did not come through the gate."""
    mark = ""
    if headers is not None:
        getter = getattr(headers, "get", None)
        if getter is not None:
            mark = getter(EDGE_HEADER) or ""
    if str(mark).strip().lower() == EDGE_PUBLIC:
        return False
    return (remote_addr or "").strip() in _LOOPBACK
