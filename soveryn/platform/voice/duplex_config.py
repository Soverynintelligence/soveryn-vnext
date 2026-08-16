"""Duplex voice shell configuration (env-driven).

PR1 of docs/designs/2026-08-16-duplex-voice-shell.md: config surface only.
Barge-in defaults **off** so existing half-duplex behavior is unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _truthy(raw: str | None, default: bool = False) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _float_env(env: dict[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    return float(raw)


def _int_env(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class DuplexConfig:
    """Runtime knobs for the cascade duplex shell.

    Defaults preserve today's live half-duplex VAD (confidence 0.3 diagnostic)
    when ``barge_in`` is false. When ``barge_in`` is true, confidence defaults
    to Silero's 0.7 unless ``SOVERYN_VOICE_VAD_CONFIDENCE`` overrides.
    """

    barge_in: bool = False
    stop_secs: float = 0.3
    start_secs: float = 0.1
    confidence: float = 0.3
    min_volume: float = 0.6
    min_barge_ms: int = 150
    backchannel_max_ms: int = 600
    metrics_enabled: bool = True
    adapter: str = "agent_loop"
    tts_agg: str = "sentence"  # PR3 may switch default to token; keep current path

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "DuplexConfig":
        e = env if env is not None else dict(os.environ)
        barge_in = _truthy(e.get("SOVERYN_VOICE_BARGE_IN"), default=False)
        # Preserve diagnostic VAD when barge-in is off (current production).
        conf_default = 0.7 if barge_in else 0.3
        if e.get("SOVERYN_VOICE_VAD_CONFIDENCE") not in (None, ""):
            confidence = float(e["SOVERYN_VOICE_VAD_CONFIDENCE"])
        else:
            confidence = conf_default
        metrics_enabled = _truthy(e.get("SOVERYN_VOICE_METRICS"), default=True)
        adapter = (e.get("SOVERYN_VOICE_ADAPTER") or "agent_loop").strip().lower()
        tts_agg = (e.get("SOVERYN_VOICE_TTS_AGG") or "sentence").strip().lower()
        if tts_agg not in ("token", "sentence"):
            tts_agg = "sentence"
        return cls(
            barge_in=barge_in,
            stop_secs=_float_env(e, "SOVERYN_VOICE_STOP_SECS", 0.3),
            start_secs=_float_env(e, "SOVERYN_VOICE_START_SECS", 0.1),
            confidence=confidence,
            min_volume=_float_env(e, "SOVERYN_VOICE_MIN_VOLUME", 0.6),
            min_barge_ms=_int_env(e, "SOVERYN_VOICE_MIN_BARGE_MS", 150),
            backchannel_max_ms=_int_env(e, "SOVERYN_VOICE_BACKCHANNEL_MAX_MS", 600),
            metrics_enabled=metrics_enabled,
            adapter=adapter,
            tts_agg=tts_agg,
        )
