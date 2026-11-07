"""Behavioral regressions for the live representation repair, 2026-11-06."""
import io
import json
import re
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from soveryn.agents.representation import cognition
from soveryn.agents.representation.briefing import build_briefing, MAX_PROMPT_BYTES, _is_autonomous
from soveryn.agents.representation.config import RepresentationConfig
from soveryn.agents.representation.daemon import RepresentationDaemon, _is_autonomous_title
from soveryn.agents.representation.novelty_gate import conv_turn_lookup, to_ny
from soveryn.agents.representation.parse import parse_conclusions
from soveryn.agents.representation.prompt import render_representation_prompt
from soveryn.agents.representation.sources import recent_turns
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.lattice.legacy import LatticeStore


@pytest.fixture
def stores(tmp_path):
    return ConversationStore(tmp_path / "conv.db"), LatticeStore(tmp_path / "lattice.db")


def add(conv, agent, stamps, *, title="human conversation", content="A substantial conversation about deliberate engineering choices.", roles=None):
    sid = conv.new_session(agent, title=title)
    for i, stamp in enumerate(stamps):
        conv.save_turn(sid, agent, (roles or ["user"] * len(stamps))[i], content)
    with sqlite3.connect(conv.db_path) as c:
        ids = c.execute("SELECT rowid FROM conversations WHERE session_id=? ORDER BY rowid", (sid,)).fetchall()
        for (rowid,), stamp in zip(ids, stamps):
            c.execute("UPDATE conversations SET timestamp=? WHERE rowid=?", (stamp.isoformat(), rowid))
    return sid


def good(prompt, url):
    ids = list(dict.fromkeys(re.findall(r"\[node:(turn:[^\]]+)\]", prompt)))
    return f"inductive | confident | Jon tests architectural decisions against evidence. | [node:{ids[0]}],[node:{ids[1]}]"


def daemon(stores, chat=good, dry=True):
    conv, lat = stores
    return RepresentationDaemon(conv_store=conv, lattice_store=lat, chat_fn=chat,
        embed_fn=None, config=RepresentationConfig(min_turns=1, dry_run=dry, turns_per_briefing=8))


def test_latest_timestamp_window_full_indices_all_agents_and_future(stores):
    conv, lat = stores
    now = datetime.now()
    sid = add(conv, "kernel", [now-timedelta(days=8), now-timedelta(hours=2), now-timedelta(hours=1), now+timedelta(days=1)], roles=["system","user","assistant","user"])
    sid2 = add(conv, "eve", [now-timedelta(minutes=1)])
    # Deliberately stale metadata cannot hide evidence.
    with sqlite3.connect(conv.db_path) as c:
        c.execute("UPDATE conversation_meta SET updated_at='2000-01-01' WHERE session_id=?", (sid,))
    text, _, ids = build_briefing(conv, lat, owner_agent="aetheria", subject="jon", turns_per_briefing=2, now=now)
    assert ids == [f"turn:{sid}:2", f"turn:{sid2}:0"]
    assert "Eve" not in text  # this Eve turn is a user, not the assistant
    assert "Unverified user on eve" in text
    lookup = conv_turn_lookup(conv.db_path)
    for nid in ids:
        sess, idx = nid[5:].rsplit(":",1)
        assert now.replace(tzinfo=to_ny(now).tzinfo)-timedelta(days=7) <= lookup(sess,int(idx)) <= to_ny(now)


def test_first_tick_filters_old_turns(stores):
    conv, _ = stores
    now = datetime.now()
    add(conv,"aetheria",[now-timedelta(days=8)] * 8)
    d = daemon(stores)
    assert d._count_new_turns_since(None, now) == 0
    assert d._do_tick(now=now)["skip_reason"] == "below_min_turns"


@pytest.mark.parametrize("title", ["automation:service_crash_watch", " AUTOMATION:other", "[heartbeat] aetheria", "[commission] task", "🤖 nightly", "[webhook] job"])
def test_shared_automation_filter(stores,title):
    conv,_ = stores
    now=datetime.now()
    add(conv,"pondwright",[now-timedelta(minutes=1)] * 2,title=title)
    assert _is_autonomous is _is_autonomous_title
    assert _is_autonomous(title)
    assert recent_turns(conv,now=now) == []


def test_failure_preserves_cursor_then_success_consumes(stores,monkeypatch):
    conv,_=stores
    now=datetime.now()
    add(conv,"eve",[now-timedelta(minutes=2),now-timedelta(minutes=1)])
    calls=[]
    def down(p,u):
        calls.append(1)
        raise TimeoutError("temporarily down")
    monkeypatch.setattr(cognition.time,"sleep",lambda _:None)
    d=daemon(stores,down)
    assert d._do_tick(now=now)["skip_reason"] == "cognition_failure"
    assert calls == [1,1]
    assert d._last_run_at is None
    d.chat_fn=good
    assert d._do_tick(now=now)["conclusion_count"] == 1
    assert d._last_run_at == now
    assert not d._do_tick(now=now+timedelta(minutes=1))["eligible"]


def test_http_body_logging_and_nonretryable_400(monkeypatch,caplog):
    calls=[]
    def bad(p,u):
        calls.append(1)
        raise HTTPError(u,400,"bad",{},io.BytesIO(b'context too large'))
    with pytest.raises(cognition.CognitionFailure):
        cognition.run_representation_pass(subject="jon",briefing="",prior_conclusions="",cognition_url="http://x",chat_fn=bad)
    assert len(calls)==1
    assert "status=400" in caplog.text and "context too large" in caplog.text


def test_prompt_budget_multibyte_and_many_priors(stores):
    conv,lat=stores
    now=datetime.now()
    add(conv,"kernel",[now-timedelta(seconds=i+1) for i in range(8)],content="界" * 20000)
    for i in range(20):
        lat.write_node(agent="aetheria",content="prior" * 80,node_type="conclusion",layer="private",provenance={"subject":"jon"})
    text,prior,ids=build_briefing(conv,lat,owner_agent="aetheria",subject="jon",turns_per_briefing=8,now=now)
    prompt=render_representation_prompt(subject="jon",briefing=text,prior_conclusions=prior)
    assert len(prompt.encode()) <= MAX_PROMPT_BYTES
    assert len([x for x in ids if x.startswith("turn:")]) >= 2
    assert all(f"[node:{x}]" in prompt for x in ids)


def test_unknown_old_prior_only_and_repeated_citations_rejected(stores):
    conv,lat=stores
    now=datetime.now()
    add(conv,"eve",[now-timedelta(minutes=2),now-timedelta(minutes=1)])
    old = lat.write_node(agent="aetheria",content="previous",node_type="conclusion",layer="private",provenance={"subject":"jon"})
    def invalid(p,u):
        tid=re.findall(r"\[node:(turn:[^\]]+)\]",p)[0]
        return (f"inductive | confident | invented | [node:{tid}],[node:fake]\n"
                f"inductive | confident | repeated | [node:{tid}],[node:{tid}]\n"
                f"inductive | confident | prior only | [node:{old}],[node:fake2]")
    d=daemon(stores,invalid,dry=False)
    assert d._do_tick(now=now)["conclusion_count"]==0
    assert len(lat.iter_nodes(agent="aetheria"))==1
    assert parse_conclusions("inductive | confident | repeated | [node:x],[node:x]")==[]


def test_cross_agent_customer_included_but_unverified_and_live_traceable(stores):
    conv,lat=stores
    now=datetime.now()
    sid=add(conv,"pondwright",[now-timedelta(minutes=2),now-timedelta(minutes=1)])
    d=daemon(stores,dry=False)
    out=d._do_tick(now=now)
    assert out["eligible"] and out["written"]["written"]==1
    assert out["pondwright_available"]==2
    assert out["selected_agents"]==["pondwright"]
    rec=[n for n in lat.iter_nodes(agent="aetheria") if n.type=="conclusion"][0]
    assert rec.provenance["premises"]==[f"turn:{sid}:0",f"turn:{sid}:1"]
    lookup=conv_turn_lookup(conv.db_path)
    assert all(lookup(sid,i) is not None for i in (0,1))


def test_retryable_503_is_bounded_and_empty_success_is_valid(monkeypatch):
    monkeypatch.setattr(cognition.time,"sleep",lambda _:None)
    calls=[]
    def chat(p,u):
        calls.append(1)
        if len(calls)==1:
            raise HTTPError(u,503,"busy",{},io.BytesIO(b'busy'))
        return ""
    assert cognition.run_representation_pass(subject="jon",briefing="",prior_conclusions="",cognition_url="http://x",chat_fn=chat)==[]
    assert len(calls)==2


@pytest.mark.parametrize("source", ["automation", "teammates_overnight"])
def test_automation_source_cannot_hide_under_plain_title(stores,source):
    conv,_=stores
    now=datetime.now()
    sid=add(conv,"eve",[now-timedelta(minutes=1)],title="ordinary title")
    with sqlite3.connect(conv.db_path) as c:
        c.execute("UPDATE conversations SET source=? WHERE session_id=?",(source,sid))
    assert recent_turns(conv,now=now)==[]


def test_mixed_agent_session_keeps_global_full_history_index(stores):
    conv,_=stores
    now=datetime.now()
    sid=add(conv,"kernel",[now-timedelta(minutes=3)],roles=["system"])
    conv.save_turn(sid,"eve","user","This later user turn has meaningful content.")
    conv.save_turn(sid,"pondwright","assistant","This other agent's response has meaningful content.")
    turns=recent_turns(conv,now=datetime.now()+timedelta(seconds=1))
    assert [t.id for t in turns]==[f"turn:{sid}:1",f"turn:{sid}:2"]
    lookup=conv_turn_lookup(conv.db_path)
    assert lookup(sid,1)==turns[0].timestamp and lookup(sid,2)==turns[1].timestamp


def test_successful_empty_response_advances_cursor(stores):
    conv,_=stores
    now=datetime.now()
    add(conv,"eve",[now-timedelta(minutes=2),now-timedelta(minutes=1)])
    d=daemon(stores,lambda p,u: "")
    assert d._do_tick(now=now)["conclusion_count"]==0
    assert d._last_run_at==now
