"""Shared pytest fixtures for the SOVERYN vNext test suite."""
import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture(autouse=True)
def _isolate_acttruth_and_skills(tmp_path, monkeypatch):
    """AgentLoop unit tests must not ingest the live house ActTruth ledger
    or on-disk skill index — that leaked extra system messages and made
    prelude-count assertions fail outside this machine."""
    iso = tmp_path / ".acttruth-test"
    monkeypatch.setenv("ACTTRUTH_DIR", str(iso))
    from soveryn.platform.acttruth.hooks import reset_acttruth_cache
    from soveryn.platform.acttruth.paths import set_default_root

    set_default_root(iso)
    reset_acttruth_cache()
    from soveryn.agents.skills import get_skill_index as _real_index

    def _index(agent, skills_dir=None):
        if skills_dir is None:
            return ""
        return _real_index(agent, skills_dir=skills_dir)

    monkeypatch.setattr("soveryn.agents.loop.get_skill_index", _index)
    monkeypatch.setattr("soveryn.agents.skills.get_skill_index", _index)


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})


@pytest.fixture
def app_state(tmp_path, fake_chat):
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return app.test_client()
