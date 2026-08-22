"""Standing objectives — multi-step work that outlives one AgentLoop turn.

Commissions remain the short work unit. An objective is the Grok-bot style
assign→execute→verify container: desk-scoped (CWG / HL / SOVERYN), owned by
a peer, checkpointed on disk, resumable after restart.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from soveryn.citizens.census import DESK_DIRS

DESKS: frozenset[str] = frozenset({"cwg", "hl", "soveryn"})
STATES: frozenset[str] = frozenset({
    "active",
    "blocked",
    "ready_for_verify",
    "done",
    "failed",
    "cancelled",
})
DEFAULT_OWNER = "vett"


def _workspace_for(conn, citizen_id: str) -> Path:
    row = conn.execute(
        "SELECT workspace_path FROM citizens WHERE id = ?", (citizen_id,)
    ).fetchone()
    if row is None:
        raise KeyError(citizen_id)
    path = row["workspace_path"] or str(Path.home() / "soveryn_citizens" / citizen_id)
    root = Path(path)
    for name in DESK_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def checkpoint_dir(conn, *, owner_id: str, objective_id: str) -> Path:
    root = _workspace_for(conn, owner_id) / "work" / "objectives" / objective_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def assign(
    conn,
    *,
    desk: str,
    title: str,
    brief: str,
    at: str,
    owner_id: str = DEFAULT_OWNER,
    success_criteria: str = "",
    assigned_by: str = "aetheria",
) -> dict[str, Any]:
    desk = (desk or "").strip().lower()
    owner_id = (owner_id or DEFAULT_OWNER).strip().lower()
    title = (title or "").strip()
    brief = (brief or "").strip()
    if desk not in DESKS:
        raise ValueError(f"desk must be one of {sorted(DESKS)}")
    if not title or not brief:
        raise ValueError("title and brief required")
    exists = conn.execute(
        "SELECT 1 FROM citizens WHERE id = ?", (owner_id,)
    ).fetchone()
    if not exists:
        raise KeyError(f"no citizen {owner_id!r}")

    oid = str(uuid.uuid4())
    path = checkpoint_dir(conn, owner_id=owner_id, objective_id=oid)
    meta = {
        "wave": 0,
        "waves_done": [],
        "findings": [],
        "notes": [],
    }
    (path / "checkpoint.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    (path / "brief.md").write_text(
        f"# {title}\n\n"
        f"- **desk:** {desk}\n"
        f"- **owner:** {owner_id}\n"
        f"- **assigned_by:** {assigned_by}\n"
        f"- **success:** {success_criteria or '(not specified)'}\n\n"
        f"## Brief\n\n{brief}\n",
        encoding="utf-8",
    )
    conn.execute(
        "INSERT INTO objectives "
        "(id, desk, owner_id, title, brief, success_criteria, state, "
        " checkpoint_path, assigned_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)",
        (
            oid,
            desk,
            owner_id,
            title,
            brief,
            (success_criteria or "").strip() or None,
            str(path),
            assigned_by,
            at,
            at,
        ),
    )
    conn.commit()
    return get(conn, oid)  # type: ignore[return-value]


def get(conn, objective_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM objectives WHERE id = ?", (objective_id,)
    ).fetchone()
    return dict(row) if row else None


def list_objectives(
    conn,
    *,
    desk: str | None = None,
    owner_id: str | None = None,
    state: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    q = "SELECT * FROM objectives WHERE 1=1"
    args: list[Any] = []
    if desk:
        q += " AND desk = ?"
        args.append(desk.strip().lower())
    if owner_id:
        q += " AND owner_id = ?"
        args.append(owner_id.strip().lower())
    if state:
        q += " AND state = ?"
        args.append(state.strip().lower())
    q += " ORDER BY updated_at DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(q, args).fetchall()]


def set_state(conn, objective_id: str, *, state: str, at: str) -> dict[str, Any]:
    state = (state or "").strip().lower()
    if state not in STATES:
        raise ValueError(f"state must be one of {sorted(STATES)}")
    row = get(conn, objective_id)
    if row is None:
        raise KeyError(objective_id)
    conn.execute(
        "UPDATE objectives SET state = ?, updated_at = ? WHERE id = ?",
        (state, at, objective_id),
    )
    conn.commit()
    return get(conn, objective_id)  # type: ignore[return-value]


def load_checkpoint(path: str | Path) -> dict[str, Any]:
    p = Path(path) / "checkpoint.json"
    if not p.is_file():
        return {"wave": 0, "waves_done": [], "findings": [], "notes": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"wave": 0, "waves_done": [], "findings": [], "notes": []}


def save_checkpoint(path: str | Path, data: dict[str, Any]) -> None:
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)
    (root / "checkpoint.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def append_finding(path: str | Path, finding: dict[str, Any]) -> dict[str, Any]:
    data = load_checkpoint(path)
    findings = list(data.get("findings") or [])
    findings.append(finding)
    data["findings"] = findings
    save_checkpoint(path, data)
    return data


def research_commission_body(objective: dict[str, Any]) -> str:
    """Body string that citizens-runtime routes to the research wave runner."""
    return (
        f"[RESEARCH_OBJECTIVE {objective['id']}]\n"
        f"desk: {objective['desk']}\n"
        f"title: {objective['title']}\n"
        f"success: {objective.get('success_criteria') or 'sourced pricing table or honest gap'}\n\n"
        f"{objective['brief'].strip()}\n"
    )
