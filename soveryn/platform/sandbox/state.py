"""State persistence for Project Sandbox runs."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from soveryn.platform.sandbox.rules import PERSONA_KEYS, RESOURCE_KEYS, STARTING_ACTIONS


DEFAULT_SEED = "station-alpha"


def run_id_for_seed(seed: str, index: int = 1) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", seed.lower()).strip("-") or "station"
    return f"{slug}-{index:04d}"


def initial_state(seed: str = DEFAULT_SEED, *, run_id: str | None = None) -> dict[str, Any]:
    rid = run_id or run_id_for_seed(seed)
    return {
        "seed": seed,
        "run_id": rid,
        "cycle": 0,
        "status": "active",
        "resources": {
            "power": 50,
            "oxygen": 35,
            "hull": 70,
            "archives": 0,
            "materials": 10,
        },
        "known_rules": [],
        "action_uses": {},
        "research": [],
        "active_research": None,
        "persona_flags": {
            "curiosity": 5,
            "pragmatism": 5,
            "reverence": 0,
            "risk_tolerance": 3,
        },
        "unlocked_sectors": ["core"],
        "available_actions": list(STARTING_ACTIONS),
        "decision_log": [],
        "alerts": [],
    }


class SandboxStore:
    """JSON-backed run directory store.

    State lives at ``<root>/runs/<run_id>/state.json``. The store creates the
    default run lazily so tools have a durable state even before explicit setup.
    """

    def __init__(self, root: Path, *, default_seed: str = DEFAULT_SEED) -> None:
        self.root = Path(root)
        self.default_seed = default_seed

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def path_for_run(self, run_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", run_id).strip(".-") or run_id_for_seed(self.default_seed)
        return self.runs_dir / safe / "state.json"

    def load(self, run_id: str | None = None) -> dict[str, Any]:
        rid = run_id or run_id_for_seed(self.default_seed)
        path = self.path_for_run(rid)
        if not path.exists():
            state = initial_state(self.default_seed, run_id=rid)
            self.save(state)
            return state
        with path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        return normalize_state(state)

    def save(self, state: dict[str, Any]) -> Path:
        state = normalize_state(state)
        path = self.path_for_run(str(state["run_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Fill missing keys so older or hand-authored state remains readable."""

    normalized = deepcopy(initial_state(
        str(state.get("seed") or DEFAULT_SEED),
        run_id=str(state.get("run_id") or run_id_for_seed(str(state.get("seed") or DEFAULT_SEED))),
    ))
    normalized.update(state)
    normalized["resources"] = {
        key: int(normalized.get("resources", {}).get(key, 0))
        for key in RESOURCE_KEYS
    }
    normalized["persona_flags"] = {
        key: int(normalized.get("persona_flags", {}).get(key, 0))
        for key in PERSONA_KEYS
    }
    normalized["known_rules"] = list(normalized.get("known_rules") or [])
    normalized["action_uses"] = dict(normalized.get("action_uses") or {})
    normalized["research"] = list(normalized.get("research") or [])
    normalized["active_research"] = normalized.get("active_research")
    normalized["unlocked_sectors"] = list(normalized.get("unlocked_sectors") or ["core"])
    normalized["available_actions"] = list(normalized.get("available_actions") or STARTING_ACTIONS)
    normalized["decision_log"] = list(normalized.get("decision_log") or [])
    normalized["alerts"] = list(normalized.get("alerts") or [])
    return normalized
