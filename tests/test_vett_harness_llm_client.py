"""SoverynVettInferenceModel — chat-completions client for Vett.

Confirms the subclass wires the vendored OpenAIAgentInferenceModel to
our llama-server router (:8090) using the chat-completions API path,
and that it round-trips against the live router.
"""
from __future__ import annotations

import uuid

import pytest

from soveryn.agents.vett.harness.llm_client import SoverynVettInferenceModel


def test_inference_model_constructs_with_defaults():
    """Constructor produces a working OpenAI-compat client without errors.

    2026-07-14 (router SPLIT): vett-scotty lives on the Quadro router (:8091),
    not Aetheria's dedicated Blackwell router (:8090) — she does not share
    her GPU with anyone. Default must target :8091."""
    model = SoverynVettInferenceModel()
    assert model.model == "vett-scotty"
    assert model.api_style == "chat_completions"
    assert model.openai_client.base_url.host in ("127.0.0.1", "localhost")
    assert "8091" in str(model.openai_client.base_url)
    assert "8090" not in str(model.openai_client.base_url)


def test_inference_model_constructor_accepts_overrides():
    """Constructor allows the router URL and model name to be overridden."""
    model = SoverynVettInferenceModel(
        router_url="http://10.0.0.5:9999",
        model_name="custom-alias",
    )
    assert model.model == "custom-alias"
    assert "10.0.0.5:9999" in str(model.openai_client.base_url)


@pytest.mark.integration
def test_inference_model_round_trips_against_live_router():
    """Construct, call against live router, get a non-None Action back."""
    from soveryn.agents.vett.harness.vendor.agent import InferenceContext
    from soveryn.agents.vett.harness.vendor.tools import ToolSet
    from soveryn.agents.vett.harness.vendor.trajectory import (
        ObservationBuilder,
        Trajectory,
    )

    # Seed trajectory with a single user observation so the chat-completions
    # call has a non-empty messages list. ObservationBuilder is the canonical
    # path the vendored harness uses to add user turns.
    obs_builder = ObservationBuilder()
    obs_builder.add_observation(
        "Reply with the single word OK and nothing else.",
        source="user",
    )
    observation = obs_builder.build()

    trajectory = Trajectory(
        actions_and_observations=[observation],
        id=uuid.uuid4(),
    )

    ctx = InferenceContext(
        trajectory=trajectory,
        toolset=ToolSet(),  # empty toolset — pure chat, no tool calls
        max_tokens=64,
    )

    model = SoverynVettInferenceModel()
    action = model(ctx)
    assert action is not None, "model returned None — chat-completions path is broken"
