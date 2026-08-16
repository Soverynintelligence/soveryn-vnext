"""Tests for DuplexConfig + voice metrics (PR1 duplex shell)."""

from __future__ import annotations

import json
from pathlib import Path

from soveryn.platform.voice.duplex_config import DuplexConfig
from soveryn.platform.voice.metrics import (
    TurnMetric,
    TurnMetricsTracker,
    emit_turn_metric,
    metrics_enabled,
)


def test_duplex_defaults_preserve_half_duplex_vad():
    cfg = DuplexConfig.from_env({})
    assert cfg.barge_in is False
    assert cfg.confidence == 0.3  # diagnostic default when barge-in off
    assert cfg.stop_secs == 0.3
    assert cfg.metrics_enabled is True
    assert cfg.adapter == "agent_loop"


def test_duplex_barge_in_raises_vad_confidence():
    cfg = DuplexConfig.from_env({"SOVERYN_VOICE_BARGE_IN": "1"})
    assert cfg.barge_in is True
    assert cfg.confidence == 0.7


def test_duplex_vad_confidence_override():
    cfg = DuplexConfig.from_env({
        "SOVERYN_VOICE_BARGE_IN": "0",
        "SOVERYN_VOICE_VAD_CONFIDENCE": "0.55",
    })
    assert cfg.confidence == 0.55


def test_metrics_disabled_env():
    assert metrics_enabled({"SOVERYN_VOICE_METRICS": "0"}) is False
    assert metrics_enabled({"SOVERYN_VOICE_METRICS": "1"}) is True


def test_emit_turn_metric_jsonl(tmp_path: Path):
    path = tmp_path / "telemetry" / "voice_turns.jsonl"
    m = TurnMetric(
        ts="2026-08-16T12:00:00Z",
        agent="aetheria",
        session_id="sess-1",
        turn_id="abc",
        stt_ms=120,
        llm_ttft_ms=400,
        tts_first_audio_ms=700,
        e2e_first_audio_ms=2100,
        user_chars=10,
        assistant_chars_spoken=40,
    )
    emit_turn_metric(m, path=path, enabled=True)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["agent"] == "aetheria"
    assert row["e2e_first_audio_ms"] == 2100
    assert "extra" not in row


def test_tracker_records_e2e(tmp_path: Path):
    path = tmp_path / "voice_turns.jsonl"
    t = TurnMetricsTracker(
        agent="aetheria",
        session_id="s1",
        path=path,
        enabled=True,
    )
    t.mark_stt_start()
    t.mark_stt_end()
    t.begin_user_turn("hello there", stt_ms=150)
    t.mark_llm_first_token("Hi")
    t.note_assistant_chars(" friend.")
    assert t.mark_tts_first_audio() is True
    t.finish()
    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["user_chars"] == len("hello there")
    assert row["stt_ms"] == 150
    assert row["llm_ttft_ms"] is not None
    assert row["e2e_first_audio_ms"] is not None
    assert row["tts_first_audio_ms"] is not None
