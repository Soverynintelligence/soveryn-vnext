"""Delta framing for heartbeat pulses.

Compares the current pulse snapshot to the previous pulse (retrieved from
ThoughtsLog.last()) so the heartbeat reacts to what CHANGED instead of
re-summarising a static board.

Pure module — no I/O, no DB access, no persona/lattice/cognition imports.
Deterministic given identical inputs.

Expected ``current`` snapshot shape (Task 7 reference)::

    {
        "board": {
            "open_signal_count":                int,
            "open_blueprint_count":             int,
            "ready_blueprint_count":            int,
            "open_friction_count":              int,
            "stalled_blueprint_count":          int,
            "blocked_blueprint_count":          int,
            "oldest_open_signal_age_minutes":   int | None,
            "oldest_open_blueprint_title":      str | None,
            "oldest_open_blueprint_age_hours":  int | None,
        },
        "material_signals": [
            {"kind": str, "ref": str, "detail": str},
            ...
        ],
        "lattice": {
            "new_node_count_recent_window":     int,
            "recent_window_minutes":            int,
            "new_contradiction_flag_count":     int,
        },
    }

``prev_record`` is a ThoughtsLog record dict that carries a ``"snapshot"`` key
holding a previously persisted snapshot in the same shape.  Pass the return
value of ``ThoughtsLog.last()`` directly; ``None`` means first pulse since
restart.

Return value::

    {"changed": bool, "items": list[str]}

``items`` are human-readable strings naming what changed (new signals, count
transitions, etc.).  Empty when ``changed`` is False.
"""

from __future__ import annotations

# ── Board fields compared as counts (change in either direction is notable) ──

_BOARD_COUNT_FIELDS: tuple[tuple[str, str], ...] = (
    ("open_signal_count",       "open signal count"),
    ("open_blueprint_count",    "open blueprint count"),
    ("ready_blueprint_count",   "ready blueprint count"),
    ("open_friction_count",     "open friction count"),
    ("stalled_blueprint_count", "stalled blueprint count"),
    ("blocked_blueprint_count", "blocked blueprint count"),
)

# Material-signal identity key: (kind, ref).  Two signals with the same kind+ref
# are considered the same signal; a signal in current not seen in prev is NEW.
def _signal_key(sig: dict) -> tuple[str, str]:
    return (sig.get("kind", ""), sig.get("ref", ""))


def compute_delta(current: dict, prev_record: dict | None) -> dict:
    """Return ``{"changed": bool, "items": list[str]}``.

    Args:
        current:     The current pulse snapshot (shape documented in module
                     docstring above).
        prev_record: The most recent ThoughtsLog record (from
                     ``ThoughtsLog.last()``), or ``None`` on first pulse.

    Returns:
        A dict with:
        - ``"changed"``: ``True`` if anything material differs.
        - ``"items"``: Human-readable list of what changed.  Empty when
          ``changed`` is ``False``.
    """
    # ── First pulse after restart ─────────────────────────────────────────────
    if prev_record is None:
        return {"changed": True, "items": ["first pulse since restart"]}

    prev_snapshot: dict = prev_record.get("snapshot") or {}

    items: list[str] = []

    # ── Board count comparisons ───────────────────────────────────────────────
    current_board: dict = current.get("board") or {}
    prev_board: dict = prev_snapshot.get("board") or {}

    for field, label in _BOARD_COUNT_FIELDS:
        cur_val = current_board.get(field)
        prv_val = prev_board.get(field)
        if cur_val != prv_val:
            items.append(f"{label} changed: {prv_val} → {cur_val}")

    # ── New material signals (present now, not in prev) ───────────────────────
    current_signals: list[dict] = current.get("material_signals") or []
    prev_signals: list[dict] = prev_snapshot.get("material_signals") or []
    prev_keys: set[tuple[str, str]] = {_signal_key(s) for s in prev_signals}

    for sig in current_signals:
        key = _signal_key(sig)
        if key not in prev_keys:
            ref = sig.get("ref", "unknown")
            kind = sig.get("kind", "unknown")
            detail = sig.get("detail", "")
            items.append(f"new {kind} signal: {ref} — {detail}")

    # ── Result ────────────────────────────────────────────────────────────────
    return {"changed": bool(items), "items": items}
