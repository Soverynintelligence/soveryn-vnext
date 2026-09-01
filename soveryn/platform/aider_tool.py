"""Kernel's default write harness — headless Aider on GLM.

Surgical diffs. OpenCode stays as ``run_opencode`` for short ``--auto``
one-shots. Same house fence as opencode_tool.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.platform.opencode_tool import (
    MAX_OUTPUT_CHARS,
    MAX_PROMPT_CHARS,
    _timeout_s,
    resolve_repo,
)
from soveryn.platform.tools.registry import ToolArgError, ToolSpec

LAUNCHER_NAMES = ("soveryn-aider",)


def find_aider() -> str | None:
    env = os.environ.get("SOVERYN_AIDER_BIN")
    if env and Path(env).is_file() and os.access(env, os.X_OK):
        return env
    for name in LAUNCHER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    script = Path.home() / "soveryn_vnext" / "scripts" / "soveryn-aider"
    if script.is_file() and os.access(script, os.X_OK):
        return str(script)
    return None


def run_aider(
    prompt: str,
    *,
    repo: Path,
    launcher: str,
    timeout_s: int,
    files: tuple[str, ...] = (),
    runner=subprocess.run,
) -> dict[str, Any]:
    cmd = [
        launcher,
        "--kernel",
        "--yes-always",
        "--no-pretty",
        "--no-show-model-warnings",
        "--no-browser",
        "--no-detect-urls",
        "--no-auto-lint",
        "--no-auto-test",
        "--map-tokens",
        "0",
        "--message",
        prompt,
    ]
    cmd.extend(files)
    env = os.environ.copy()
    env.setdefault("OPENAI_API_KEY", "local")
    env["AIDER_SHOW_MODEL_WARNINGS"] = "false"
    env["AIDER_DETECT_URLS"] = "false"
    env["AIDER_YES_ALWAYS"] = "true"
    try:
        proc = runner(
            cmd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_s,
            cwd=str(repo),
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        return {
            "ok": False,
            "error": f"aider timed out after {timeout_s}s",
            "output": out[-MAX_OUTPUT_CHARS:],
            "repo": str(repo),
        }
    except OSError as exc:
        return {"ok": False, "error": f"aider failed to start: {exc}", "repo": str(repo)}
    blob = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "output": blob[-MAX_OUTPUT_CHARS:],
        "repo": str(repo),
    }


def build_run_aider_tool(*, owner_agent: str = "kernel") -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ToolArgError("prompt must be a non-empty string")
        text = prompt.strip()
        if len(text) > MAX_PROMPT_CHARS:
            raise ToolArgError(f"prompt exceeds {MAX_PROMPT_CHARS} characters")
        repo_raw = args.get("repo")
        if repo_raw is not None and not isinstance(repo_raw, str):
            raise ToolArgError("repo must be a string path")
        files_raw = args.get("files")
        files: tuple[str, ...] = ()
        if files_raw is not None:
            if not isinstance(files_raw, list) or not all(
                isinstance(f, str) and f.strip() for f in files_raw
            ):
                raise ToolArgError("files must be a list of path strings")
            files = tuple(f.strip() for f in files_raw)
        repo = resolve_repo(repo_raw)
        launcher = find_aider()
        if launcher is None:
            return {
                "ok": False,
                "error": "soveryn-aider not found on PATH",
                "repo": str(repo),
            }
        return run_aider(
            text,
            repo=repo,
            launcher=launcher,
            timeout_s=_timeout_s(),
            files=files,
        )

    return ToolSpec(
        name="run_aider",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "The mend. Name files and the change. Aider applies "
                        "diffs on GLM :8001 — not a whole-file rewrite."
                    ),
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional paths to edit, relative to repo.",
                },
                "repo": {
                    "type": "string",
                    "description": (
                        "Working tree. Default ~/soveryn_vnext. House repos only."
                    ),
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Default Kernel write path: soveryn-aider --kernel --yes on GLM "
            ":8001. Surgical diffs. Prefer this over run_opencode. Use "
            "run_opencode only for a short bounded --auto one-shot."
        ),
    )
