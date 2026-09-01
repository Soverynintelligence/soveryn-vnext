"""Per-citizen shape prefs — Grok-bot style badges the user can pick."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SHAPES: tuple[str, ...] = (
    "round",
    "squircle",
    "pill",
    "bean",
    "diamond",
    "egg",
    "triangle",
    "hex",
    "heart",
    "star",
    "drop",
    "moon",
    "cloud",
    "clover",
    "shield",
    "blob",
)
SHAPE_LABELS: dict[str, str] = {
    "round": "Round",
    "squircle": "Square",
    "pill": "Pill",
    "bean": "Bean",
    "diamond": "Diamond",
    "egg": "Egg",
    "triangle": "Triangle",
    "hex": "Hex",
    "heart": "Heart",
    "star": "Star",
    "drop": "Drop",
    "moon": "Moon",
    "cloud": "Cloud",
    "clover": "Clover",
    "shield": "Shield",
    "blob": "Blob",
}
DEFAULTS: dict[str, str] = {
    "aetheria": "round",
    "kernel": "squircle",
    "eve": "pill",
    "t_critic": "diamond",
    "t_scout": "bean",
}


def _data_root(data_root: Path | None = None) -> Path:
    if data_root is not None:
        return Path(data_root)
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    from soveryn.config.loader import DEFAULT_DATA_ROOT

    return Path(DEFAULT_DATA_ROOT)


def shapes_path(data_root: Path | None = None) -> Path:
    return _data_root(data_root) / "citizen_shapes.json"


def load_shapes(data_root: Path | None = None) -> dict[str, str]:
    path = shapes_path(data_root)
    out = dict(DEFAULTS)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            for key, val in raw.items():
                if str(val) in SHAPES:
                    out[str(key).strip().lower()] = str(val)
    return out


def save_shapes(mapping: dict[str, str], *, data_root: Path | None = None) -> None:
    path = shapes_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {
        str(k).strip().lower(): v
        for k, v in mapping.items()
        if v in SHAPES and str(k).strip()
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def set_shape(
    agent: str, shape: str, *, data_root: Path | None = None
) -> dict[str, Any]:
    agent = (agent or "").strip().lower()
    shape = (shape or "").strip().lower()
    if not agent:
        raise ValueError("agent required")
    if shape not in SHAPES:
        raise ValueError(f"shape must be one of {', '.join(SHAPES)}")
    mapping = load_shapes(data_root)
    mapping[agent] = shape
    save_shapes(mapping, data_root=data_root)
    return {"agent": agent, "shape": shape, "shapes": mapping}


def catalog() -> list[dict[str, str]]:
    return [{"id": s, "label": SHAPE_LABELS[s]} for s in SHAPES]
