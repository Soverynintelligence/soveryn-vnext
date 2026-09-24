"""Per-automation delivery channel preferences (Command Center / Signal).

Catalog entries still declare a legacy single ``delivery`` target. Effective
channels for dry-run (and later live) come from this prefs file, defaulting
to Command Center so morning output lands where Jon looks first. Signal is
opt-in per automation from the Command Center UI.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

AVAILABLE_CHANNELS: tuple[str, ...] = ("command_center", "signal")
DEFAULT_CHANNELS: tuple[str, ...] = ("command_center",)


def _data_root() -> Path:
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    from soveryn.config.loader import DEFAULT_DATA_ROOT

    return Path(DEFAULT_DATA_ROOT)


def prefs_path(data_root: Path | None = None) -> Path:
    root = Path(data_root) if data_root is not None else _data_root()
    return root / "automations" / "channels.json"


def _normalize(channels: Iterable[str]) -> List[str]:
    seen: List[str] = []
    for ch in channels:
        name = str(ch or "").strip().lower()
        if not name or name not in AVAILABLE_CHANNELS:
            continue
        if name not in seen:
            seen.append(name)
    return seen


def load_channel_prefs(data_root: Path | None = None) -> Dict[str, List[str]]:
    path = prefs_path(data_root)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, Mapping):
        return {}
    out: Dict[str, List[str]] = {}
    for aid, value in raw.items():
        if isinstance(value, Mapping):
            chans = value.get("channels")
        else:
            chans = value
        if isinstance(chans, str):
            chans = [chans]
        if not isinstance(chans, Sequence):
            continue
        norm = _normalize(chans)
        if norm:
            out[str(aid)] = norm
    return out


def save_channel_prefs(
    prefs: Mapping[str, Sequence[str]], *, data_root: Path | None = None
) -> Path:
    path = prefs_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        aid: {"channels": _normalize(chans) or list(DEFAULT_CHANNELS)}
        for aid, chans in prefs.items()
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def resolve_channels(
    automation_id: str, *, data_root: Path | None = None
) -> List[str]:
    """Effective channels for one automation (prefs → default CC)."""
    prefs = load_channel_prefs(data_root)
    if automation_id in prefs:
        return list(prefs[automation_id])
    return list(DEFAULT_CHANNELS)


def set_channels(
    automation_id: str,
    channels: Sequence[str],
    *,
    data_root: Path | None = None,
) -> List[str]:
    """Persist channels for one automation. Raises ValueError if empty/invalid."""
    norm = _normalize(channels)
    if not norm:
        raise ValueError(
            "channels must include at least one of: "
            + ", ".join(AVAILABLE_CHANNELS)
        )
    prefs = load_channel_prefs(data_root)
    prefs[automation_id] = norm
    save_channel_prefs(prefs, data_root=data_root)
    return norm
