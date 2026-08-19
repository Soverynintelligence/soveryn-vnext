"""ActTruth by SOVERYN — act ledger + unprompted spend allowance.

Stdlib-only portable core. Host apps (SOVERYN) may call
``acttruth.paths.set_default_root(...)`` at startup.
"""

from __future__ import annotations

from acttruth.budget import (
    DEFAULT_MAX_ACTIONS,
    DEFAULT_WINDOW_SECONDS,
    BudgetDecision,
    BudgetPolicy,
    BudgetStore,
)
from acttruth.ledger import ActTruth, EventKind, LedgerEvent, LedgerStore
from acttruth.paths import default_acttruth_dir, set_default_root
from acttruth.wrap import audit_tool, wrap_callable

__all__ = [
    "ActTruth",
    "BudgetDecision",
    "BudgetPolicy",
    "BudgetStore",
    "DEFAULT_MAX_ACTIONS",
    "DEFAULT_WINDOW_SECONDS",
    "EventKind",
    "LedgerEvent",
    "LedgerStore",
    "audit_tool",
    "default_acttruth_dir",
    "set_default_root",
    "wrap_callable",
]

__version__ = "0.1.0"
