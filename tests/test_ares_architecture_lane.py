"""Pure-input tests for Ares architecture lane invariants."""

from pathlib import Path

from soveryn.agents.ares.findings import Severity
from soveryn.agents.ares.lanes.architecture import (
    RETIRED_AGENTS,
    check_no_raw_io_in_agents,
    check_no_retired_agent_packages,
    check_tool_ownership_intact,
)


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


def test_raw_io_in_ares_infrastructure_is_exempt():
    """Ares lanes use sqlite3 on purpose — not cognition-path debt."""
    findings = check_no_raw_io_in_agents({
        Path("soveryn/agents/ares/lanes/observability.py"): "import sqlite3\n",
        Path("soveryn/agents/dream/writeback.py"): "import sqlite3\n",
        Path("soveryn/agents/presence/x_client.py"): "import requests\n",
        Path("soveryn/agents/heartbeat/daemon.py"): "import sqlite3\n",
    })
    assert findings == []


def test_raw_io_in_agent_cognition_path_still_flagged():
    findings = check_no_raw_io_in_agents({
        Path("soveryn/agents/aetheria/loop_helpers.py"): "import sqlite3\n",
    })
    assert len(findings) == 1


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


def test_no_retired_packages_emits_no_finding():
    findings = check_no_retired_agent_packages(
        present_packages=frozenset({"aetheria", "vett", "scotty", "ares"})
    )
    assert findings == []


def test_retired_package_present_is_warning():
    findings = check_no_retired_agent_packages(
        present_packages=frozenset({"aetheria", "tinker"})
    )
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.WARNING
    assert f.finding_type == "architecture.retired_agent_present"
    assert f.evidence["agent"] == "tinker"


def test_retired_agents_list_matches_design():
    assert RETIRED_AGENTS == frozenset({"scout", "vision", "tinker", "aetheria_public"})


def test_tool_ownership_clean_emits_no_finding():
    owners = {"persistent_memory": "aetheria", "browser_fetch": "vett"}
    active = frozenset({"aetheria", "vett", "scotty", "ares"})
    findings = check_tool_ownership_intact(tool_owners=owners, active_agents=active)
    assert findings == []


def test_tool_owned_by_retired_agent_is_warning():
    owners = {"scrape_dealers": "scout", "persistent_memory": "aetheria"}
    active = frozenset({"aetheria", "vett", "scotty", "ares"})
    findings = check_tool_ownership_intact(tool_owners=owners, active_agents=active)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.WARNING
    assert f.finding_type == "architecture.tool_owned_by_inactive_agent"
    assert f.evidence["tool"] == "scrape_dealers"
    assert f.evidence["owner"] == "scout"


def test_collect_architecture_live_against_synthetic_root(monkeypatch, tmp_path):
    agents_dir = tmp_path / "soveryn" / "agents"
    fake_agent = agents_dir / "fakeagent"
    fake_agent.mkdir(parents=True)
    (fake_agent / "__init__.py").write_text("", encoding="utf-8")
    (fake_agent / "bad.py").write_text("import sqlite3\n", encoding="utf-8")
    tinker = agents_dir / "tinker"
    tinker.mkdir()
    (tinker / "__init__.py").write_text("", encoding="utf-8")

    monkeypatch.setenv("SOVERYN_VNEXT_ROOT", str(tmp_path))
    import soveryn.agents.ares.lanes.architecture as arch

    findings = arch.collect_architecture_live()
    types = {f.finding_type for f in findings}
    assert "architecture.raw_io_in_agents" in types
    assert "architecture.retired_agent_present" in types
    assert "architecture.tool_owned_by_inactive_agent" not in types
