"""`python -m soveryn.platform.medic` — one medic tick (systemd oneshot)."""
from __future__ import annotations

import json

from soveryn.platform.medic.medic import run_once


def main() -> None:
    print(json.dumps(run_once()))


if __name__ == "__main__":
    main()
