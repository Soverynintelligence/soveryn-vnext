"""SOVERYN vNext — intent grammar.

The third first-class axis on a share, peer to Provenance (how do I know
this?) and Channel (am I allowed to state this?): Intent — why am I
surfacing this, now? Built as a validated value object, never persona prose.
Deliberate-emit only: silence is the default; the mark is the deliberate
break. See docs/superpowers/specs/2026-06-16-deliberate-share-intent-grammar-design.md.
"""

from soveryn.platform.intent.grammar import DeliberateShareIntent
from soveryn.platform.intent.ledger import record_intent, resolve_trigger

__all__ = ["DeliberateShareIntent", "record_intent", "resolve_trigger"]
