"""Memory mechanism boundary for Lattice, Attic, and Regions.

This package exposes storage and retrieval interfaces. Agent-specific recall
wording and response policy belong in agent packages, not here.
"""

from soveryn.platform.lattice.attic import AtticRecord, AtticStore
from soveryn.platform.lattice.legacy import (
    INTENSITY_CORE,
    INTENSITY_DEFAULT,
    INTENSITY_SIGNIFICANT,
    LAYER_GLOBAL,
    LAYER_LIBRARY,
    LAYER_PRIVATE,
    WRITE_LAYERS,
    LatticeError,
    LatticeStore,
    LegacyLatticeAdapter,
    Node,
    embed_text,
    entry_from_node,
    region_for_node,
)
from soveryn.platform.lattice.types import Entry, Region

__all__ = [
    "AtticRecord",
    "AtticStore",
    "Entry",
    "INTENSITY_CORE",
    "INTENSITY_DEFAULT",
    "INTENSITY_SIGNIFICANT",
    "LAYER_GLOBAL",
    "LAYER_LIBRARY",
    "LAYER_PRIVATE",
    "LatticeError",
    "LatticeStore",
    "LegacyLatticeAdapter",
    "Node",
    "Region",
    "WRITE_LAYERS",
    "embed_text",
    "entry_from_node",
    "region_for_node",
]
