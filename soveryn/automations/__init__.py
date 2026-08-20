"""SOVERYN Automations v0 — dry-run automation layer.

Importing this package must stay light: do NOT import :mod:`runner` here,
because ``python -m soveryn.automations.runner`` would otherwise re-execute
the module (runpy RuntimeWarning). Import the runner explicitly where needed.
"""
from .prefs import (
    AVAILABLE_CHANNELS,
    DEFAULT_CHANNELS,
    resolve_channels,
    set_channels,
)
from .registry import (
    AutomationSpec,
    Delivery,
    get_automation,
    load_automations,
)

__all__ = [
    "AVAILABLE_CHANNELS",
    "DEFAULT_CHANNELS",
    "AutomationSpec",
    "Delivery",
    "get_automation",
    "load_automations",
    "resolve_channels",
    "set_channels",
]
