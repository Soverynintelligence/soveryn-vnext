"""Guards for the Pi 1.0.0 (pi100) launcher pin and generated CLI settings."""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "packages" / "soveryn-cli"
LAUNCHER = CLI / "bin" / "soveryn-pi100"
PKG_JSON = CLI / "package.json"
SETTINGS = REPO / "config" / "soveryn-cli" / "settings.json"


def test_pi100_launcher_exists_executable_and_matches_package_pin() -> None:
    assert LAUNCHER.is_file()
    assert LAUNCHER.stat().st_mode & stat.S_IXUSR
    text = LAUNCHER.read_text(encoding="utf-8")
    pkg = json.loads(PKG_JSON.read_text(encoding="utf-8"))
    assert re.search(r'^PI_PIN_VERSION="1\.0\.0"$', text, re.M)
    node = pkg["soverynPi"]["node"]
    assert re.search(rf'^NODE_PIN_VERSION="{re.escape(node)}"$', text, re.M)


def test_package_json_bin_soveryn_is_pi100_and_rollbacks_stay_pinned() -> None:
    pkg = json.loads(PKG_JSON.read_text(encoding="utf-8"))
    assert pkg["bin"]["soveryn"] == "./bin/soveryn-pi100"
    assert pkg["bin"]["soveryn-pi099"] == "./bin/soveryn-pi099"
    assert pkg["bin"]["soveryn-pi087"] == "./bin/soveryn-pi087"
    assert pkg["bin"]["soveryn-074"] == "./bin/soveryn"

    pi099 = CLI / "bin" / "soveryn-pi099"
    pi087 = CLI / "bin" / "soveryn-pi087"
    assert pi099.is_file()
    assert pi087.is_file()
    assert re.search(r'^PI_PIN_VERSION="0\.99\.1"$', pi099.read_text(encoding="utf-8"), re.M)
    assert re.search(r'^PI_PIN_VERSION="0\.87\.1"$', pi087.read_text(encoding="utf-8"), re.M)


def test_soveryn_cli_settings_tui_regular_extensions_and_no_home_paths() -> None:
    raw = SETTINGS.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["tuiMode"] == "regular"
    assert data["extensions"] == ["-builtin:mcp"]
    assert "/home" not in raw
