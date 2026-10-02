"""Textual TUI for the SOVERYN console (imported by console.py).

Panels: KERNEL / ENDPOINTS / GPUs / SEATS + LOG + INPUT command bar.
Keys: q quit, r refresh now. Commands run under a 20s cap.
"""
from __future__ import annotations

import subprocess
import time

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Footer, Input, RichLog, Static

from console import (SEAT_UNITS, endpoints_text, read_brain,
                     read_profile_endpoint, snapshot)


class Panel(Static):
    def __init__(self, title: str, panel_id: str, text: str = "…"):
        super().__init__(text, id=panel_id)
        self.panel_title = title

    def on_mount(self):
        self.border_title = self.panel_title


class SoverynConsoleApp(App):
    TITLE = "SOVERYN CONSOLE"
    CSS = """
    Screen { background: #02080f; }
    Panel {
        border: round #00b7ff;
        background: #030d16;
        padding: 0 1;
        width: 1fr;
        height: auto;
        color: #9fd8e8;
    }
    #top, #mid { height: auto; }
    #log { height: 1fr; border: round #00b7ff; background: #030d16; }
    #cmd { dock: bottom; border: round #ffb000; background: #0a0a05; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Horizontal(Panel("KERNEL", "p-kernel"),
                         Panel("ENDPOINTS", "p-endpoints"), id="top")
        yield Horizontal(Panel("GPUs", "p-gpus"),
                         Panel("SEATS", "p-seats"), id="mid")
        yield RichLog(id="log", markup=True, highlight=False, wrap=True)
        yield Input(placeholder="command (soveryn …, kernel …, shell) — enter to run",
                    id="cmd")
        yield Footer()

    def on_mount(self):
        self.set_interval(5.0, self.refresh_panels)
        self.refresh_panels()
        self.query_one("#log", RichLog).write(
            "[bold #00b7ff]SOVERYN console online.[/] type a command, enter to run.")

    def action_refresh(self):
        self.refresh_panels()

    @work(thread=True, exclusive=True)
    def refresh_panels(self) -> None:
        brain = read_brain()
        gpu_rows = []
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,"
                 "utilization.gpu,temperature.gpu", "--format=csv,noheader"],
                text=True, timeout=5)
            gpu_rows = [l.strip() for l in out.strip().splitlines()]
        except Exception as e:
            gpu_rows = [f"nvidia-smi unavailable: {e}"]
        seats = []
        for u in SEAT_UNITS:
            try:
                st = subprocess.check_output(
                    ["systemctl", "--user", "is-active", f"{u}.service"],
                    text=True, timeout=3).strip()
            except Exception:
                st = "?"
            color = "green" if st == "active" else "red"
            seats.append(f"[{color}]{st:<10}[/] {u}")

        setit = lambda sel, txt: self.call_from_thread(self._set_panel, sel, txt)
        setit("#p-kernel", f"[bold #ffb000]{brain}[/]\n{read_profile_endpoint(brain)}")
        setit("#p-endpoints", endpoints_text())
        setit("#p-gpus", "\n".join(gpu_rows))
        setit("#p-seats", "\n".join(seats))

    def _set_panel(self, selector: str, content: str) -> None:
        try:
            self.query_one(selector).update(content)
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        event.value = ""
        if not cmd:
            return
        self.query_one("#log", RichLog).write(f"[bold #ffb000]$[/] {cmd}")
        self._run_command(cmd)

    @work(thread=True)
    def _run_command(self, cmd: str) -> None:
        try:
            t0 = time.time()
            res = subprocess.run(["bash", "-lc", cmd], text=True,
                                 capture_output=True, timeout=20)
            dt = time.time() - t0
            out = ((res.stdout or "") + (res.stderr or "")).rstrip() or "(no output)"
            self.call_from_thread(self._log_result, out, res.returncode, dt)
        except subprocess.TimeoutExpired:
            self.call_from_thread(self._log_result, "(timed out after 20s)", 124, 20.0)

    def _log_result(self, out: str, code: int, dt: float) -> None:
        log = self.query_one("#log", RichLog)
        log.write(out[:8000])
        color = "green" if code == 0 else "red"
        log.write(f"[{color}]exit {code} in {dt:.1f}s[/]")
