"""Repair recipe schema declarations and parser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RepairTier = Literal["A", "B", "C"]


class RepairRecipeError(Exception):
    """Raised when a repair recipe file is invalid."""


@dataclass(frozen=True)
class RepairRecipe:
    """Human-authored bounded repair recipe.

    Phase 1 parses and validates recipes only. It does not execute actions.
    """

    name: str
    tier: RepairTier
    preconditions: tuple[str, ...]
    actions: tuple[str, ...]
    verify: tuple[str, ...]
    rollback: tuple[str, ...] = ()
    on_repeated_failure: str = "escalate"


def load_recipe(path: Path) -> RepairRecipe:
    data = _parse_simple_recipe(path.read_text())
    try:
        name = _require_scalar(data, "name")
        tier = _require_tier(data)
        preconditions = _require_list(data, "preconditions")
        actions = _require_list(data, "action")
        verify = _require_list(data, "verify")
    except KeyError as exc:
        raise RepairRecipeError(f"missing required recipe field: {exc.args[0]}") from exc
    rollback = tuple(data.get("rollback") or ())
    on_repeated_failure = str(data.get("on_repeated_failure") or "escalate")
    return RepairRecipe(
        name=name,
        tier=tier,
        preconditions=preconditions,
        actions=actions,
        verify=verify,
        rollback=rollback,
        on_repeated_failure=on_repeated_failure,
    )


def _require_scalar(data: dict[str, object], key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise RepairRecipeError(f"{key} must be a non-empty scalar")
    return value.strip()


def _require_tier(data: dict[str, object]) -> RepairTier:
    value = _require_scalar(data, "tier")
    if value not in {"A", "B", "C"}:
        raise RepairRecipeError("tier must be A, B, or C")
    return value  # type: ignore[return-value]


def _require_list(data: dict[str, object], key: str) -> tuple[str, ...]:
    value = data[key]
    if not isinstance(value, list) or not value:
        raise RepairRecipeError(f"{key} must be a non-empty list")
    return tuple(str(item) for item in value)


def _parse_simple_recipe(text: str) -> dict[str, object]:
    """Parse the small YAML subset used by Phase 1 sample recipes.

    Supported forms are `key: scalar`, `key: null`, and list blocks:

        key:
          - item

    This avoids adding PyYAML just to validate an inert skeleton recipe.
    """
    data: dict[str, object] = {}
    current_list_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current_list_key is None:
                raise RepairRecipeError("list item without list key")
            value = stripped[2:].strip()
            cast_list = data.setdefault(current_list_key, [])
            if not isinstance(cast_list, list):
                raise RepairRecipeError(f"{current_list_key} is not a list")
            cast_list.append(value)
            continue
        if ":" not in stripped:
            raise RepairRecipeError(f"invalid recipe line: {raw_line!r}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            data[key] = []
            current_list_key = key
        elif value == "null":
            data[key] = []
            current_list_key = None
        else:
            data[key] = value.strip('"')
            current_list_key = None
    return data
