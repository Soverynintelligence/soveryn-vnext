"""Watch pondwright-cwg-ops for new leads and ping Jon's Messages PWA.

Spark cannot reach tower :5001 (localhost-only). The CRM tunnel is already
on 127.0.0.1:8100, so we poll from here. First tick seeds IDs so history
does not dump eight old cards onto the phone. Source `admin` is quiet —
Jon typed it himself.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_DEFAULT_STATE = Path.home() / "soveryn_vnext" / "data" / "memory" / "pondwright_lead_watch.json"
_INTERVAL = 20.0
_SEEN_CAP = 500
_SKIP_SOURCES = frozenset({"admin", "smoke", "test", "probe"})


def should_ping_source(source: str | None) -> bool:
    s = (source or "").strip().lower()
    if not s:
        return True
    if s in _SKIP_SOURCES or s.startswith("admin"):
        return False
    return True


def _state_path() -> Path:
    raw = (os.environ.get("SOVERYN_LEAD_WATCH_STATE") or "").strip()
    return Path(raw) if raw else _DEFAULT_STATE


def load_seen(path: Path | None = None) -> set[str]:
    p = path or _state_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    ids = data.get("seen") if isinstance(data, dict) else None
    if not isinstance(ids, list):
        return set()
    return {str(x) for x in ids if x}


def save_seen(seen: set[str], path: Path | None = None) -> None:
    p = path or _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    ids = list(seen)[-_SEEN_CAP:]
    p.write_text(json.dumps({"seen": ids}, indent=0) + "\n", encoding="utf-8")


def tick(
    *,
    list_leads: Callable[..., dict[str, Any]] | None = None,
    notify: Callable[[dict[str, Any]], None] | None = None,
    state_path: Path | None = None,
) -> dict[str, Any]:
    from soveryn.platform.pondwright import crm as pw_crm
    from soveryn.platform.webpush.notify import notify_pondwright_lead

    list_fn = list_leads or pw_crm.list_leads
    notify_fn = notify or notify_pondwright_lead
    path = state_path or _state_path()

    out = list_fn(limit=100)
    if out.get("ok") is False or out.get("error"):
        return {"ok": False, "error": out.get("error") or "list_failed"}
    leads = list(out.get("leads") or [])
    ids = [str(L.get("id") or "") for L in leads if L.get("id")]
    seen = load_seen(path)
    if not seen:
        save_seen(set(ids), path)
        return {"ok": True, "seeded": len(ids), "pinged": 0}

    pinged = 0
    for lead in leads:
        lid = str(lead.get("id") or "")
        if not lid or lid in seen:
            continue
        seen.add(lid)
        if not should_ping_source(lead.get("source")):
            continue
        try:
            notify_fn(lead)
            pinged += 1
        except Exception:
            logger.exception("lead_watch: notify failed id=%s", lid)
    save_seen(seen, path)
    return {"ok": True, "pinged": pinged, "seen": len(seen)}


def run_forever(interval: float | None = None) -> None:
    wait = float(interval or os.environ.get("SOVERYN_LEAD_WATCH_INTERVAL") or _INTERVAL)
    logger.info("lead_watch: started interval=%.0fs", wait)
    while True:
        try:
            tick()
        except Exception:
            logger.exception("lead_watch: tick failed")
        time.sleep(max(5.0, wait))
