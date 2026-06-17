"""Tests for soveryn.agents.representation.cognition."""
from __future__ import annotations

import pytest

from soveryn.agents.representation.cognition import run_representation_pass
from soveryn.agents.representation.parse import Conclusion


def test_runs_and_parses():
    fake = lambda prompt, url: (
        "abductive | fairly confident | Jon prefers honesty | [node:t1]\n"
        "deductive | sure | premise-less dropped | \n"
    )
    out = run_representation_pass(
        subject="jon",
        briefing="[node:t1] x",
        prior_conclusions="",
        cognition_url="http://x",
        chat_fn=fake,
    )
    assert out == [Conclusion("abductive", "fairly confident", "Jon prefers honesty", ("t1",))]


def test_best_effort_on_error():
    def boom(prompt, url):
        raise RuntimeError("server down")

    assert (
        run_representation_pass(
            subject="jon",
            briefing="",
            prior_conclusions="",
            cognition_url="http://x",
            chat_fn=boom,
        )
        == []
    )
