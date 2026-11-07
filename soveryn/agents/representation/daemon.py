"""Representation daemon process loop.

Spin-bug-resistant tick loop mirroring soveryn/agents/dream/daemon.py.
SIGTERM/SIGINT triggers graceful shutdown.

Constructor accepts injected conv_store, lattice_store, chat_fn, embed_fn,
and config — no module-level DB connections — so tests can drive _do_tick
with fakes and zero HTTP / real model calls.

Run as: `python -m soveryn.agents.representation`.
"""
from __future__ import annotations

import json
import logging
import signal
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from soveryn.agents.representation.briefing import build_briefing
from soveryn.agents.representation.cognition import CognitionFailure, run_representation_pass
from soveryn.agents.representation.sources import recent_turns, is_autonomous_title
from soveryn.agents.representation.novelty_gate import to_ny
from soveryn.agents.representation.config import RepresentationConfig
from soveryn.agents.representation.trigger import evaluate
from soveryn.agents.representation.writeback import write_conclusions
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.lattice.legacy import LatticeStore

logger = logging.getLogger(__name__)

_is_autonomous_title = is_autonomous_title


class RepresentationDaemon:
    """Single-threaded tick loop for the representation pass.

    Mirrors DreamDaemon shape: spin-bug-resistant sleep math, SIGTERM/SIGINT
    handling, injectable deps for clean unit testing.
    """

    def __init__(
        self,
        *,
        conv_store: ConversationStore,
        lattice_store: LatticeStore,
        chat_fn: Callable[[str, str], str] | None,
        embed_fn: Callable[[str], tuple[float, ...]] | None,
        config: RepresentationConfig,
        dryrun_log_path: Path | None = None,
    ) -> None:
        self.conv_store = conv_store
        self.lattice_store = lattice_store
        self.chat_fn = chat_fn
        self.embed_fn = embed_fn
        self.config = config
        # Structured review artifact (one JSONL line per tick with conclusions).
        # None in tests → no file side effect. __main__ wires the real path.
        self.dryrun_log_path = dryrun_log_path
        self._stop = False
        # Advances to `now` on every eligible tick. None = never run.
        self._last_run_at: datetime | None = None

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        logger.info(
            "representation daemon starting. config=%s", self.config
        )
        # Spin-bug-resistant sleep math (mirrors dream daemon 0fb715b pattern):
        # _last_run_at advances only on eligible ticks.
        # last_tick_at advances EVERY tick so sleep_target never drifts into
        # the past on consecutive skipped ticks.
        forge_pass = None
        if self.config.forge_memory_enabled:
            from soveryn.agents.representation.forge_memory import ForgeMemoryPass
            forge_pass = ForgeMemoryPass(
                conv_store=self.conv_store, lattice_store=self.lattice_store,
                config=self.config, chat_fn=self.chat_fn, embed_fn=self.embed_fn,
            )
        last_tick_at: datetime | None = None
        while not self._stop:
            now = datetime.now()
            try:
                summary = self._do_tick(now=now)
                self._record_tick_summary(summary, now=now)
            except Exception:
                logger.exception("representation tick failed")
            if forge_pass is not None and not self._stop:
                try:
                    forge_pass.tick(now=datetime.now())
                except Exception:
                    logger.exception("Forge memory tick failed; house pass unaffected")
            self._record_novelty_gate(now=now)
            last_tick_at = now  # always advance — the spin-bug fix
            sleep_target = last_tick_at + timedelta(
                seconds=self.config.tick_interval_seconds
            )
            while not self._stop and datetime.now() < sleep_target:
                time.sleep(
                    min(0.5, max(0.05, (sleep_target - datetime.now()).total_seconds()))
                )
        logger.info("representation daemon stopped cleanly")

    def _handle_signal(self, *_: Any) -> None:
        logger.info("representation daemon received shutdown signal")
        self._stop = True

    # ─── Per-tick work ──────────────────────────────────────────────────────

    def _do_tick(self, *, now: datetime) -> dict:
        """Execute one daemon tick. Returns a summary dict.

        `now` is injected (never calls datetime.now() internally) so tests
        can drive exact timestamps without patching.

        Summary keys:
            eligible       — bool
            skip_reason    — str | None
            conclusion_count — int (0 when ineligible or empty)
            written        — dict from write_conclusions (dry_run fields, etc.)
        """
        turns = recent_turns(self.conv_store, now=now)
        new_turn_count = sum(self._last_run_at is None or
                            t.timestamp > to_ny(self._last_run_at) for t in turns)
        eligibility = evaluate(new_turn_count, self.config)

        if not eligibility.eligible:
            logger.info(
                "representation tick skipped: %s (new_turns=%d)",
                eligibility.skip_reason, new_turn_count,
            )
            return {
                "eligible": False,
                "skip_reason": eligibility.skip_reason,
                "conclusion_count": 0,
                "written": None,
            }

        run_id = str(uuid.uuid4())
        logger.info(
            "representation tick %s starting. new_turns=%d dry_run=%s",
            run_id, new_turn_count, self.config.dry_run,
        )

        briefing_text, prior_text, source_ids = build_briefing(
            self.conv_store,
            self.lattice_store,
            owner_agent=self.config.owner_agent,
            subject=self.config.subject,
            turns_per_briefing=self.config.turns_per_briefing,
            now=now, turns=turns,
        )

        selected_ids = {i for i in source_ids if i.startswith("turn:")}
        selected = [t for t in turns if t.id in selected_ids]
        evidence_summary = {
            "run_id": run_id, "new_turns": new_turn_count,
            "available_turns": len(turns), "selected_turns": len(selected),
            "selected_ids": [t.id for t in selected],
            "selected_from": selected[0].timestamp.isoformat() if selected else None,
            "selected_through": selected[-1].timestamp.isoformat() if selected else None,
            "selected_agents": sorted({t.agent for t in selected}),
            "pondwright_available": sum(t.agent.casefold() == "pondwright" for t in turns),
        }
        logger.info("representation evidence: %s", evidence_summary)
        try:
            conclusions = run_representation_pass(
                subject=self.config.subject, briefing=briefing_text,
                prior_conclusions=prior_text, cognition_url=self.config.cognition_url,
                chat_fn=self.chat_fn,
            )
        except CognitionFailure:
            logger.exception("representation request failed; processed cursor unchanged")
            return {"eligible": True, "skip_reason": "cognition_failure",
                    "conclusion_count": 0, "written": None, **evidence_summary}

        allowed = set(source_ids)
        valid = [c for c in conclusions
                 if len(set(c.premises)) >= 2 and set(c.premises) <= allowed
                 and set(c.premises) & selected_ids]
        if len(valid) != len(conclusions):
            logger.warning("representation rejected invalid/stale/unknown citations: %d",
                           len(conclusions) - len(valid))
        evidence_summary["parsed_conclusions"] = len(conclusions)
        evidence_summary["rejected_citations"] = len(conclusions) - len(valid)
        conclusions = valid

        # Review artifact — record what this tick concluded (the dry-run log
        # Vett + Aetheria inspect) BEFORE writeback, so it's captured whether
        # or not writes are live.
        self._record_dryrun(run_id=run_id, now=now, conclusions=conclusions)

        written = write_conclusions(
            self.lattice_store,
            conclusions,
            owner_agent=self.config.owner_agent,
            subject=self.config.subject,
            run_id=run_id,
            embed_fn=self.embed_fn,
            dry_run=self.config.dry_run,
            supersedes=None,  # P3 — not yet implemented
        )

        self._record_gate(run_id=run_id, now=now, conclusions=conclusions,
                          written=written)

        # Advance the last-run cursor ONLY on eligible ticks
        self._last_run_at = now

        logger.info(
            "representation tick %s done. conclusions=%d written=%s",
            run_id, len(conclusions), written,
        )

        return {
            "eligible": True,
            "skip_reason": None,
            "conclusion_count": len(conclusions),
            "written": written,
            **evidence_summary,
        }

    def _record_tick_summary(self, summary: dict, *, now: datetime) -> None:
        """Inspectable live outcome without logging conversation text."""
        try:
            path = Path(self.lattice_store.db_path).parent / "representation_last_tick.json"
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"ts": to_ny(now).isoformat(), **summary}, indent=2))
            tmp.replace(path)
        except Exception:
            logger.exception("representation last-tick status write failed")

    def _record_novelty_gate(self, *, now: datetime) -> dict | None:
        """LIVE novelty gate (Jon 2026-11-06): recompute per-day table, streak
        and pass/fail every tick; write status JSON next to the lattice and
        log one line. Measurement only, never blocks writes. Best-effort."""
        try:
            from soveryn.agents.representation import novelty_gate as ng
            db = Path(self.lattice_store.db_path)
            conv_db = getattr(self.conv_store, "db_path", None) or getattr(
                self.conv_store, "_db_path", None)
            if conv_db is None:
                return None
            res = ng.run_live(db, Path(conv_db), now=now)
            out = db.parent / "representation_novelty_gate_status.json"
            tmp = out.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(res, indent=2), encoding="utf-8")
            tmp.replace(out)
            logger.info("representation novelty gate: status=%s streak=%d/%d "
                        "through=%s", res["status"], res["streak"],
                        res["required"], res["evaluated_through"])
            return res
        except Exception:
            logger.exception("representation novelty gate evaluation failed")
            return None

    def _record_gate(self, *, run_id: str, now: datetime, conclusions: list,
                     written: dict) -> None:
        """Novelty-gate measurement (approved criterion 2026-11-05: 7 days,
        ≥80% novel writes). One JSONL line per tick, appended next to the
        lattice DB. Measurement ONLY — the gate never blocks writes; the
        verdict stays human. Best-effort — never crashes the tick."""
        try:
            gate_path = self.lattice_store.db_path.parent / "representation_gate.jsonl"
            gate_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps({
                "ts": now.isoformat(),
                "run_id": run_id,
                "dry_run": self.config.dry_run,
                "offered": len(conclusions),
                "written": written.get("written", 0),
                "skipped_exact": written.get("skipped_exact", 0),
                "skipped_near": written.get("skipped_near", 0),
            }, sort_keys=True)
            with gate_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            logger.exception("representation gate log append failed")

    def _record_dryrun(self, *, run_id: str, now: datetime, conclusions: list) -> None:
        """The dry-run review artifact for Vett/Aetheria: log each would-write
        conclusion at INFO, and (if a path is set) append one JSONL line per
        tick. Best-effort — never crashes the tick."""
        for c in conclusions:
            logger.info(
                "representation would-write [%s | %s] %s :: premises=%s",
                c.mode, c.confidence, c.content, list(c.premises),
            )
        if not self.dryrun_log_path or not conclusions:
            return
        try:
            record = {
                "ts": now.isoformat(),
                "run_id": run_id,
                "dry_run": self.config.dry_run,
                "subject": self.config.subject,
                "conclusions": [
                    {"mode": c.mode, "confidence": c.confidence,
                     "content": c.content, "premises": list(c.premises)}
                    for c in conclusions
                ],
            }
            self.dryrun_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.dryrun_log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception:
            logger.exception("representation: failed to append dry-run artifact")

    # ─── State queries (via injected stores) ────────────────────────────────

    def _count_new_turns_since(
        self, since: datetime | None, now: datetime
    ) -> int:
        """Count recent substantive turns across every agent, even first run."""
        return sum(since is None or t.timestamp > to_ny(since)
                   for t in recent_turns(self.conv_store, now=now))
