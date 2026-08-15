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


def _ssh_json_bundle(host: str) -> dict[str, Any] | None:
    """One SSH: curl all three summary+health endpoints on Spark loopback."""
    # JSON object of port -> {summary, health}. Shell must never fail on curl.
    remote = r"""
python3 - <<'PY'
import json, urllib.request
out = {}
for port in (8200, 8400, 8500):
    row = {"summary": None, "health": None, "error": None}
    for kind in ("summary", "health"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/{kind}", timeout=2) as r:
                row[kind] = json.loads(r.read().decode() or "{}")
        except Exception as e:
            row["error"] = f"{kind}:{type(e).__name__}"
    out[str(port)] = row
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
        row = bundle.get(str(spec["port"])) or {}
        if row.get("error") and not row.get("summary") and not row.get("health"):
            glance.error = row.get("error")
        _apply_summary(glance, row.get("summary"), row.get("health"))
        agents.append(glance)

    # "Talking" = real visitor activity *today* (probes already stripped upstream).
    talking = [
        a.id for a in agents
        if a.reachable and (
            (a.conversations_today or 0) > 0
            or (a.turns_today or 0) > 0
        )
    ]
    payload = {
        "agents": [asdict(a) for a in agents],
        "talking": talking,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "path": path,
    }
    _cache["at"] = now
    _cache["payload"] = payload
    return payload
