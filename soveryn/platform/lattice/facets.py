"""Provisional Aetheria-local facets stored as Entry metadata."""

from __future__ import annotations

from dataclasses import replace

from soveryn.platform.lattice.types import Entry

FACET_METADATA_KEY = "facets"
PROVISIONAL_FACETS = frozenset({
    "working_context",
    "pattern_reservoir",
    "friction_log",
    "salience_cache",
})


def get_facets(entry: Entry) -> tuple[str, ...]:
    raw = entry.metadata.get(FACET_METADATA_KEY, ())
    if isinstance(raw, str):
        raw = (raw,)
    try:
        return tuple(str(item) for item in raw if str(item).strip())
    except TypeError:
        return ()


def add_facet(entry: Entry, facet: str) -> Entry:
    label = _normalize_facet(facet)
    facets = tuple(dict.fromkeys((*get_facets(entry), label)))
    return _with_facets(entry, facets)


def remove_facet(entry: Entry, facet: str) -> Entry:
    label = _normalize_facet(facet)
    return _with_facets(entry, tuple(item for item in get_facets(entry) if item != label))


def replace_facet(entry: Entry, old: str, new: str) -> Entry:
    old_label = _normalize_facet(old)
    new_label = _normalize_facet(new)
    replaced = tuple(new_label if item == old_label else item for item in get_facets(entry))
    if old_label not in get_facets(entry):
        replaced = (*replaced, new_label)
    return _with_facets(entry, tuple(dict.fromkeys(replaced)))


def _with_facets(entry: Entry, facets: tuple[str, ...]) -> Entry:
    metadata = dict(entry.metadata)
    metadata[FACET_METADATA_KEY] = list(facets)
    return replace(entry, metadata=metadata)


def _normalize_facet(facet: str) -> str:
    label = facet.strip().lower().replace("-", "_").replace(" ", "_")
    if not label:
        raise ValueError("facet must be non-empty")
    return label
