"""CLI: python -m soveryn.platform.acttruth → portable acttruth CLI."""
from __future__ import annotations

import sys

from acttruth.cli import main

if __name__ == "__main__":
    sys.exit(main())
