"""Library layer — cross-agent reference material in the lattice.

Substrate already exists in the lattice (layer='library' on the nodes
table); this module adds the tool surface so agents can intentionally
write to it and search it. Per the design discussion 2026-06-02
([[project-soveryn-library-layer]]):

- Library writes are PASSIVE — they do NOT fire coord webhook events.
  Aetheria notices new library entries via her heartbeat's lattice
  activity count.
- All three agents can write (it's shared reference material).
- Attribution is preserved via the `agent` column on nodes table.

Structural distinction from Signal board posts:
- Library: permanent reference material, stable, "verified fact"
- Signal: workflow item, lifecycle-tracked, "unverified lead needing triage"

Vett would use BOTH on a patrol — choose based on the nature of the
finding, not the author.
"""

from soveryn.platform.library.tools import (
    build_search_library_tool,
    build_write_library_node_tool,
    register_library_tools,
)


__all__ = [
    "build_search_library_tool",
    "build_write_library_node_tool",
    "register_library_tools",
]
