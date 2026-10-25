"""Dispatch returns a ledger id only after the row is committed.

Pulse/ops/Kernel have reported Forge handoffs as sent (1f1f049d, 55f62f34)
that never appeared in data/delegation.db. These tests pin the contract:
a successful dispatch is readable; a write failure raises and is never
claimed sent; a duplicate live objective is idempotent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.citizens.registry import Citizen, connect, register
from soveryn.platform.delegation.dispatch import (
    DispatchError,
    DispatchResult,
    as_probe_records,
    dispatch,
    dispatch_forge_handoff,
    format_dispatch_error_block,
    is_forge_assignee,
    recent_dispatch_probes,
)
from soveryn.platform.delegation.store import DelegationStore, LedgerWriteError
from soveryn.platform.delegation.tools import build_dispatch_task_tool
from soveryn.platform.house_post_tools import register_house_post_tools
from soveryn.platform.tools.registry import ToolRegistry


def _store(tmp_path: Path) -> DelegationStore:
    return DelegationStore(tmp_path / "delegation.db")


def _args(**extra):
    base = dict(
        dispatched_by="aetheria",
        objective="Add a medic retired-units regression test.",
        scope="tests/test_medic.py",
        acceptance="python -m pytest tests/test_medic.py -q",
    )
    base.update(extra)
    return base


def test_successful_dispatch_yields_readable_row(tmp_path):
    store = _store(tmp_path)
    result = dispatch(store, **_args())
    assert isinstance(result, DispatchResult)
    assert result.sent is True
    assert result.duplicate is False
    row = store.get_task(result.task_id)
    assert row is not None
    assert row.id == result.task_id
    assert row.status == "dispatched"
    assert row.objective == _args()["objective"]


def test_write_failure_raises_and_is_never_claimed_sent(tmp_path, monkeypatch):
    store = _store(tmp_path)

    def boom(**_kw):
        raise LedgerWriteError("disk I/O error")

    monkeypatch.setattr(store, "create_task", boom)
    with pytest.raises(DispatchError, match="not sent") as excinfo:
        dispatch(store, **_args())
    assert store.list_tasks() == ()
    probe = excinfo.value.probe()
    assert probe["result"] == "fail"
    assert probe["target"] == "delegation.db"
    assert probe["name"] == "delegation_dispatch"
    assert "not sent" in probe["detail"]
    persisted = recent_dispatch_probes(path=tmp_path / "dispatch_probes.jsonl")
    assert persisted and persisted[-1]["result"] == "fail"


def test_unreadable_row_raises_never_returns_the_id(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(store, "create_task", lambda **_kw: "ghost-id")
    monkeypatch.setattr(store, "get_task", lambda _tid: None)
    with pytest.raises(DispatchError, match="not persist ghost-id") as excinfo:
        dispatch(store, **_args())
    assert excinfo.value.probe()["result"] == "fail"


def test_create_task_raises_if_row_missing_after_commit(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(store, "get_task", lambda _tid: None)
    with pytest.raises(LedgerWriteError, match="not sent"):
        store.create_task(**_args())


def test_duplicate_dispatch_is_idempotent(tmp_path):
    store = _store(tmp_path)
    first = dispatch(store, **_args())
    second = dispatch(store, **_args())
    assert second.duplicate is True
    assert second.sent is True
    assert second.task_id == first.task_id
    assert len(store.list_tasks()) == 1


def test_whitespace_and_case_duplicate_is_idempotent(tmp_path):
    store = _store(tmp_path)
    dispatch(store, **_args())
    messy = _args(objective="  add a MEDIC   retired-units\n regression test.  ")
    again = dispatch(store, **messy)
    assert again.duplicate is True
    assert len(store.list_tasks()) == 1


def test_retry_after_failure_is_a_new_row(tmp_path):
    store = _store(tmp_path)
    first = dispatch(store, **_args())
    store.set_status(first.task_id, "executing")
    store.set_status(first.task_id, "failed")
    second = dispatch(store, **_args())
    assert second.duplicate is False
    assert second.task_id != first.task_id
    assert len(store.list_tasks()) == 2


def test_dispatch_task_tool_returns_committed_id(tmp_path):
    store = _store(tmp_path)
    tool = build_dispatch_task_tool(store=store)
    result = tool.handler({
        "objective": "Refresh README and CURRENT_TRUTH.",
        "scope": "README.md docs/CURRENT_TRUTH.md",
        "acceptance": "python -m pytest tests/test_docs_consistency.py -q",
    })
    assert result["sent"] is True
    assert store.get_task(result["task_id"]) is not None


def test_dispatch_task_tool_write_failure_raises(tmp_path, monkeypatch):
    store = _store(tmp_path)
    tool = build_dispatch_task_tool(store=store)
    monkeypatch.setattr(
        store, "create_task",
        lambda **_kw: (_ for _ in ()).throw(LedgerWriteError("locked")),
    )
    with pytest.raises(DispatchError, match="not sent"):
        tool.handler({
            "objective": "Refresh README and CURRENT_TRUTH.",
            "scope": "README.md",
            "acceptance": "python -m pytest tests/test_docs_consistency.py -q",
        })
    assert store.list_tasks() == ()


def test_house_post_forge_reports_ledger_id(tmp_path, monkeypatch):
    db = tmp_path / "citizens.db"
    monkeypatch.setenv("SOVERYN_CITIZENS_DB", str(db))
    monkeypatch.setenv("SOVERYN_DELEGATION_DB", str(tmp_path / "delegation.db"))
    with connect(db) as conn:
        for cid, name in (("aetheria", "Aetheria"), ("forge", "Forge")):
            register(
                conn,
                Citizen(
                    id=cid,
                    display_name=name,
                    workspace_path=str(tmp_path / "desks" / cid),
                ),
            )
    reg = ToolRegistry(audit_hook=lambda _e: None)
    register_house_post_tools(reg, owner_agent="aetheria")
    out = reg.invoke(
        "aetheria",
        "house_post_send",
        {"to_id": "forge", "body": "Write the medic retired-units test.", "kind": "request"},
    )
    assert out.get("ok") is True, out
    assert out.get("sent") is True
    assert out.get("task_id")
    store = DelegationStore(tmp_path / "delegation.db")
    row = store.get_task(out["task_id"])
    assert row is not None
    assert row.status == "recorded"


def test_house_post_forge_write_failure_is_not_sent(tmp_path, monkeypatch):
    db = tmp_path / "citizens.db"
    monkeypatch.setenv("SOVERYN_CITIZENS_DB", str(db))
    monkeypatch.setenv("SOVERYN_DELEGATION_DB", str(tmp_path / "delegation.db"))
    with connect(db) as conn:
        for cid, name in (("aetheria", "Aetheria"), ("forge", "Forge")):
            register(
                conn,
                Citizen(
                    id=cid,
                    display_name=name,
                    workspace_path=str(tmp_path / "desks" / cid),
                ),
            )

    def boom(**_kw):
        raise DispatchError("delegation ledger insert failed; not sent: locked")

    monkeypatch.setattr(
        "soveryn.platform.delegation.dispatch.dispatch_forge_handoff",
        boom,
    )
    reg = ToolRegistry(audit_hook=lambda _e: None)
    register_house_post_tools(reg, owner_agent="aetheria")
    out = reg.invoke(
        "aetheria",
        "house_post_send",
        {"to_id": "forge", "body": "Write the medic retired-units test.", "kind": "request"},
    )
    assert out.get("ok") is False
    assert out.get("sent") is False
    assert out.get("task_id") is None
    assert out.get("probe", {}).get("result") == "fail"
    store = DelegationStore(tmp_path / "delegation.db")
    assert store.list_tasks() == ()


def test_format_dispatch_error_block_is_probed(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DISPATCH_PROBES", str(tmp_path / "probes.jsonl"))
    store = _store(tmp_path)
    monkeypatch.setattr(
        store, "create_task",
        lambda **_kw: (_ for _ in ()).throw(LedgerWriteError("locked")),
    )
    with pytest.raises(DispatchError):
        dispatch(store, **_args())
    block = format_dispatch_error_block()
    assert "Verified dispatch failures" in block
    assert "result=fail" in block
    records = as_probe_records(recent_dispatch_probes())
    assert records
    first = records[0]
    if hasattr(first, "is_down"):
        assert first.is_down
    else:
        assert first["result"] == "fail"


def test_kernel_alias_is_a_forge_assignee():
    assert is_forge_assignee("forge")
    assert is_forge_assignee("kernel")
    assert is_forge_assignee("scotty")
    assert not is_forge_assignee("eve")


def test_ask_peer_forge_reports_ledger_id(tmp_path, monkeypatch):
    from soveryn.memory.conversation_store import ConversationStore
    from soveryn.rooms.store import ask_peer, open_room

    db = tmp_path / "citizens.db"
    monkeypatch.setenv("SOVERYN_CITIZENS_DB", str(db))
    monkeypatch.setenv("SOVERYN_DELEGATION_DB", str(tmp_path / "delegation.db"))
    with connect(db) as conn:
        for cid, name in (("aetheria", "Aetheria"), ("forge", "Forge")):
            register(
                conn,
                Citizen(
                    id=cid,
                    display_name=name,
                    workspace_path=str(tmp_path / "desks" / cid),
                ),
            )
    conv = ConversationStore(tmp_path / "conv.db")
    dm = conv.new_session("aetheria", title="dm")
    room = open_room(conv, data_root=tmp_path / "data", peer="forge", dm_session_id=dm)
    out = ask_peer(
        conv,
        data_root=tmp_path / "data",
        citizens_db=db,
        session_id=room["session_id"],
        brief="Refresh README and CURRENT_TRUTH.",
        peer="forge",
    )
    assert out.get("ok") is True
    task_id = out["routing"]["task_id"]
    assert task_id
    assert out["event"]["task_id"] == task_id
    store = DelegationStore(tmp_path / "delegation.db")
    assert store.get_task(task_id) is not None
    hist = conv.load_history(room["session_id"])
    assert any(task_id in t.content for t in hist)
