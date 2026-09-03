"""Reference knowledge base — sibling of the lattice, not a re-index of it.

Lattice keeps weight/salience/graph/provenance (Part A). This store is
read-mostly compressed vectors for docs, specs, catalogs (Part B, Eve 2026-09-01).
"""

from soveryn.platform.kb.recall import format_kb_hits, recall
from soveryn.platform.kb.store import KBStore, default_intake_dir, default_kb_dir

__all__ = [
    "KBStore",
    "default_intake_dir",
    "default_kb_dir",
    "format_kb_hits",
    "recall",
]
