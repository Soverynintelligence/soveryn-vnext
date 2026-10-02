"""Capture 2b goldens from live core (run on unmodified main first).

Used by tests/test_cwg_split_2b_goldens.py. Update files with
``SOVERYN_UPDATE_GOLDEN=1 pytest tests/test_cwg_split_2b_goldens.py``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from flask import Flask

from soveryn.agents.personas import get_persona
from soveryn.automations.registry import load_automations
from soveryn.automations.routines import load_routine
from soveryn.config.loader import load_env_config
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.platform.email.identities import load_identities, board_identities
from soveryn.platform.intake.file_away import all_buckets
from soveryn.platform.ledgers import paths as ledger_paths
from soveryn.platform.social import instagram_desk

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden" / "cwg_split_2b"


def assembled_personas() -> dict[str, str]:
    data_root = load_env_config().data_root
    return {
        "eve": get_persona("eve", data_root=data_root),
        "aetheria": get_persona("aetheria", data_root=data_root),
    }


def tool_schemas_from_app(app: Flask) -> dict[str, list[dict[str, Any]]]:
    registry = app.extensions["soveryn"]["tool_registry"]
    by_owner: dict[str, list[dict[str, Any]]] = {}
    for spec in registry._tools.values():
        by_owner.setdefault(spec.owner, []).append(
            {
                "name": spec.name,
                "description": spec.description,
                "schema": spec.schema,
            }
        )
    out: dict[str, list[dict[str, Any]]] = {}
    for owner in sorted(by_owner):
        rows = sorted(by_owner[owner], key=lambda r: r["name"])
        # Dedup by name (same tool registered once per owner).
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for row in rows:
            if row["name"] in seen:
                continue
            seen.add(row["name"])
            uniq.append(row)
        out[owner] = uniq
    return out


_HOME_PREFIX = re.compile(r"/home/[^/]+")


def stabilize_tool_schemas(obj: Any) -> Any:
    """Drop machine home prefixes so the golden is CI-portable.

    Catalog tool descriptions embed ``~/pondpro/*.json`` as an absolute path
    (``/home/<user>/pondpro/...``). The golden was captured on unmodified
    main; compare after rewriting the home prefix, do not regenerate.
    """
    if isinstance(obj, str):
        return _HOME_PREFIX.sub("{home}", obj)
    if isinstance(obj, dict):
        return {k: stabilize_tool_schemas(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [stabilize_tool_schemas(v) for v in obj]
    return obj


def resolved_cwg_paths(*, root: Path, data_root: Path, home: Path) -> dict[str, str]:
    """Resolve every CWG path the 2b path-parity test locks.

    ``root`` is SOVERYN_ROOT. ``data_root`` is SOVERYN_DATA_ROOT.
    ``home`` is Path.home() at capture time (photo inbox).
    """
    from soveryn.paths import SoverynPaths

    return {
        "soveryn_root": str(SoverynPaths.root()),
        "cwg_csv": str(ledger_paths.cwg_csv(root)),
        "cwg_evidence": str(ledger_paths.evidence_root("cwg", root)),
        "soveryn_csv": str(ledger_paths.soveryn_csv(root)),
        "soveryn_evidence": str(ledger_paths.evidence_root("soveryn", root)),
        "cwg_ig": str(home / "Desktop" / "CWG-Instagram"),
        "cwg_evidence_bucket": str(root / "docs" / "ops" / "tax-cwg" / "evidence"),
        "cwg_insurance": str(root / "docs" / "ops" / "cwg-business" / "insurance"),
        "cwg_licenses": str(root / "docs" / "ops" / "cwg-business" / "licenses"),
        "cwg_vehicles": str(root / "docs" / "ops" / "cwg-business" / "vehicles"),
        "cwg_contracts": str(root / "docs" / "ops" / "cwg-business" / "contracts"),
        "lead_watch_state": str(root / "data" / "memory" / "pondwright_lead_watch.json"),
        "gbp_token_dir": str(data_root / "gbp"),
        "gcal_token_dir": str(data_root / "gcal"),
        "ig_profile_dir": str(instagram_desk.DEFAULT_PROFILE),
        "photo_inbox": str(instagram_desk.DEFAULT_INBOX),
        "file_away_buckets": {
            k: str(v) for k, v in all_buckets().items() if k.startswith("cwg_")
        },
    }


def path_formulas() -> dict[str, str]:
    """Stable relative formulas captured from main (not machine-absolute)."""
    return {
        "cwg_csv": "docs/ops/tax-cwg/CWG-2025-2026-expense-ledger.csv",
        "cwg_evidence": "docs/ops/tax-cwg/evidence",
        "cwg_ig": "{home}/Desktop/CWG-Instagram",
        "cwg_insurance": "docs/ops/cwg-business/insurance",
        "cwg_licenses": "docs/ops/cwg-business/licenses",
        "cwg_vehicles": "docs/ops/cwg-business/vehicles",
        "cwg_contracts": "docs/ops/cwg-business/contracts",
        "lead_watch_state": "data/memory/pondwright_lead_watch.json",
        "gbp_token_dir": "{data}/gbp",
        "gcal_token_dir": "{data}/gcal",
        "ig_profile_dir": "{checkout}/data/eve_ig_profile",
        "photo_inbox": "{home}/Desktop/CWG-Instagram",
    }


def email_identities_snapshot() -> dict[str, Any]:
    identities = load_identities()
    board = board_identities()
    return {
        "identities": identities,
        "domains": list(board.get("domains") or []),
        "desk": board.get("desk") or {},
        "aetheria_allowed_from": board["by_citizen"]["aetheria"]["allowed_from"],
        "eve_allowed_from": board["by_citizen"]["eve"]["allowed_from"],
    }


def routines_and_skills_snapshot() -> dict[str, Any]:
    from soveryn.agents.skills import get_skill_index

    data_root = load_env_config().data_root
    skills_dir = load_env_config().skills_dir
    _catalog, order = load_automations()
    routines = []
    for aid in order:
        doc = load_routine(aid, data_root=data_root)
        routines.append(
            {
                "id": aid,
                "has_routine": doc is not None,
                "source": (doc or {}).get("source"),
                "bytes": (doc or {}).get("bytes"),
            }
        )
    skills = {
        agent: get_skill_index(agent, skills_dir=skills_dir)
        for agent in sorted(ACTIVE_AGENTS)
    }
    return {
        "routine_ids": list(order),
        "routines": routines,
        "skill_index": skills,
    }


def public_agents_payload_shape(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop clock fields so the golden is stable."""
    out = json.loads(json.dumps(payload))
    out["fetched_at"] = "<ts>"
    return out


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
