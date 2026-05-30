"""Pure-input tests for Ares architecture lane invariants."""

from pathlib import Path

from soveryn.agents.ares.findings import Severity
from soveryn.agents.ares.lanes.architecture import check_no_raw_io_in_agents


def test_clean_agent_module_emits_no_finding():
    sources = {
        Path("soveryn/agents/aetheria/persona.py"): (
            "from soveryn.platform.inference.llama_server_client import chat\n"
            "PERSONA = 'You are Aetheria.'\n"
        ),
    }
    findings = check_no_raw_io_in_agents(sources)
    assert findings == []


def test_raw_sqlite_in_agent_is_warning():
    sources = {
        Path("soveryn/agents/aetheria/badmod.py"): (
            "import sqlite3\n"
            "conn = sqlite3.connect('foo.db')\n"
        ),
    }
    findings = check_no_raw_io_in_agents(sources)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.WARNING
    assert f.finding_type == "architecture.raw_io_in_agents"
    assert "sqlite3" in f.evidence["module"]
    assert "soveryn/agents/aetheria/badmod.py" in f.evidence["path"]


def test_raw_requests_in_agent_is_warning():
    findings = check_no_raw_io_in_agents({
        Path("soveryn/agents/vett/scrape.py"): "import requests\n",
    })
    assert len(findings) == 1
    assert "requests" in findings[0].evidence["module"]


def test_raw_urllib_in_agent_is_warning():
    findings = check_no_raw_io_in_agents({
        Path("soveryn/agents/scotty/fetcher.py"): "from urllib.request import urlopen\n",
    })
    assert len(findings) == 1
    assert "urllib.request" in findings[0].evidence["module"]


def test_multi_import_flags_only_forbidden_module():
    findings = check_no_raw_io_in_agents({
        Path("soveryn/agents/aetheria/multi.py"): "import os, sqlite3\n",
    })
    assert len(findings) == 1
    assert findings[0].evidence["module"] == "sqlite3"


def test_raw_io_in_platform_is_ignored():
    sources = {
        Path("soveryn/platform/inference/llama_server_client.py"): (
            "import urllib.request\n"
            "import sqlite3\n"
        ),
    }
    findings = check_no_raw_io_in_agents(sources)
    assert findings == []


def test_syntax_error_source_is_skipped_not_crashed():
    findings = check_no_raw_io_in_agents({
        Path("soveryn/agents/aetheria/broken.py"): "if True print('bad')\n",
    })
    assert findings == []


def test_finding_id_includes_path_so_multiple_violations_distinct():
    findings = check_no_raw_io_in_agents({
        Path("soveryn/agents/a/x.py"): "import sqlite3\n",
        Path("soveryn/agents/b/y.py"): "import sqlite3\n",
    })
    assert len({f.id for f in findings}) == 2
