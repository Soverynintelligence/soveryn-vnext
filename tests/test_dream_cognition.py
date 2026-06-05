"""Tests for soveryn.agents.dream.cognition — HTTP client + 3-pass orchestrator.

Mocked HTTP throughout. The live cognition surface is exercised only by
manual verification post-deploy.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from soveryn.agents.dream.cognition import (
    CognitionError,
    CognitionResult,
    chat_completion,
    run_three_pass,
)
from soveryn.agents.dream.prompt import DreamBriefing, NodeSummary


def _mock_urlopen_with_response(body_text: str):
    """Helper: build a context-manager mock that yields body_text."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "choices": [{"message": {"content": body_text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }).encode()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_response
    return mock_cm


# ─── chat_completion ───────────────────────────────────────────────────────

def test_chat_completion_posts_to_cognition_url():
    with patch("soveryn.agents.dream.cognition.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_urlopen_with_response("hi")
        content = chat_completion(
            url="http://x:8089",
            messages=[{"role": "user", "content": "test"}],
            timeout=10,
        )
    assert content == "hi"
    # Verify URL was hit
    call_url = mock_urlopen.call_args[0][0].full_url
    assert "x:8089" in call_url


def test_chat_completion_raises_cognition_error_on_http_failure():
    import urllib.error
    with patch("soveryn.agents.dream.cognition.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        with pytest.raises(CognitionError):
            chat_completion(
                url="http://x:8089",
                messages=[{"role": "user", "content": "test"}],
                timeout=10,
            )


def test_chat_completion_raises_cognition_error_on_malformed_response():
    """Response without `choices` should fail clearly."""
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"unexpected": "shape"}'
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_response
    with patch("soveryn.agents.dream.cognition.urllib.request.urlopen", return_value=mock_cm):
        with pytest.raises(CognitionError):
            chat_completion(
                url="http://x:8089",
                messages=[{"role": "user", "content": "test"}],
                timeout=10,
            )


# ─── run_three_pass orchestrator ───────────────────────────────────────────

def _briefing():
    return DreamBriefing(
        hours_since_last_dream=24.0,
        nodes=(
            NodeSummary(id="n-1", agent="aetheria", node_type="memory",
                        content_head="test note"),
        ),
        board_summary="Signal: 0",
        recent_daemon_activity="quiet",
        recent_library_writes_count=0,
    )


def test_three_pass_runs_all_three_passes_on_happy_path():
    responses = [
        "assoc result mentioning [node:n-1]",
        "contra result building on assoc [node:n-1]",
        "synth result integrating both [node:n-1]",
    ]
    with patch("soveryn.agents.dream.cognition.chat_completion") as mock_chat:
        mock_chat.side_effect = responses
        result = run_three_pass(
            briefing=_briefing(),
            cognition_url="http://x",
            timeout_seconds=10,
            max_internal_iterations=3,
        )
    assert isinstance(result, CognitionResult)
    assert result.iterations_completed == 3
    assert "synth result" in result.synthesis
    assert result.associations == responses[0]
    assert result.contradictions == responses[1]
    assert result.loop_health == 1.0  # all 3 passes succeeded


def test_three_pass_pass1_failure_bails():
    with patch("soveryn.agents.dream.cognition.chat_completion") as mock_chat:
        mock_chat.side_effect = CognitionError("pass 1 timeout")
        result = run_three_pass(
            briefing=_briefing(),
            cognition_url="http://x",
            timeout_seconds=10,
            max_internal_iterations=3,
        )
    assert result.iterations_completed == 0
    assert result.synthesis == ""
    assert result.loop_health == 0.0
    assert "pass 1 timeout" in (result.error or "")


def test_three_pass_pass2_failure_uses_assoc_as_synth():
    responses = ["assoc good", CognitionError("pass 2 failed")]
    with patch("soveryn.agents.dream.cognition.chat_completion") as mock_chat:
        mock_chat.side_effect = responses
        result = run_three_pass(
            briefing=_briefing(),
            cognition_url="http://x",
            timeout_seconds=10,
            max_internal_iterations=3,
        )
    assert result.iterations_completed == 1
    assert result.synthesis == "assoc good"  # fall back to pass 1 output
    assert 0 < result.loop_health < 1.0


def test_three_pass_max_iterations_cap_respected():
    """If max_internal_iterations=2, only run 2 passes."""
    responses = ["a", "b", "c"]
    with patch("soveryn.agents.dream.cognition.chat_completion") as mock_chat:
        mock_chat.side_effect = responses
        result = run_three_pass(
            briefing=_briefing(),
            cognition_url="http://x",
            timeout_seconds=10,
            max_internal_iterations=2,
        )
    assert mock_chat.call_count == 2  # not 3
    assert result.iterations_completed == 2
