"""Specialist concurrency cap — limits how many specialists Aetheria can
have active at once. Backstops accidental spawn loops the same way the
DAC rate limiter backstops loop-chatter.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


_SPECIALIST_SESSION_TITLE_PREFIX = "[specialist:"
_DEFAULT_CONCURRENCY_CAP = 3


def count_active_specialists(
    conv_db_path: Path,
    *,
    title_prefix: str = _SPECIALIST_SESSION_TITLE_PREFIX,
) -> int:
    """Count conv_meta rows whose title starts with the specialist prefix.

    A specialist is "active" iff it has a session whose title hasn't been
    rewritten by terminate_specialist (which retitles to '[specialist-archived:...]').
    Simple and honest; no separate registry to drift out of sync with reality.
    """
    with sqlite3.connect(str(conv_db_path)) as con:
        row = con.execute(
            "SELECT COUNT(*) FROM conversation_meta WHERE title LIKE ?",
            (title_prefix + "%",),
        ).fetchone()
    return int(row[0]) if row else 0


def is_at_concurrency_cap(
    conv_db_path: Path,
    *,
    cap: int = _DEFAULT_CONCURRENCY_CAP,
) -> bool:
    return count_active_specialists(conv_db_path) >= cap
