"""Mission Control ops: brain switch + pytest runs.

Durable job files under data/ops/ so a brain switch that restarts soveryn-vnext
does not lose status. Localhost-only enforcement lives in the route layer.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from soveryn.config.runtime import (
    MODEL_SERVERS,
    _VETT_BRAIN_PROFILES,
    resolve_vett_brain,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SWITCH_SCRIPT = REPO_ROOT / "scripts" / "switch_vett_brain.sh"
PYTHON = Path(os.environ.get("SOVERYN_PYTHON") or
              "/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python")

BRAINS = tuple(_VETT_BRAIN_PROFILES.keys())

TEST_SUITES: dict[str, dict[str, Any]] = {
    "smoke": {
        "label": "Smoke (routing + runtime)",
        "paths": [
            "tests/test_runtime_config.py",
            "tests/test_routing.py",
            "tests/test_turn_scope.py",
            "tests/test_public_agents_service.py",
        ],
    },
    "cognition": {
        "label": "Cognition",
        "paths": [
            "tests/test_cognition_runner_turns.py",
            "tests/test_cognition_reflect.py",
            "tests/test_cognition_cycle.py",
            "tests/test_app_api_cognition_routes.py",
        ],
    },
    "agent_loop": {
        "label": "Agent loop / tools",
        "paths": [
            "tests/test_agent_loop_tool_loop.py",
            "tests/test_agent_loop_stream_tools.py",
            "tests/test_verification_gate.py",
        ],
    },
    "keepsake": {
        "label": "TGTHRmess keepsake (external)",
        "cwd": str(Path.home() / "tgthrmess-app"),
        "paths": ["test_keepsake.py"],
        "external": True,
    },
}


def _ops_dir() -> Path:
    d = REPO_ROOT / "data" / "ops"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _job_path(kind: str) -> Path:
    return _ops_dir() / f"{kind}_job.json"


def _write_job(kind: str, payload: dict[str, Any]) -> None:
    path = _job_path(kind)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_job(kind: str) -> dict[str, Any] | None:
    path = _job_path(kind)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def brain_status() -> dict[str, Any]:
    key = resolve_vett_brain()
    prof = _VETT_BRAIN_PROFILES[key]
    vs = next(s for s in MODEL_SERVERS if s.name == "vett_scotty_shared")
    job = _read_job("brain")
    # Reconcile a job left "running" after a successful switch (vnext restarted).
    if job and job.get("status") in ("running", "starting"):
        wanted = job.get("brain")
        if wanted and wanted == key:
            age = time.time() - float(job.get("started_at") or 0)
            if age > 30:
                job = {
                    **job,
                    "status": "ok",
                    "finished_at": time.time(),
                    "message": f"Brain is {key} (switch completed; process restarted).",
                    "result_brain": key,
                }
                _write_job("brain", job)
        else:
            # Still switching or failed silently — leave status; UI polls log.
            pass
    return {
        "brain": key,
        "house_name": prof.get("house_name") or key,
        "alias": prof["alias"],
        "role": prof["role"],
        "blurb": prof.get("blurb") or "",
        "routed_alias": vs.model_alias,
        "base_url": vs.base_url,
        # One-at-a-time on Spark :8001 — peers are switchable, not concurrent.
        "note": (
            "Spark hard brains for Vett, Scotty, and public agents. "
            "Only one loaded at a time. Aetheria (soul) stays on Blackwell. "
            "Kernel defaults to GLM TP=2 on Sparks :8001; switch with "
            "scripts/switch_kernel_brain.sh glm|flash|qwen38 (Eve stays on Quadros Qwen)."
        ),
        "brains": [
            {
                "id": k,
                "house_name": p.get("house_name") or k,
                "alias": p["alias"],
                "role": p["role"],
                "blurb": p.get("blurb") or "",
            }
            for k, p in _VETT_BRAIN_PROFILES.items()
        ],
        "job": job,
    }


def start_brain_switch(brain: str) -> dict[str, Any]:
    brain = (brain or "").strip().lower()
    if brain not in BRAINS:
        return {"ok": False, "error": "bad_brain", "valid": list(BRAINS)}
    if not SWITCH_SCRIPT.is_file():
        return {"ok": False, "error": "missing_script", "path": str(SWITCH_SCRIPT)}

    existing = _read_job("brain")
    if existing and existing.get("status") in ("running", "starting"):
        # Stale lock: if the job is older than 20 min, allow a new one.
        age = time.time() - float(existing.get("started_at") or 0)
        if age < 1200:
            return {"ok": False, "error": "busy", "job": existing}

    job_id = uuid.uuid4().hex[:12]
    log_path = _ops_dir() / f"brain_{job_id}.log"
    status_path = _ops_dir() / f"brain_{job_id}.status"
    job = {
        "id": job_id,
        "kind": "brain",
        "brain": brain,
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "exit_code": None,
        "log_path": str(log_path),
        "status_path": str(status_path),
        "message": (
            f"Switching Spark brain to {brain}. "
            "vLLM reload can take several minutes; this page may briefly disconnect."
        ),
    }
    _write_job("brain", job)

    # Detached session: switch_vett_brain restarts soveryn-vnext, which would
    # kill a request-thread child. A new session group survives the restart.
    wrapper = f"""
set -euo pipefail
LOG={json.dumps(str(log_path))}
STATUS={json.dumps(str(status_path))}
JOB={json.dumps(str(_job_path("brain")))}
BRAIN={json.dumps(brain)}
SCRIPT={json.dumps(str(SWITCH_SCRIPT))}
{{
  echo "=== brain switch $BRAIN @ $(date -Iseconds) ==="
  bash "$SCRIPT" "$BRAIN"
  ec=$?
  echo "=== exit $ec @ $(date -Iseconds) ==="
  printf '%s' "$ec" > "$STATUS"
  python3 - <<'PY'
import json, time
from pathlib import Path
job_path = Path({json.dumps(str(_job_path("brain")))})
status_path = Path({json.dumps(str(status_path))})
log_path = Path({json.dumps(str(log_path))})
ec = int(status_path.read_text().strip() or "-1")
job = json.loads(job_path.read_text()) if job_path.is_file() else {{}}
job.update({{
  "status": "ok" if ec == 0 else "failed",
  "exit_code": ec,
  "finished_at": time.time(),
  "message": (
    f"Brain switch to {json.dumps(brain)[1:-1]} finished."
    if ec == 0 else
    f"Brain switch failed (exit {{ec}}). See log."
  ),
  "result_brain": open(Path.home()/".soveryn"/"vett_brain").read().strip()
    if (Path.home()/".soveryn"/"vett_brain").is_file() else {json.dumps(brain)},
}})
job_path.write_text(json.dumps(job, indent=2) + "\\n")
PY
}} >"$LOG" 2>&1
"""
    subprocess.Popen(
        ["bash", "-c", wrapper],
        cwd=str(REPO_ROOT),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "job": job}


def list_test_suites() -> list[dict[str, Any]]:
    return [
        {"id": k, "label": v["label"], "paths": v["paths"], "external": bool(v.get("external"))}
        for k, v in TEST_SUITES.items()
    ]


def start_tests(suite: str) -> dict[str, Any]:
    suite = (suite or "").strip().lower()
    if suite not in TEST_SUITES:
        return {"ok": False, "error": "bad_suite", "valid": list(TEST_SUITES)}

    existing = _read_job("tests")
    if existing and existing.get("status") in ("running", "starting"):
        return {"ok": False, "error": "busy", "job": existing}

    spec = TEST_SUITES[suite]
    job_id = uuid.uuid4().hex[:12]
    log_path = _ops_dir() / f"tests_{job_id}.log"
    cwd = Path(spec.get("cwd") or REPO_ROOT)
    job = {
        "id": job_id,
        "kind": "tests",
        "suite": suite,
        "label": spec["label"],
        "paths": list(spec["paths"]),
        "status": "starting",
        "started_at": time.time(),
        "finished_at": None,
        "exit_code": None,
        "log_path": str(log_path),
        "message": f"Running {spec['label']}…",
        "summary": None,
    }
    _write_job("tests", job)

    def _run() -> None:
        job["status"] = "running"
        _write_job("tests", job)
        cmd = [
            str(PYTHON), "-m", "pytest", "-q", "--tb=line",
            *spec["paths"],
        ]
        try:
            with open(log_path, "w", encoding="utf-8") as log:
                log.write(f"$ {' '.join(cmd)}\ncwd={cwd}\n\n")
                log.flush()
                proc = subprocess.run(
                    cmd,
                    cwd=str(cwd),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=600,
                )
            tail = ""
            try:
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                tail = "\n".join(lines[-12:])
            except OSError:
                pass
            job["exit_code"] = proc.returncode
            job["status"] = "ok" if proc.returncode == 0 else "failed"
            job["summary"] = tail
            job["message"] = (
                f"{spec['label']}: passed"
                if proc.returncode == 0
                else f"{spec['label']}: failed (exit {proc.returncode})"
            )
        except subprocess.TimeoutExpired:
            job["status"] = "failed"
            job["exit_code"] = -1
            job["message"] = f"{spec['label']}: timed out (10 min)"
        except Exception as e:
            job["status"] = "failed"
            job["exit_code"] = -1
            job["message"] = f"{type(e).__name__}: {e}"
        job["finished_at"] = time.time()
        _write_job("tests", job)

    threading.Thread(target=_run, name=f"tests-{suite}", daemon=True).start()
    return {"ok": True, "job": job}


def job_status(kind: str) -> dict[str, Any]:
    if kind not in ("brain", "tests"):
        return {"ok": False, "error": "bad_kind"}
    job = _read_job(kind)
    log_tail = ""
    if job and job.get("log_path"):
        try:
            lines = Path(job["log_path"]).read_text(encoding="utf-8", errors="replace").splitlines()
            log_tail = "\n".join(lines[-40:])
        except OSError:
            pass
    return {"ok": True, "job": job, "log_tail": log_tail}
