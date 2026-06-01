"""SOVERYN status CLI — `python -m soveryn.status`.

Thin printer over the existing `soveryn.app.preflight.run_preflight()`.
Reuses `PreflightReport.format_text()` — no parallel formatting logic.
Exit 0 if the report is ok, exit 1 otherwise.
"""

from __future__ import annotations

import sys
from typing import Callable


def main(
    argv: list[str] | None = None,
    *,
    run_preflight: Callable[[], object] | None = None,
) -> int:
    if run_preflight is None:
        from soveryn.app.preflight import run_preflight as default_run_preflight
        run_preflight = default_run_preflight
    report = run_preflight()
    print(report.format_text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
