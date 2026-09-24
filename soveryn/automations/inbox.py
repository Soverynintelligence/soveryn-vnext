"""Automations CC inbox — append-only JSONL of fired runs.

Hermes-inspired: deliver to a local surface by default (here: Command Center
inbox) rather than egressing. Signal preview may be recorded; live Signal
send is a separate gate (off this pass).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _data_root() -> Path:
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    from soveryn.config.loader import DEFAULT_DATA_ROOT

    return Path(DEFAULT_DATA_ROOT)


def inbox_path(data_root: Path | None = None) -> Path:
    root = Path(data_root) if data_root is not None else _data_root()
    return root / "automations" / "inbox.jsonl"


def append_inbox(
    *,
    automation_id: str,
    title: str,
    agent: str,
    channels: list[str],
    status: str,
    content: str = "",
    session_id: str | None = None,
    signal_preview: str | None = None,
    source: str = "manual",
    error: str | None = None,
    data_root: Path | None = None,
) -> Dict[str, Any]:
    """Append one inbox row. Returns the record written."""
    path = inbox_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "automation_id": automation_id,
        "title": title,
        "agent": agent,
        "channels": list(channels),
        "fired_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "content": content or "",
        "session_id": session_id,
        "signal_preview": signal_preview,
        "source": source,
        "error": error,
        "read": False,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
    return record


def list_inbox(
    *,
    limit: int = 40,
    data_root: Path | None = None,
) -> List[Dict[str, Any]]:
    """Newest-first inbox rows (tail read)."""
    path = inbox_path(data_root)
    if not path.is_file():
        return []
    limit = max(1, min(int(limit), 200))
    try:
        # Cheap tail: last ~512KB is plenty for recent rows.
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > 512 * 1024:
                fh.seek(size - 512 * 1024)
                fh.readline()
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    rows: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    rows.reverse()
    return rows[:limit]
