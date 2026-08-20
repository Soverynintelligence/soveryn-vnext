"""botdirectory.ai browse + local import (never scheduled)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from soveryn.platform.botdirectory.client import (
    BotDirectoryError,
    BotSummary,
    fetch_bot,
    search_bots,
)
from soveryn.platform.botdirectory.store import (
    get_import,
    import_charter,
    list_imports,
)
from soveryn.platform.botdirectory.tools import (
    build_browse_bot_directory_tool,
    build_get_imported_bot_charter_tool,
    build_import_bot_charter_tool,
    build_list_imported_bot_charters_tool,
)
from soveryn.platform.tools.registry import ToolRegistry


_SAMPLE = {
    "slug": "carousel-publisher",
    "name": "Carousel Publisher",
    "category": "Marketing",
    "integrations": ["PostNitro", "Instagram"],
    "prompt": "You are my social content publisher. Never post without approval.",
    "contributor": "postnitro",
    "detailUrl": "https://botdirectory.ai/bots/carousel-publisher/",
    "sourceUrl": "https://github.com/postnitro/postnitro-agent",
    "addedAt": "2026-08-20T09:00:00.000Z",
}


def _fake_get(payload: dict):
    def _inner(url: str, *, timeout: float = 20.0):
        return payload

    return _inner


def test_search_bots_returns_previews_not_full_prompt():
    with patch(
        "soveryn.platform.botdirectory.client._http_get",
        _fake_get({"bots": [_SAMPLE]}),
    ):
        out = search_bots(q="carousel", limit=5)
    assert out["ok"] is True
    assert out["count"] == 1
    bot = out["bots"][0]
    assert bot["slug"] == "carousel-publisher"
    assert "prompt" not in bot
    assert "prompt_preview" in bot
    assert "NEVER auto-scheduled" in out["note"]


def test_fetch_bot_exact_slug():
    with patch(
        "soveryn.platform.botdirectory.client._http_get",
        _fake_get({"bots": [_SAMPLE], "sync": {"hasMore": False}}),
    ):
        bot = fetch_bot("carousel-publisher")
    assert isinstance(bot, BotSummary)
    assert bot.slug == "carousel-publisher"
    assert "Never post" in bot.prompt


def test_fetch_bot_missing_raises():
    with patch(
        "soveryn.platform.botdirectory.client._http_get",
        _fake_get({"bots": [], "sync": {"hasMore": False}}),
    ):
        with pytest.raises(BotDirectoryError, match="no bot"):
            fetch_bot("does-not-exist-xyz")


def test_import_charter_writes_files_not_scheduled(tmp_path):
    bot = BotSummary(
        slug="carousel-publisher",
        name="Carousel Publisher",
        category="Marketing",
        integrations=("Instagram",),
        prompt="Draft only. Never post without Jon.",
        contributor="postnitro",
        detail_url="https://botdirectory.ai/bots/carousel-publisher/",
        source_url=None,
        added_at="2026-08-20T09:00:00.000Z",
    )
    imported = import_charter(bot, data_root=tmp_path, note="for Eve review")
    assert imported.scheduled is False
    md = tmp_path / "botdirectory" / "imports" / "carousel-publisher.md"
    js = tmp_path / "botdirectory" / "imports" / "carousel-publisher.json"
    assert md.is_file()
    assert js.is_file()
    text = md.read_text(encoding="utf-8")
    assert "scheduled: false" in text
    assert "Draft only" in text
    meta = json.loads(js.read_text(encoding="utf-8"))
    assert meta["scheduled"] is False
    assert meta["live"] is False
    listed = list_imports(data_root=tmp_path)
    assert listed[0]["slug"] == "carousel-publisher"
    loaded = get_import("carousel-publisher", data_root=tmp_path)
    assert loaded["ok"] is True
    assert "Draft only" in loaded["prompt"]
    assert loaded["scheduled"] is False


def test_tools_registered_for_eve(tmp_path):
    reg = ToolRegistry(active_agents=("eve",), audit_hook=lambda e: None)
    reg.register(build_browse_bot_directory_tool(owner_agent="eve"))
    reg.register(
        build_import_bot_charter_tool(owner_agent="eve", data_root=tmp_path)
    )
    reg.register(
        build_list_imported_bot_charters_tool(owner_agent="eve", data_root=tmp_path)
    )
    reg.register(
        build_get_imported_bot_charter_tool(owner_agent="eve", data_root=tmp_path)
    )
    names = {n for (_o, n) in reg._tools}
    assert names == {
        "browse_bot_directory",
        "import_bot_charter",
        "list_imported_bot_charters",
        "get_imported_bot_charter",
    }


def test_import_tool_end_to_end(tmp_path):
    reg = ToolRegistry(active_agents=("eve",), audit_hook=lambda e: None)
    tool = build_import_bot_charter_tool(owner_agent="eve", data_root=tmp_path)
    reg.register(tool)
    with patch(
        "soveryn.platform.botdirectory.tools.fetch_bot",
        return_value=BotSummary(
            slug="industry-intel-digest",
            name="Industry Intel Digest",
            category="Marketing",
            integrations=("TranscriptAPI",),
            prompt="Weekday digest. Never republish transcripts.",
            contributor="scheemunai",
            detail_url="https://botdirectory.ai/bots/industry-intel-digest/",
            source_url=None,
            added_at=None,
        ),
    ):
        result = reg.invoke("eve", "import_bot_charter", {"slug": "industry-intel-digest"})
    assert result["ok"] is True
    assert result["scheduled"] is False
    assert result["live"] is False
    assert (tmp_path / "botdirectory" / "imports" / "industry-intel-digest.md").is_file()
