"""Cron-that-remembers: last-output continuity, notepad, monitor hash, acked failures.

House-shaped Hermes steal: recurring automations load what they last said,
keep a per-job KV scratchpad, skip the LLM when a watch source is unchanged,
and stop re-pinging an error Jon already acked. JSON under data/automations/,
same root as schedule_state.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .registry import AutomationSpec

MAX_LAST_OUTPUT_CHARS = 8000
MAX_VALUE_BYTES = 16 * 1024
MAX_KEY_CHARS = 128
MAX_JOB_TOTAL_BYTES = 64 * 1024
MAX_DIFF_CHARS = 4000
MAX_MONITOR_OUTPUT_CHARS = 8000
MAX_ERROR_CHARS = 500
_MAX_SIGNATURE_ERROR_CHARS = 200
URL_TIMEOUT_SECONDS = 30
MAX_URL_BYTES = 262_144

CRON_HINT = (
    "You are running as a scheduled house automation. Your reply lands in "
    "the Command Center inbox — do not try to deliver it yourself. If there "
    "is genuinely nothing new versus the previous run, reply with exactly "
    "[SILENT] and nothing else.\n\n"
)

FetchFn = Callable[[str], Tuple[bool, str]]

_lock = threading.RLock()


def _data_root(data_root: Path | None = None) -> Path:
    if data_root is not None:
        return Path(data_root)
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    from soveryn.config.loader import DEFAULT_DATA_ROOT

    return Path(DEFAULT_DATA_ROOT)


def memory_path(data_root: Path | None = None) -> Path:
    return _data_root(data_root) / "automations" / "cron_memory.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(data_root: Path | None = None) -> Dict[str, Any]:
    path = memory_path(data_root)
    if not path.is_file():
        return {"jobs": {}, "incidents": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"jobs": {}, "incidents": {}}
    if not isinstance(raw, dict):
        return {"jobs": {}, "incidents": {}}
    jobs = raw.get("jobs") if isinstance(raw.get("jobs"), dict) else {}
    incidents = raw.get("incidents") if isinstance(raw.get("incidents"), dict) else {}
    return {"jobs": jobs, "incidents": incidents}


def _save(state: Dict[str, Any], *, data_root: Path | None = None) -> None:
    path = memory_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def _job(state: Dict[str, Any], automation_id: str) -> Dict[str, Any]:
    jobs = state.setdefault("jobs", {})
    entry = jobs.get(automation_id)
    if not isinstance(entry, dict):
        entry = {}
        jobs[automation_id] = entry
    return entry


# --- last output / continuity -------------------------------------------------


def save_last_output(
    automation_id: str,
    content: str,
    *,
    data_root: Path | None = None,
) -> None:
    text = str(content or "")
    with _lock:
        state = _load(data_root)
        job = _job(state, automation_id)
        job["last_output"] = _truncate(text, MAX_LAST_OUTPUT_CHARS)
        job["last_output_at"] = _now()
        _save(state, data_root=data_root)


def load_last_output(
    automation_id: str, *, data_root: Path | None = None
) -> str:
    with _lock:
        state = _load(data_root)
        job = state.get("jobs", {}).get(automation_id) or {}
        if not isinstance(job, dict):
            return ""
        return str(job.get("last_output") or "")


def _truncate(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + "\n\n[... output truncated ...]"


def render_continuity_section(
    automation_id: str, *, data_root: Path | None = None
) -> str:
    raw = load_last_output(automation_id, data_root=data_root).strip()
    if not raw:
        return ""
    shown = _truncate(raw, MAX_LAST_OUTPUT_CHARS)
    return (
        "## Your previous run's output\n"
        "The following is this job's most recent output from its previous "
        "run. Use it for continuity: avoid repeating what was already "
        "reported, and continue where the last run left off.\n\n"
        f"```\n{shown}\n```\n\n"
    )


# --- notepad ------------------------------------------------------------------


def set_note(
    automation_id: str,
    key: str,
    value: str,
    *,
    data_root: Path | None = None,
) -> Dict[str, Any]:
    automation_id, key, value = str(automation_id), str(key), str(value)
    if not automation_id:
        raise ValueError("automation_id must be non-empty")
    if not key:
        raise ValueError("key must be non-empty")
    if len(key) > MAX_KEY_CHARS:
        raise ValueError(f"key too long (max {MAX_KEY_CHARS} characters)")
    if len(value.encode("utf-8")) > MAX_VALUE_BYTES:
        raise ValueError(f"value too large (max {MAX_VALUE_BYTES} bytes per key)")
    with _lock:
        state = _load(data_root)
        job = _job(state, automation_id)
        pad = job.get("notepad")
        if not isinstance(pad, dict):
            pad = {}
        other = 0
        for k, entry in pad.items():
            if k == key:
                continue
            val = entry.get("value") if isinstance(entry, dict) else str(entry)
            other += len(str(k).encode("utf-8")) + len(str(val).encode("utf-8"))
        entry_bytes = len(key.encode("utf-8")) + len(value.encode("utf-8"))
        if other + entry_bytes > MAX_JOB_TOTAL_BYTES:
            raise ValueError(
                f"notepad full: job '{automation_id}' would exceed "
                f"{MAX_JOB_TOTAL_BYTES} bytes total; delete unused keys first"
            )
        now = _now()
        pad[key] = {"value": value, "updated_at": now}
        job["notepad"] = pad
        _save(state, data_root=data_root)
    return {
        "automation_id": automation_id,
        "key": key,
        "value": value,
        "updated_at": now,
    }


def get_note(
    automation_id: str, key: str, *, data_root: Path | None = None
) -> Optional[str]:
    with _lock:
        state = _load(data_root)
        job = state.get("jobs", {}).get(automation_id) or {}
        pad = job.get("notepad") if isinstance(job, dict) else None
        if not isinstance(pad, dict):
            return None
        entry = pad.get(key)
        if isinstance(entry, dict):
            return str(entry.get("value") or "")
        if entry is None:
            return None
        return str(entry)


def delete_note(
    automation_id: str, key: str, *, data_root: Path | None = None
) -> bool:
    with _lock:
        state = _load(data_root)
        job = _job(state, automation_id)
        pad = job.get("notepad")
        if not isinstance(pad, dict) or key not in pad:
            return False
        del pad[key]
        job["notepad"] = pad
        _save(state, data_root=data_root)
        return True


def list_notes(
    automation_id: str, *, data_root: Path | None = None
) -> List[Dict[str, Any]]:
    with _lock:
        state = _load(data_root)
        job = state.get("jobs", {}).get(automation_id) or {}
        pad = job.get("notepad") if isinstance(job, dict) else None
        if not isinstance(pad, dict):
            return []
        rows = []
        for key in sorted(pad):
            entry = pad[key]
            if isinstance(entry, dict):
                rows.append(
                    {
                        "automation_id": automation_id,
                        "key": key,
                        "value": str(entry.get("value") or ""),
                        "updated_at": entry.get("updated_at"),
                    }
                )
            else:
                rows.append(
                    {
                        "automation_id": automation_id,
                        "key": key,
                        "value": str(entry),
                        "updated_at": None,
                    }
                )
        return rows


def clear_notepad(automation_id: str, *, data_root: Path | None = None) -> int:
    with _lock:
        state = _load(data_root)
        job = _job(state, automation_id)
        pad = job.get("notepad")
        n = len(pad) if isinstance(pad, dict) else 0
        job["notepad"] = {}
        _save(state, data_root=data_root)
        return n


def render_notepad_section(
    automation_id: str, *, data_root: Path | None = None
) -> str:
    notes = list_notes(automation_id, data_root=data_root)
    if not notes:
        return ""
    lines = [f"- {note['key']}: {note['value']}" for note in notes]
    return (
        "## Job notepad (persistent across runs)\n"
        "This durable scratchpad survives between scheduled runs of this "
        "job. Update it with the cron_notepad tool "
        "(action=set|get|delete|list).\n\n" + "\n".join(lines) + "\n\n"
    )


# --- monitor ------------------------------------------------------------------


@dataclass
class MonitorOutcome:
    ok: bool
    changed: bool = False
    first_run: bool = False
    context_block: Optional[str] = None
    error: Optional[str] = None


def hash_monitor_output(output: str) -> str:
    return hashlib.sha256(output.encode("utf-8", errors="replace")).hexdigest()


def build_monitor_diff(old: str, new: str) -> str:
    import difflib

    diff = "\n".join(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile="previous",
            tofile="current",
            lineterm="",
        )
    )
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n... [diff truncated]"
    return diff


def _resolve_monitor_file(rel: str, data_root: Path) -> Path:
    raw = Path(rel)
    if raw.is_absolute():
        raise ValueError("monitor_file must be relative to data root")
    root = data_root.resolve()
    path = (root / raw).resolve()
    if path != root and root not in path.parents:
        raise ValueError("monitor_file escapes data root")
    return path


def _fetch_monitor_url(url: str) -> Tuple[bool, str]:
    import urllib.request

    if not str(url).lower().startswith(("http://", "https://")):
        return False, f"monitor_url must be http(s): {url!r}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "soveryn-automation-monitor"}
        )
        with urllib.request.urlopen(req, timeout=URL_TIMEOUT_SECONDS) as resp:
            body = resp.read(MAX_URL_BYTES + 1)
        if len(body) > MAX_URL_BYTES:
            body = body[:MAX_URL_BYTES]
        return True, body.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 — monitor must never raise
        return False, f"monitor_url fetch failed: {exc}"


def _read_monitor_source(
    spec: AutomationSpec,
    *,
    data_root: Path,
    fetch_fn: FetchFn | None = None,
) -> Tuple[bool, str]:
    file_rel = getattr(spec, "monitor_file", None)
    url = getattr(spec, "monitor_url", None)
    if file_rel:
        try:
            path = _resolve_monitor_file(str(file_rel), data_root)
        except ValueError as exc:
            return False, str(exc)
        if not path.is_file():
            return True, ""
        try:
            return True, path.read_text(encoding="utf-8")
        except OSError as exc:
            return False, f"monitor_file read failed: {exc}"
    if url:
        fn = fetch_fn or _fetch_monitor_url
        return fn(str(url))
    return False, "monitor job has neither monitor_file nor monitor_url"


def spec_has_monitor(spec: AutomationSpec) -> bool:
    return bool(
        (getattr(spec, "monitor_file", None) or "").strip()
        or (getattr(spec, "monitor_url", None) or "").strip()
    )


def check_monitor(
    spec: AutomationSpec,
    *,
    data_root: Path | None = None,
    fetch_fn: FetchFn | None = None,
) -> MonitorOutcome:
    """Hash the watch source. Unchanged → skip LLM. Source failure → error, hash kept."""
    root = _data_root(data_root)
    ok, output = _read_monitor_source(spec, data_root=root, fetch_fn=fetch_fn)
    if not ok:
        return MonitorOutcome(ok=False, error=output)

    new_hash = hash_monitor_output(output)
    with _lock:
        state = _load(root)
        job = _job(state, spec.id)
        mon = job.get("monitor") if isinstance(job.get("monitor"), dict) else {}
        last_hash = mon.get("last_output_hash")
        snapshot = str(mon.get("snapshot") or "")

        if last_hash is not None and new_hash == last_hash:
            return MonitorOutcome(ok=True, changed=False)

        first_run = last_hash is None
        # Empty first observation: persist baseline, do not spend an LLM turn.
        if first_run and not output.strip():
            job["monitor"] = {
                "last_output_hash": new_hash,
                "last_changed_at": _now(),
                "snapshot": output,
            }
            _save(state, data_root=root)
            return MonitorOutcome(ok=True, changed=False, first_run=True)

        shown = _truncate(output, MAX_MONITOR_OUTPUT_CHARS)
        if first_run:
            context_block = (
                "## Monitor Baseline (first run)\n\n"
                "This is the first observation of the monitored source — "
                "there is no previous output to diff against.\n\n"
                f"### Current output\n\n```\n{shown}\n```"
            )
        else:
            diff = build_monitor_diff(snapshot, output)
            context_block = (
                "## MONITOR CHANGE DETECTED\n\n"
                "The monitored source's output changed since the last run.\n\n"
                f"### Diff (previous → current)\n\n```diff\n{diff}\n```\n\n"
                f"### Current output\n\n```\n{shown}\n```"
            )
        job["monitor"] = {
            "last_output_hash": new_hash,
            "last_changed_at": _now(),
            "snapshot": output,
        }
        _save(state, data_root=root)
    return MonitorOutcome(
        ok=True,
        changed=True,
        first_run=first_run,
        context_block=context_block,
    )


# --- incidents / acked failures -----------------------------------------------


def _normalize_error(error: str) -> str:
    return re.sub(r"\s+", " ", str(error or "")).strip().lower()


def _error_signature(automation_id: str, error: str) -> str:
    normalized = _normalize_error(error)[:_MAX_SIGNATURE_ERROR_CHARS]
    digest = hashlib.sha256(
        automation_id.encode() + normalized.encode()
    ).hexdigest()
    return digest[:12]


def _incident_id(automation_id: str, error_sig: str) -> str:
    return f"{automation_id}_{error_sig}"


def upsert_incident(
    automation_id: str,
    error: str,
    *,
    data_root: Path | None = None,
) -> Tuple[str, bool]:
    sig = _error_signature(automation_id, error)
    iid = _incident_id(automation_id, sig)
    stored = str(error or "")[:MAX_ERROR_CHARS]
    now = _now()
    with _lock:
        state = _load(data_root)
        incidents = state.setdefault("incidents", {})
        existing = incidents.get(iid)
        if isinstance(existing, dict):
            existing["last_seen_at"] = now
            existing["error"] = stored
            incidents[iid] = existing
            _save(state, data_root=data_root)
            return iid, False
        incidents[iid] = {
            "id": iid,
            "automation_id": automation_id,
            "error_sig": sig,
            "state": "detected",
            "error": stored,
            "first_seen_at": now,
            "last_seen_at": now,
            "acked_at": None,
        }
        _save(state, data_root=data_root)
        return iid, True


def get_incident(
    incident_id: str, *, data_root: Path | None = None
) -> Optional[Dict[str, Any]]:
    with _lock:
        state = _load(data_root)
        rec = state.get("incidents", {}).get(incident_id)
        return dict(rec) if isinstance(rec, dict) else None


def ack_incident(incident_id: str, *, data_root: Path | None = None) -> bool:
    now = _now()
    with _lock:
        state = _load(data_root)
        rec = state.get("incidents", {}).get(incident_id)
        if not isinstance(rec, dict):
            return False
        if rec.get("state") == "closed":
            return True
        rec["state"] = "closed"
        rec["acked_at"] = now
        rec["closed_at"] = now
        state["incidents"][incident_id] = rec
        _save(state, data_root=data_root)
        return True


def mark_incident_alerted(
    incident_id: str, *, data_root: Path | None = None
) -> None:
    with _lock:
        state = _load(data_root)
        rec = state.get("incidents", {}).get(incident_id)
        if not isinstance(rec, dict) or rec.get("state") == "closed":
            return
        rec["state"] = "alerted"
        state["incidents"][incident_id] = rec
        _save(state, data_root=data_root)


def is_failure_acked(
    automation_id: str, error: str, *, data_root: Path | None = None
) -> bool:
    sig = _error_signature(automation_id, error)
    iid = _incident_id(automation_id, sig)
    rec = get_incident(iid, data_root=data_root)
    return bool(rec and rec.get("state") == "closed")


def list_incidents(
    *,
    automation_id: str | None = None,
    data_root: Path | None = None,
) -> List[Dict[str, Any]]:
    with _lock:
        state = _load(data_root)
        rows = []
        for rec in (state.get("incidents") or {}).values():
            if not isinstance(rec, dict):
                continue
            if automation_id and rec.get("automation_id") != automation_id:
                continue
            rows.append(dict(rec))
        rows.sort(key=lambda r: str(r.get("last_seen_at") or ""), reverse=True)
        return rows


# --- prompt assembly / run gate -----------------------------------------------


def is_silent(content: str) -> bool:
    return str(content or "").strip() == "[SILENT]"


def assemble_run_prompt(
    spec: AutomationSpec,
    *,
    data_root: Path | None = None,
    monitor_block: str | None = None,
) -> str:
    parts: List[str] = [CRON_HINT]
    if getattr(spec, "notepad", True):
        pad = render_notepad_section(spec.id, data_root=data_root)
        if pad:
            parts.append(pad)
    if getattr(spec, "remember", True):
        cont = render_continuity_section(spec.id, data_root=data_root)
        if cont:
            parts.append(cont)
    if monitor_block:
        parts.append(monitor_block.rstrip() + "\n\n")
    parts.append(spec.prompt)
    return "".join(parts)


@dataclass
class PrepareResult:
    skip: bool
    prompt: str
    reason: str | None = None
    error: str | None = None
    monitor_changed: bool = False


def prepare_run(
    spec: AutomationSpec, *, data_root: Path | None = None
) -> PrepareResult:
    monitor_block = None
    if spec_has_monitor(spec):
        outcome = check_monitor(spec, data_root=data_root)
        if not outcome.ok:
            return PrepareResult(
                skip=True,
                prompt="",
                reason="monitor_error",
                error=outcome.error,
            )
        if not outcome.changed:
            return PrepareResult(skip=True, prompt="", reason="no_change")
        monitor_block = outcome.context_block
        return PrepareResult(
            skip=False,
            prompt=assemble_run_prompt(
                spec, data_root=data_root, monitor_block=monitor_block
            ),
            monitor_changed=True,
        )
    return PrepareResult(
        skip=False,
        prompt=assemble_run_prompt(spec, data_root=data_root),
    )


def should_write_inbox(result: Dict[str, Any], *, data_root: Path | None = None) -> bool:
    """False for goldfish-skip, [SILENT], or an already-acked failure signature."""
    status = str(result.get("status") or "")
    if status in {"no_change", "disabled"}:
        return False
    if is_silent(str(result.get("content") or "")):
        return False
    if status not in {"ok", "would_send"}:
        err = str(result.get("message") or result.get("error") or "")
        aid = str(result.get("id") or "")
        if aid and err and is_failure_acked(aid, err, data_root=data_root):
            return False
    return True


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m soveryn.automations.memory",
        description="Cron memory: notepad + ack incidents.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("notepad", help="per-job KV scratchpad")
    n.add_argument("automation_id")
    n.add_argument("action", choices=["set", "get", "delete", "list"])
    n.add_argument("key", nargs="?")
    n.add_argument("value", nargs="?")

    a = sub.add_parser("ack", help="ack a failure incident (stop re-pinging)")
    a.add_argument("incident_id")

    sub.add_parser("incidents", help="list failure incidents")

    args = parser.parse_args(argv)
    if args.cmd == "notepad":
        if args.action == "list":
            for row in list_notes(args.automation_id):
                print(f"{row['key']}\t{row['value']}")
            return 0
        if not args.key:
            print("error: key required", flush=True)
            return 2
        if args.action == "get":
            val = get_note(args.automation_id, args.key)
            if val is None:
                return 1
            print(val)
            return 0
        if args.action == "delete":
            return 0 if delete_note(args.automation_id, args.key) else 1
        if args.value is None:
            print("error: value required for set", flush=True)
            return 2
        set_note(args.automation_id, args.key, args.value)
        return 0
    if args.cmd == "ack":
        ok = ack_incident(args.incident_id)
        print("acked" if ok else "not found")
        return 0 if ok else 1
    for rec in list_incidents():
        print(
            f"{rec['id']}\t{rec.get('state')}\t{rec.get('automation_id')}\t"
            f"{rec.get('error')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
