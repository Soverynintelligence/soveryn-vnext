"""Reference knowledge base — sibling of the lattice, not a re-index of it.

Lattice keeps weight/salience/graph/provenance (Part A). This store is
read-mostly compressed vectors for docs, specs, catalogs (Part B, Eve 2026-09-01).
"""

from soveryn.platform.kb.recall import recall
from soveryn.platform.kb.store import KBStore

__all__ = ["KBStore", "recall"]
