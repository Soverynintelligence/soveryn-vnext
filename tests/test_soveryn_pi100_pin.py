"""Guards for the current Pi launcher pin (pi110 as of 2026-10-08) and generated CLI settings."""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "packages" / "soveryn-cli"
LAUNCHER = CLI / "bin" / "soveryn-pi110"
PKG_JSON = CLI / "package.json"
SETTINGS = REPO / "config" / "soveryn-cli" / "settings.json"


def test_pi110_launcher_exists_executable_and_matches_package_pin() -> None:
    assert LAUNCHER.is_file()
    assert LAUNCHER.stat().st_mode & stat.S_IXUSR
    text = LAUNCHER.read_text(encoding="utf-8")
    pkg = json.loads(PKG_JSON.read_text(encoding="utf-8"))
    assert re.search(r'^PI_PIN_VERSION="1\.1\.0"$', text, re.M)
    node = pkg["soverynPi"]["node"]
    assert re.search(rf'^NODE_PIN_VERSION="{re.escape(node)}"$', text, re.M)


def test_package_json_bin_soveryn_is_pi110_and_rollbacks_stay_pinned() -> None:
    pkg = json.loads(PKG_JSON.read_text(encoding="utf-8"))
    assert pkg["bin"]["soveryn"] == "./bin/soveryn-pi110"
    assert pkg["bin"]["soveryn-pi104"] == "./bin/soveryn-pi104"
    assert pkg["bin"]["soveryn-pi103"] == "./bin/soveryn-pi103"
    assert pkg["bin"]["soveryn-pi100"] == "./bin/soveryn-pi100"
    assert pkg["bin"]["soveryn-pi099"] == "./bin/soveryn-pi099"
    assert pkg["bin"]["soveryn-pi087"] == "./bin/soveryn-pi087"
    assert pkg["bin"]["soveryn-074"] == "./bin/soveryn"

    pi104 = CLI / "bin" / "soveryn-pi104"
    pi103 = CLI / "bin" / "soveryn-pi103"
    pi100 = CLI / "bin" / "soveryn-pi100"
    pi099 = CLI / "bin" / "soveryn-pi099"
    pi087 = CLI / "bin" / "soveryn-pi087"
    assert pi104.is_file()
    assert pi103.is_file()
    assert pi100.is_file()
    assert pi099.is_file()
    assert pi087.is_file()
    assert re.search(r'^PI_PIN_VERSION="1\.0\.4"$', pi104.read_text(encoding="utf-8"), re.M)
    assert re.search(r'^PI_PIN_VERSION="1\.0\.3"$', pi103.read_text(encoding="utf-8"), re.M)
    assert re.search(r'^PI_PIN_VERSION="1\.0\.0"$', pi100.read_text(encoding="utf-8"), re.M)
    assert re.search(r'^PI_PIN_VERSION="0\.99\.1"$', pi099.read_text(encoding="utf-8"), re.M)
    assert re.search(r'^PI_PIN_VERSION="0\.87\.1"$', pi087.read_text(encoding="utf-8"), re.M)


def test_soveryn_cli_settings_tui_regular_extensions_and_no_home_paths() -> None:
    raw = SETTINGS.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["tuiMode"] == "regular"
    assert data["extensions"] == ["-builtin:mcp"]
    assert "/home" not in raw
