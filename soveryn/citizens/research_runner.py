"""Multi-wave research runner — OpenCode-class persistence for Vett-style digs.

One AgentLoop turn with a flat tool budget dies as "exhaustion." This runner
executes N waves, checkpoints findings to the objective desk folder, and can
resume after restart.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

from soveryn.citizens import objectives as objectives_mod
from soveryn.citizens.registry import connect

logger = logging.getLogger(__name__)

RESEARCH_MARKER = "[RESEARCH_OBJECTIVE "
DEFAULT_MAX_WAVES = 6
DEFAULT_ROUNDS_PER_WAVE = 10

WaveProcessFn = Callable[[str, str], str]
# (citizen_id, wave_prompt) -> model text for this wave


def parse_objective_id(body: str) -> str | None:
    text = (body or "").lstrip()
    if not text.startswith(RESEARCH_MARKER):
        return None
    m = re.match(r"\[RESEARCH_OBJECTIVE ([0-9a-fA-F-]{36})\]", text)
    return m.group(1) if m else None


def _wave_prompt(
    *,
    objective: dict[str, Any],
    checkpoint: dict[str, Any],
    wave: int,
    max_waves: int,
) -> str:
    findings = checkpoint.get("findings") or []
    prior = ""
    if findings:
        lines = []
        for f in findings[-20:]:
            if isinstance(f, dict):
                lines.append(
                    f"- {f.get('brand','?')} | {f.get('model','?')} | "
                    f"{f.get('price','?')} | {f.get('source','?')}"
                )
            else:
                lines.append(f"- {f}")
        prior = "Findings so far:\n" + "\n".join(lines) + "\n\n"

    return (
        f"[RESEARCH WAVE {wave + 1}/{max_waves} · objective {objective['id'][:8]}]\n"
        f"Desk: {objective['desk']} · Title: {objective['title']}\n"
        f"Success: {objective.get('success_criteria') or 'sourced table or honest gap'}\n\n"
        f"{objective['brief']}\n\n"
        f"{prior}"
        "PondWright bar for this wave:\n"
        "- **House first:** pick `apex_catalog_search` OR `akt_catalog_search` "
        "(separate catalogs), plus `pondwright_pricing_book` for rates.\n"
        "- Extract Brand | Model/MPN | Coverage | Price | Source "
        "(Apex catalog / rate book / URL only if web fallback).\n"
        "- Customer retail = MAP else MSRP. Never publish wholesale.\n"
        "- Web only if the house book cannot answer. Cite-or-stop.\n"
        "- End with a short WAVE_SUMMARY listing new rows added or why none.\n"
    )


def _extract_table_rows(text: str) -> list[dict[str, str]]:
    """Best-effort parse of markdown table rows from model output."""
    rows: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("|") or line.count("|") < 4:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or cells[0].lower() in ("brand", "---", ":---", ":---:"):
            continue
        if set(cells[0]) <= {"-", ":"}:
            continue
        while len(cells) < 5:
            cells.append("")
        rows.append({
            "brand": cells[0],
            "model": cells[1],
            "coverage": cells[2],
            "price": cells[3],
            "source": cells[4],
        })
    return rows


def run_research_objective(
    *,
    db_path: str | Path,
    citizen_id: str,
    body: str,
    commission_id: str,
    wave_fn: WaveProcessFn,
    max_waves: int = DEFAULT_MAX_WAVES,
) -> str:
    """Execute remaining waves for a RESEARCH_OBJECTIVE commission body."""
    oid = parse_objective_id(body)
    if not oid:
        raise ValueError("not a RESEARCH_OBJECTIVE body")

    with connect(db_path) as conn:
        objective = objectives_mod.get(conn, oid)
        if objective is None:
            raise KeyError(f"objective {oid} not found")
        path = objective.get("checkpoint_path") or ""
        checkpoint = objectives_mod.load_checkpoint(path)
        start_wave = int(checkpoint.get("wave") or 0)

        for wave in range(start_wave, max_waves):
            prompt = _wave_prompt(
                objective=objective,
                checkpoint=checkpoint,
                wave=wave,
                max_waves=max_waves,
            )
            logger.info(
                "research objective %s wave %s/%s (commission %s)",
                oid[:8],
                wave + 1,
                max_waves,
                commission_id[:8],
            )
            try:
                text = wave_fn(citizen_id, prompt)
            except Exception:
                logger.exception("research wave %s failed for %s", wave, oid)
                objectives_mod.set_state(
                    conn, oid, state="blocked", at=_now()
                )
                raise

            rows = _extract_table_rows(text or "")
            for row in rows:
                objectives_mod.append_finding(path, {**row, "wave": wave + 1})
            checkpoint = objectives_mod.load_checkpoint(path)
            waves_done = list(checkpoint.get("waves_done") or [])
            waves_done.append({
                "wave": wave + 1,
                "rows_added": len(rows),
                "summary": (text or "")[:800],
            })
            checkpoint["wave"] = wave + 1
            checkpoint["waves_done"] = waves_done
            notes = list(checkpoint.get("notes") or [])
            notes.append(f"wave {wave + 1}: +{len(rows)} rows")
            checkpoint["notes"] = notes[-40:]
            objectives_mod.save_checkpoint(path, checkpoint)

            # Early stop if we have a usable table
            findings = checkpoint.get("findings") or []
            priced = [
                f for f in findings
                if isinstance(f, dict) and f.get("price") and "$" in str(f.get("price"))
            ]
            # CWG house catalogs: accept Apex/AKT/rate-book sources without "$"
            # if the price cell is numeric-looking.
            house_priced = [
                f for f in findings
                if isinstance(f, dict)
                and f.get("price")
                and (
                    "$" in str(f.get("price"))
                    or any(
                        s in str(f.get("source", "")).lower()
                        for s in ("apex", "akt", "rate book", "pondwright")
                    )
                )
            ]
            enough = len(priced) >= 3 or (
                (objective.get("desk") or "").lower() == "cwg" and len(house_priced) >= 3
            )
            if enough:
                objectives_mod.set_state(
                    conn, oid, state="ready_for_verify", at=_now()
                )
                break
        else:
            # Completed all waves — ready for CoS either way
            objectives_mod.set_state(
                conn, oid, state="ready_for_verify", at=_now()
            )
            checkpoint = objectives_mod.load_checkpoint(path)

        findings = checkpoint.get("findings") or []
        priced = [
            f for f in findings
            if isinstance(f, dict) and f.get("price") and "$" in str(f.get("price"))
        ]
        lines = [
            f"# Research objective result · {objective['title']}",
            f"OBJECTIVE_ID: {oid}",
            "STATE: ready_for_verify",
            f"desk={objective['desk']} owner={citizen_id} waves={checkpoint.get('wave')}",
            f"success: {objective.get('success_criteria') or '(not specified)'}",
            "",
            "CoS: put the priced brief (with $) into Jon's DM now. "
            f"Do NOT call objective_verify until Jon accepts/rejects. "
            f"objective_id={oid}.",
            "",
            "| Brand | Model | Coverage | Price | Source |",
            "|---|---|---|---|---|",
        ]
        for f in findings:
            if not isinstance(f, dict):
                continue
            lines.append(
                f"| {f.get('brand','')} | {f.get('model','')} | "
                f"{f.get('coverage','')} | {f.get('price','')} | "
                f"{f.get('source','')} |"
            )
        if not priced:
            lines.append("")
            lines.append(
                "**Honest gap:** no sourced dollar rows. Web catalogs do not "
                "publish service/maintenance plan pricing for the targets "
                "searched. Prefer house pricing (PondWright estimator / CRM) "
                "or local contractor calls over more web waves."
            )
            # Keep the last wave only — Cos summarizes; don't dump the trail.
            last = (checkpoint.get("waves_done") or [])[-1:]
            for w in last:
                lines.append(
                    f"\n## Last wave ({w.get('wave')}) trail\n"
                    f"{(w.get('summary') or '')[:1200]}\n"
                )
        else:
            lines.append("")
            lines.append(
                f"**{len(priced)} sourced price row(s)** ready for Jon to verify."
            )

        text = "\n".join(lines)
        try:
            root = Path(path)
            root.mkdir(parents=True, exist_ok=True)
            (root / "result.md").write_text(text + "\n", encoding="utf-8")
        except OSError:
            logger.exception("could not write result.md for objective %s", oid)
        return text


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
