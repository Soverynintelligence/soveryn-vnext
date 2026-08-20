"""Registry types and loading for SOVERYN automations (v0, dry-run)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Delivery:
    """Where an automation's output goes (v0: metadata only, never sent)."""

    channel: str
    target: str


@dataclass(frozen=True)
class AutomationSpec:
    """A single scheduled automation, declared as data, executed as a dry run."""

    id: str
    title: str
    category: str
    agent: str
    cron: str
    prompt: str
    delivery: Delivery
    enabled: bool = True
    dry_run: bool = True


def load_automations() -> Tuple[Dict[str, AutomationSpec], List[str]]:
    """Return (catalog by id, ids in catalog order) from the static catalog.

    Raises ValueError on duplicate ids so the catalog stays a well-formed map.
    """
    from .catalog import CATALOG

    out: Dict[str, AutomationSpec] = {}
    order: List[str] = []
    for spec in CATALOG:
        if spec.id in out:
            raise ValueError(f"duplicate automation id: {spec.id!r}")
        out[spec.id] = spec
        order.append(spec.id)
    return out, order


def get_automation(automation_id: str) -> AutomationSpec:
    """Look up one spec by id; raise KeyError with a helpful message if absent."""
    catalog, _ = load_automations()
    try:
        return catalog[automation_id]
    except KeyError:
        known = ", ".join(catalog)
        raise KeyError(
            f"unknown automation {automation_id!r}; known: {known}"
        ) from None
