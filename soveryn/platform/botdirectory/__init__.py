"""botdirectory.ai client + local charter imports (never auto-schedule).

Public catalog of bot role prompts (Grok Bot / Hermes Bot Mode genre).
House use: browse inspiration, import charters to disk for Eve/Jon review.
Nothing from this package fires a live timer or posts externally.
"""

from __future__ import annotations

from soveryn.platform.botdirectory.client import (
    BotSummary,
    BotDirectoryError,
    fetch_bot,
    search_bots,
)
from soveryn.platform.botdirectory.store import (
    ImportedCharter,
    get_import,
    import_charter,
    list_imports,
)

__all__ = [
    "BotDirectoryError",
    "BotSummary",
    "ImportedCharter",
    "fetch_bot",
    "get_import",
    "import_charter",
    "list_imports",
    "search_bots",
]
