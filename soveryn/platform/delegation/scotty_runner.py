"""SOVERYN vNext — real Scotty runner for delegated execution.

scotty_run(worktree_path, objective, scope, *, max_seconds=600,
           max_tool_rounds=12) -> str

Builds a Scotty AgentLoop with all tools pinned to ``worktree_path`` (NOT the
live repo), runs ONE bounded-turn task directing Scotty to accomplish
``objective`` within ``scope``, enforces the wall-clock cap, and returns a
short summary string of what Scotty did.

Isolation
---------
ALL of Scotty's tools are pinned to ``worktree_path``:
  - read_file / list_directory: ``root=worktree`` (read-only inspection).
  - edit_file / git_status / git_diff / git_restore_file: ``root=worktree``
    (writes + git ops resolve under the worktree; paths escaping it are
    rejected by resolve_within_root).
  - run_command / run_pytest: ``root=worktree`` — cwd is the worktree AND
    PYTHONPATH=worktree, so any ``python``/``pytest`` invocation imports the
    worktree's code, not the editable-installed live tree.
There is no path by which a delegation run touches the live repo: the engine
creates the worktree, this runner pins every tool to it, and the human approve
gate is the only thing that merges the branch back.

Wall-clock cap
--------------
Enforced here because the engine (execute_task) does not enforce it:
``max_seconds`` is passed through as context but not measured by the engine.
The runner spawns process_message in a daemon thread and joins with timeout.
If the timeout fires, the thread is abandoned (Python has no hard thread kill)
and a TimeoutError summary string is returned — the engine will mark the task
failed via its exception guard.
"""
from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


def build_worktree_tool_registry(worktree: Path):
    """Build a ToolRegistry whose every Scotty tool is pinned to *worktree*.

    Extracted so the isolation wiring is testable without a live llama-server:
    all write/exec tools resolve paths, run subprocesses, and set PYTHONPATH
    against *worktree*, never SCOTTY_PROJECT_ROOT.
    """
    from soveryn.platform.tools.registry import ToolRegistry
    from soveryn.agents.scotty.tools import (
        build_read_file_tool,
        build_list_directory_tool,
        build_edit_file_tool,
        build_run_command_tool,
        build_git_status_tool,
        build_git_diff_tool,
        build_git_restore_file_tool,
        build_run_pytest_tool,
    )

    worktree = Path(worktree).resolve()
    registry = ToolRegistry()
    registry.register(build_read_file_tool(owner_agent="scotty", root=worktree))
    registry.register(build_list_directory_tool(owner_agent="scotty", root=worktree))
    registry.register(build_edit_file_tool(owner_agent="scotty", root=worktree))
    registry.register(
        build_run_command_tool(owner_agent="scotty", root=worktree, sandbox=True)
    )
    registry.register(build_git_status_tool(owner_agent="scotty", root=worktree))
    registry.register(build_git_diff_tool(owner_agent="scotty", root=worktree))
    registry.register(build_git_restore_file_tool(owner_agent="scotty", root=worktree))
    registry.register(
        build_run_pytest_tool(owner_agent="scotty", root=worktree, sandbox=True)
    )
    return registry


def scotty_run(
    worktree_path: str,
    objective: str,
    scope: str,
    *,
    max_seconds: int = 600,
    max_tool_rounds: int = 12,
) -> str:
    """Run Scotty's bounded execution loop for one delegated task.

    Builds a fresh Scotty AgentLoop, spins up a temporary conversation store,
    sends ONE turn directing Scotty to accomplish ``objective`` within ``scope``
    (all file operations constrained to ``worktree_path``), and returns a
    summary of what Scotty did.

    Parameters
    ----------
    worktree_path:
        Absolute path to the isolated git worktree. Scotty's read/write
        operations should be anchored here.
    objective:
        Clear description of the bounded implementation task Scotty must
        complete.
    scope:
        Hard boundary on what files/modules Scotty may touch. He should
        not touch anything outside this scope.
    max_seconds:
        Wall-clock cap for the entire turn (including all tool rounds).
        Default 600 (10 minutes). When exceeded, a timeout summary is
        returned.
    max_tool_rounds:
        Maximum number of tool-call rounds Scotty gets. Passed to AgentLoop.

    Returns
    -------
    str
        Short summary of what Scotty did, suitable for storing as task.summary.
        On timeout or error, returns an error description string.
    """
    worktree = Path(worktree_path).resolve()
    logger.info(
        "scotty_runner: starting for worktree=%s objective=%r scope=%r",
        worktree, objective[:80], scope[:80],
    )

    # ── Build isolated per-invocation infrastructure ─────────────────────────

    # Temporary DB for this Scotty run. Use a file-based DB (not :memory:) so
    # AgentLoop's session creation and turn save work normally. Auto-cleaned up
    # when the context exits. Each delegation run is stateless.
    with tempfile.TemporaryDirectory(prefix="scotty_run_") as tmp_dir:
        conv_db_path = Path(tmp_dir) / "conv.db"

        try:
            result_holder: list[str] = []
            error_holder: list[str] = []

            def _run() -> None:
                try:
                    from soveryn.memory.conversation_store import ConversationStore
                    from soveryn.agents.loop import AgentLoop

                    # Temporary conversation store for this isolated run
                    conv_store = ConversationStore(conv_db_path)

                    # Every Scotty tool pinned to the worktree — no live-repo path.
                    registry = build_worktree_tool_registry(worktree)

                    # Build AgentLoop. soul_text="" skips soul loading so we
                    # don't require the souls dir to exist. system_prompt=None
                    # loads the default Scotty persona.
                    loop = AgentLoop(
                        "scotty",
                        conv_store,
                        tool_registry=registry,
                        max_tool_rounds=max_tool_rounds,
                        soul_text="",  # skip soul for delegation runs
                    )

                    # Fresh session for this isolated delegation run
                    session_id = conv_store.new_session(
                        "scotty",
                        title=f"delegation: {objective[:60]}",
                    )

                    # Build the task directive for Scotty. Be explicit about scope,
                    # worktree path, and the fact that this is a bounded execution.
                    directive = (
                        f"You are executing a bounded delegation task.\n\n"
                        f"OBJECTIVE: {objective}\n\n"
                        f"SCOPE: {scope}\n"
                        f"You may ONLY touch files within the specified scope. "
                        f"Do not modify anything outside the scope.\n\n"
                        f"WORKING DIRECTORY: {worktree}\n"
                        f"All your file operations should target files under "
                        f"this worktree path.\n\n"
                        f"Complete the objective, then report briefly what you did. "
                        f"Be factual and concise — no preamble."
                    )

                    response = loop.process_message(session_id, directive)
                    result_holder.append(response.content or "Scotty completed the task (no summary).")

                except Exception as exc:
                    logger.exception(
                        "scotty_runner: error during execution (worktree=%s)", worktree
                    )
                    error_holder.append(str(exc))

            thread = threading.Thread(target=_run, daemon=True, name="scotty-delegation")
            thread.start()
            thread.join(timeout=max_seconds)

            if thread.is_alive():
                # Timeout: thread is abandoned (no hard kill in Python).
                # The engine's exception guard will catch the TimeoutError we raise.
                msg = (
                    f"Scotty's execution exceeded the {max_seconds}s wall-clock cap "
                    f"for objective: {objective[:80]!r}"
                )
                logger.warning("scotty_runner: %s", msg)
                raise TimeoutError(msg)

            if error_holder:
                # Re-raise so the engine marks the task failed
                raise RuntimeError(f"scotty_runner error: {error_holder[0]}")

            summary = result_holder[0] if result_holder else "Scotty completed (no content)."
            logger.info("scotty_runner: completed. summary=%r", summary[:120])
            return summary

        except (TimeoutError, RuntimeError):
            raise
        except Exception as exc:
            logger.exception("scotty_runner: unexpected error for worktree=%s", worktree)
            raise RuntimeError(f"scotty_runner unexpected error: {exc}") from exc
