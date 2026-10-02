"""Public Spark agents (PondWright, Seneca, Atticus) for Mission Control.

These three sit on the Spark and bind 127.0.0.1 only (not the fabric IP),
behind Cloudflare for the public. Browser fetches to public hostnames break
when the tunnel hiccups (CF 1033), so Mission Control must not depend on the
edge. One SSH hop to the Spark reads each agent's /summary + /health on
loopback — counts and short previews only, never full transcripts, never
written into the lattice.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SPARK_SSH_USER = "soverynspark"
SPARK_FABRIC_HOST = "10.10.10.2"
SPARK_WIFI_HOST = "192.168.86.26"
_SSH_TIMEOUT = 6.0
_SSH_CONNECT = 3

PUBLIC_AGENTS: tuple[dict[str, Any], ...] = (
    {
        "id": "pondwright",
        "name": "PondWright",
        "role": "Carolina Water Gardens chat",
        "port": 8200,
        "site": "https://chat.pondwright.com",
        "open": "https://pondwright.com",
    },
    {
        "id": "seneca",
        "name": "Seneca",
        "role": "SOVERYN public voice",
        "port": 8400,
        "site": "https://ask.soverynintelligence.com",
        "open": "https://soverynintelligence.com",
    },
    {
        "id": "atticus",
        "name": "Atticus",
        "role": "History's Ledger curator",
        "port": 8500,
        "site": "https://atticus.historysledger.com",
        "open": "https://atticus.historysledger.com",
    },
)

_CACHE_TTL = 15.0
_cache: dict[str, Any] = {"at": 0.0, "payload": None}

# Owner ack for the "CRM new leads" chip. Leads keep status='new' in the CRM
# until someone works them, so the chip needs its own clear: a watermark of
# when Jon last reviewed. Only leads newer than the watermark count.
_CRM_ACK_FILE = Path.home() / ".soveryn" / "crm_ack"


def _crm_ack_ts() -> str | None:
    try:
        raw = _CRM_ACK_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return raw if raw[:4].isdigit() else None


def ack_crm_new_leads() -> dict[str, Any]:
    """Owner cleared the CRM new-leads chip: watermark now, refresh counts."""
    _CRM_ACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CRM_ACK_FILE.write_text(
        datetime.now(timezone.utc).isoformat(), encoding="utf-8"
    )
    _cache["at"] = 0.0  # bust the 15s cache so the ack shows immediately
    return get_public_agents(force=True)


@dataclass
class AgentGlance:
    id: str
    name: str
    role: str
    site: str
    open: str
    reachable: bool
    enabled: bool | None = None
    model_ok: bool | None = None
    model: str | None = None
    conversations_today: int | None = None
    conversations_total: int | None = None
    leads_captured: int | None = None
    turns_today: int | None = None
    last_activity: str | None = None
    recent: list[dict] = field(default_factory=list)
    error: str | None = None


def _crm_pipeline(ack: str | None = None) -> dict[str, Any]:
    """Live cwg-ops pipeline glance via the tower CRM client. Never raises."""
    unavailable = {
        "ok": False,
        "error": "crm_unavailable",
        "open": "https://crm.pondwright.com/",
        "label": "PondWright CRM",
    }
    try:
        from soveryn.platform.pondwright import crm as pw_crm
        out = pw_crm.pipeline_glance(ack=ack)
    except Exception as e:  # noqa: BLE001 — glance must not blank Mission Control
        unavailable["error"] = type(e).__name__
        return unavailable
    if isinstance(out, dict):
        return out
    return unavailable


def _ssh_json_bundle(host: str) -> dict[str, Any] | None:
    """One SSH: agent summary+health + HL waitlist. CRM is not on this hop.

    PondWright pipeline counts come from the live cwg-ops book over HTTP
    (see `_crm_pipeline`). The legacy `~/pondwright-crm/leads.db` is frozen.
    """
    remote = r"""
python3 - <<'PY'
import json, urllib.request, os
from datetime import datetime, timezone
out = {"agents": {}, "waitlist": {"ok": False}}
for port in (8200, 8400, 8500):
    row = {"summary": None, "health": None, "error": None}
    for kind in ("summary", "health"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/{kind}", timeout=2) as r:
                row[kind] = json.loads(r.read().decode() or "{}")
        except Exception as e:
            row["error"] = f"{kind}:{type(e).__name__}"
    out["agents"][str(port)] = row

# History's Ledger Family waitlist (Atticus) — emails Jon; also on disk
wl_path = os.path.expanduser("~/atticus/waitlist.jsonl")
try:
    lines = []
    if os.path.isfile(wl_path):
        with open(wl_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    recent = []
    today_count = 0
    for raw in lines[-40:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        ts = str(rec.get("ts") or "")
        if ts.startswith(today) or (len(ts) >= 10 and ts[:10] == today):
            today_count += 1
        recent.append({
            "ts": ts,
            "email": (rec.get("email") or "")[:120],
            "name": (rec.get("name") or "")[:80] or "—",
            "note": (rec.get("note") or "")[:100],
            "price_interest": rec.get("price_interest") or "",
            "source": rec.get("source") or "",
            "list": rec.get("list") or "family-year",
        })
    recent = list(reversed(recent[-12:]))  # newest first
    out["waitlist"] = {
        "ok": True,
        "total": len(lines),
        "today": int(today_count),
        "recent": recent[:8],
        "open": "https://historysledger.com/family#waitlist",
        "label": "HL Family waitlist",
    }
except Exception as e:
    out["waitlist"] = {"ok": False, "error": type(e).__name__}
print(json.dumps(out))
PY
"""
    try:
        proc = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={_SSH_CONNECT}",
                "-o", "StrictHostKeyChecking=accept-new",
                f"{SPARK_SSH_USER}@{host}",
                remote,
            ],
            capture_output=True,
            text=True,
            timeout=_SSH_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return None


def _apply_summary(glance: AgentGlance, summary: dict | None, health: dict | None) -> None:
    if health:
        glance.model_ok = health.get("model_ok")
        glance.model = health.get("model")
        if "enabled" in health:
            glance.enabled = bool(health.get("enabled"))
        if health.get("ok") or health.get("model_ok"):
            glance.reachable = True
    if not summary:
        return
    glance.reachable = True
    glance.enabled = bool(summary.get("enabled", True))
    glance.conversations_today = int(summary.get("conversations_today") or 0)
    glance.conversations_total = int(summary.get("conversations_total") or 0)
    glance.leads_captured = int(summary.get("leads_captured") or 0)
    if summary.get("turns_today") is not None:
        glance.turns_today = int(summary.get("turns_today") or 0)
    glance.last_activity = summary.get("last_activity") or None
    recent = summary.get("recent") or []
    if isinstance(recent, list):
        clean = []
        for row in recent[:8]:
            if not isinstance(row, dict):
                continue
            preview = str(row.get("preview") or row.get("last_user") or "").strip()
            if len(preview) > 140:
                preview = preview[:137] + "…"
            clean.append({
                "ts": row.get("ts") or "",
                "preview": preview,
                "captured": bool(row.get("captured")),
            })
        glance.recent = clean


def get_public_agents(*, force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    if (
        not force
        and _cache["payload"] is not None
        and (now - float(_cache["at"])) < _CACHE_TTL
    ):
        return _cache["payload"]

    bundle = None
    path = None
    for host, label in ((SPARK_FABRIC_HOST, "fabric"), (SPARK_WIFI_HOST, "wifi")):
        bundle = _ssh_json_bundle(host)
        if bundle is not None:
            path = label
            break

    # CRM is the live cwg-ops book on the tower tunnel — not the SSH hop,
    # and not the frozen pondwright-crm leads.db. Fail-soft: a dead CRM
    # must not blank PondWright / Seneca / Atticus or the waitlist.
    crm = _crm_pipeline(ack=_crm_ack_ts())
    if not isinstance(crm, dict):
        crm = {"ok": False, "error": "crm_unavailable"}

    # Bundle shape: {agents, waitlist}. Older shape was port-keyed only.
    # A leftover `crm` key from an older Spark script is ignored.
    agent_rows: dict[str, Any] = {}
    waitlist: dict[str, Any] = {"ok": False}
    if isinstance(bundle, dict):
        if "agents" in bundle and isinstance(bundle.get("agents"), dict):
            agent_rows = bundle["agents"]
            waitlist = (
                bundle.get("waitlist")
                if isinstance(bundle.get("waitlist"), dict)
                else waitlist
            )
        else:
            agent_rows = bundle

    agents: list[AgentGlance] = []
    for spec in PUBLIC_AGENTS:
        glance = AgentGlance(
            id=spec["id"],
            name=spec["name"],
            role=spec["role"],
            site=spec["site"],
            open=spec["open"],
            reachable=False,
        )
        if bundle is None:
            glance.error = "spark_unreachable"
            agents.append(glance)
            continue
        row = agent_rows.get(str(spec["port"])) or {}
        if row.get("error") and not row.get("summary") and not row.get("health"):
            glance.error = row.get("error")
        _apply_summary(glance, row.get("summary"), row.get("health"))
        # Prefer CRM pipeline counts for PondWright leads when available.
        if spec["id"] == "pondwright" and crm.get("ok"):
            if crm.get("leads_total") is not None:
                glance.leads_captured = int(crm["leads_total"])
        agents.append(glance)

    # "Talking" = real visitor activity *today* (probes already stripped upstream).
    talking = [
        a.id for a in agents
        if a.reachable and (
            (a.conversations_today or 0) > 0
            or (a.turns_today or 0) > 0
        )
    ]

    # Unified web intake glance for Mission Control (CRM + HL waitlist).
    intake_items: list[dict[str, Any]] = []
    if crm.get("ok"):
        for L in (crm.get("recent") or [])[:6]:
            if not isinstance(L, dict):
                continue
            intake_items.append({
                "channel": "pondwright",
                "kind": "crm_lead",
                "ts": L.get("created_at") or "",
                "who": L.get("name") or "—",
                "detail": " · ".join(
                    x for x in (
                        L.get("phone") or "",
                        L.get("interest") or "",
                        L.get("status") or "",
                    ) if x
                )[:100],
                "status": L.get("status") or "",
            })
    if waitlist.get("ok"):
        for W in (waitlist.get("recent") or [])[:6]:
            if not isinstance(W, dict):
                continue
            intake_items.append({
                "channel": "historysledger",
                "kind": "waitlist",
                "ts": W.get("ts") or "",
                "who": W.get("name") or W.get("email") or "—",
                "detail": " · ".join(
                    x for x in (
                        W.get("email") or "",
                        W.get("note") or "",
                        (f"${W['price_interest']}" if W.get("price_interest") else ""),
                    ) if x
                )[:100],
                "status": "waitlist",
            })
    # Newest first by timestamp string (ISO-ish)
    intake_items.sort(key=lambda r: r.get("ts") or "", reverse=True)

    intake = {
        "ok": bool(crm.get("ok") or waitlist.get("ok")),
        "crm_new": int(crm.get("leads_new") or 0) if crm.get("ok") else 0,
        "crm_today": int(crm.get("leads_today") or 0) if crm.get("ok") else 0,
        "waitlist_today": int(waitlist.get("today") or 0) if waitlist.get("ok") else 0,
        "waitlist_total": int(waitlist.get("total") or 0) if waitlist.get("ok") else 0,
        "pending": (
            (int(crm.get("leads_new") or 0) if crm.get("ok") else 0)
            + (int(waitlist.get("today") or 0) if waitlist.get("ok") else 0)
        ),
        "recent": intake_items[:10],
        "crm_open": crm.get("open") or "https://crm.pondwright.com/",
        "waitlist_open": waitlist.get("open")
        or "https://historysledger.com/family#waitlist",
    }

    payload = {
        "agents": [asdict(a) for a in agents],
        "talking": talking,
        "crm": crm,
        "waitlist": waitlist,
        "intake": intake,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "path": path,
    }
    _cache["at"] = now
    _cache["payload"] = payload
    return payload
