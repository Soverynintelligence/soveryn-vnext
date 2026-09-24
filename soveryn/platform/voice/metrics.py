"""Voice turn metrics — JSONL sink for duplex shell (PR1).

Design: docs/designs/2026-08-16-duplex-voice-shell.md

Enabled by default (``SOVERYN_VOICE_METRICS=1``). Writes one JSON object per
line under ``{data_root}/telemetry/voice_turns.jsonl``. Failures never raise
into the pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()


def _default_metrics_path() -> Path:
    root = Path(os.environ.get("SOVERYN_DATA_ROOT") or "data")
    return root / "telemetry" / "voice_turns.jsonl"


def metrics_enabled(env: dict[str, str] | None = None) -> bool:
    e = env if env is not None else os.environ
    raw = e.get("SOVERYN_VOICE_METRICS", "1")
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class TurnMetric:
    """One voice turn (or barge event) record."""

    ts: str
    agent: str
    session_id: str
    turn_id: str
    turn_epoch: int = 0
    stt_ms: int | None = None
    llm_ttft_ms: int | None = None
    tts_first_audio_ms: int | None = None
    e2e_first_audio_ms: int | None = None
    barge_in: bool = False
    barge_accept_to_playout_stop_ms: int | None = None
    barge_vad_start_to_playout_stop_ms: int | None = None
    f5_clauses_completed_after_cancel: int | None = None
    cancel_reason: str | None = None
    user_chars: int = 0
    assistant_chars_spoken: int = 0
    adapter: str = "agent_loop"
    warm: bool | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json_row(self) -> dict[str, Any]:
        row = asdict(self)
        extra = row.pop("extra", None) or {}
        for k, v in extra.items():
            if k not in row or row[k] is None:
                row[k] = v
        # Drop Nones for compact JSONL
        return {k: v for k, v in row.items() if v is not None}


def emit_turn_metric(
    metric: TurnMetric,
    *,
    path: Path | None = None,
    enabled: bool | None = None,
) -> None:
    """Append one metric row. Never raises."""
    if enabled is None:
        enabled = metrics_enabled()
    if not enabled:
        return
    out = path or _default_metrics_path()
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(metric.to_json_row(), ensure_ascii=False) + "\n"
        with _write_lock:
            with out.open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception:  # noqa: BLE001 — metrics must not break voice
        logger.exception("voice metrics write failed path=%s", out)


class TurnMetricsTracker:
    """In-pipeline turn timer shared by STT, bridge, and first-audio probe.

    Lifecycle for one user turn:
      mark_stt_start → mark_stt_end → mark_user_text → mark_llm_first_token
      → mark_tts_first_audio → finish(cancel_reason=?)
    """

    def __init__(
        self,
        *,
        agent: str,
        session_id: str,
        adapter: str = "agent_loop",
        path: Path | None = None,
        enabled: bool | None = None,
    ):
        self.agent = agent
        self.session_id = session_id
        self.adapter = adapter
        self._path = path
        self._enabled = metrics_enabled() if enabled is None else enabled
        self.turn_epoch = 0
        self._reset_turn()

    def _reset_turn(self) -> None:
        self.turn_id = uuid.uuid4().hex[:12]
        self._t0_user_final: float | None = None
        self._t_stt_start: float | None = None
        self._t_stt_end: float | None = None
        self._t_llm_first: float | None = None
        self._t_tts_first: float | None = None
        self._user_chars = 0
        self._assistant_chars = 0
        self._barge_in = False
        self._cancel_reason: str | None = None
        self._finished = False

    def begin_user_turn(self, user_text: str, *, stt_ms: int | None = None) -> None:
        """Call when a final transcript starts an agent turn."""
        if self._enabled and not self._finished and self._t0_user_final is not None:
            # Previous turn never closed (disconnect mid-turn) — still emit what we have.
            self.finish()
        self._reset_turn()
        now = time.perf_counter()
        self._t0_user_final = now
        self._user_chars = len(user_text or "")
        if stt_ms is not None:
            self._t_stt_end = now
            self._t_stt_start = now - (stt_ms / 1000.0)

    def mark_stt_start(self) -> None:
        self._t_stt_start = time.perf_counter()

    def mark_stt_end(self) -> int | None:
        self._t_stt_end = time.perf_counter()
        if self._t_stt_start is None:
            return None
        return int(round((self._t_stt_end - self._t_stt_start) * 1000))

    def mark_llm_first_token(self, chunk: str = "") -> None:
        if self._t_llm_first is None:
            self._t_llm_first = time.perf_counter()
        self._assistant_chars += len(chunk or "")

    def note_assistant_chars(self, chunk: str) -> None:
        self._assistant_chars += len(chunk or "")

    def mark_tts_first_audio(self) -> bool:
        """Record first TTS audio. Returns True if this was the first chunk."""
        if self._t_tts_first is None:
            self._t_tts_first = time.perf_counter()
            return True
        return False

    def has_open_turn(self) -> bool:
        return (
            not self._finished
            and self._t0_user_final is not None
        )

    def note_barge_in(self, reason: str = "barge_in") -> None:
        self._barge_in = True
        self._cancel_reason = reason

    def note_cancel(self, reason: str) -> None:
        self._cancel_reason = reason

    def finish(self) -> None:
        if not self._enabled or self._finished:
            return
        if self._t0_user_final is None and self._user_chars == 0:
            return
        self._finished = True
        t0 = self._t0_user_final
        stt_ms = None
        if self._t_stt_start is not None and self._t_stt_end is not None:
            stt_ms = int(round((self._t_stt_end - self._t_stt_start) * 1000))
        llm_ttft = None
        if t0 is not None and self._t_llm_first is not None:
            llm_ttft = int(round((self._t_llm_first - t0) * 1000))
        tts_first = None
        e2e = None
        if t0 is not None and self._t_tts_first is not None:
            e2e = int(round((self._t_tts_first - t0) * 1000))
            if self._t_llm_first is not None:
                tts_first = int(round((self._t_tts_first - self._t_llm_first) * 1000))
            else:
                tts_first = e2e

        metric = TurnMetric(
            ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            agent=self.agent,
            session_id=self.session_id,
            turn_id=self.turn_id,
            turn_epoch=self.turn_epoch,
            stt_ms=stt_ms,
            llm_ttft_ms=llm_ttft,
            tts_first_audio_ms=tts_first,
            e2e_first_audio_ms=e2e,
            barge_in=self._barge_in,
            cancel_reason=self._cancel_reason,
            user_chars=self._user_chars,
            assistant_chars_spoken=self._assistant_chars,
            adapter=self.adapter,
        )
        emit_turn_metric(metric, path=self._path, enabled=True)
