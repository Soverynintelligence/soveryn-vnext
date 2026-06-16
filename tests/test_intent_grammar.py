"""DeliberateShareIntent — the why/stance/trigger grammar value object."""
from __future__ import annotations
import pytest
from dataclasses import FrozenInstanceError

from soveryn.platform.intent.grammar import DeliberateShareIntent


def test_valid_intent_constructs_and_is_frozen():
    intent = DeliberateShareIntent(
        why="This baseline result changes how I read the whole arc.",
        stance="surfacing-tension",
        trigger="node-abc-123",
    )
    assert intent.why == "This baseline result changes how I read the whole arc."
    assert intent.stance == "surfacing-tension"
    assert intent.trigger == "node-abc-123"
    with pytest.raises(FrozenInstanceError):
        intent.stance = "offering"  # frozen


def test_coined_stance_is_accepted_open_vocabulary():
    # The openness IS the contract: any non-blank string passes, no enum.
    intent = DeliberateShareIntent(
        why="naming something we don't have a word for yet",
        stance="reaching-for-a-word-that-doesnt-exist",
        trigger="node-1",
    )
    assert intent.stance == "reaching-for-a-word-that-doesnt-exist"


@pytest.mark.parametrize("field,kwargs", [
    ("why", {"why": "  ", "stance": "offering", "trigger": "n1"}),
    ("stance", {"why": "real reason", "stance": "", "trigger": "n1"}),
    ("trigger", {"why": "real reason", "stance": "offering", "trigger": "   "}),
])
def test_blank_fields_are_rejected(field, kwargs):
    with pytest.raises(ValueError, match=field):
        DeliberateShareIntent(**kwargs)
