"""Forge extraction, attribution, privacy and house-gate isolation regressions."""
import json
import re
import sqlite3
from datetime import datetime, timedelta
from dataclasses import replace

import pytest

from soveryn.agents.representation.config import RepresentationConfig
from soveryn.agents.representation.daemon import RepresentationDaemon
from soveryn.agents.representation.forge_memory import ForgeMemoryPass, parse_operational
from soveryn.agents.representation.novelty_gate import load_conclusions, conv_turn_lookup, to_ny
from soveryn.agents.representation.parse import Conclusion
from soveryn.agents.representation.sources import recent_turns
from soveryn.agents.representation.writeback import write_conclusions
from soveryn.agents.aetheria.tools.lookup import build_get_node_tool
from soveryn.agents.aetheria.tools.recent import build_recent_tool
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.lattice.legacy import LatticeStore


@pytest.fixture
def stores(tmp_path):
    return ConversationStore(tmp_path/"conv.db"), LatticeStore(tmp_path/"lattice.db")


def seed(conv, *, agent="forge", title="Build decisions", source="direct", days=0):
    sid=conv.new_session(agent,title=title)
    conv.save_turn(sid,agent,"user","I require repeatable measurements before adopting build changes.",source=source)
    conv.save_turn(sid,agent,"assistant","The verified test output was 57 passed; keep owner-scoped deduplication.",source=source)
    if days:
        with sqlite3.connect(conv.db_path) as c:
            c.execute("UPDATE conversations SET timestamp=? WHERE session_id=?",((datetime.now()-timedelta(days=days)).isoformat(),sid))
    return sid


def ids(prompt):
    return list(dict.fromkeys(re.findall(r"\[node:(turn:[^\]]+)\]",prompt)))


def good(prompt,url):
    cited=ids(prompt)
    if prompt.startswith("FORGE OPERATIONAL"):
        return f"lesson | Verified tests passed; retain owner-scoped deduplication. | [node:{cited[1]}]"
    return f"inductive | fairly confident | Jon requires repeatable evidence for build changes. | [node:{cited[0]}],[node:{cited[1]}]"


def make(stores,chat=good,**kw):
    conv,lat=stores
    cfg=RepresentationConfig(dry_run=kw.get("dry_run",False),turns_per_briefing=8,forge_memory_enabled=True)
    return ForgeMemoryPass(conv_store=conv,lattice_store=lat,config=cfg,chat_fn=chat,embed_fn=lambda _: (1.,0.,0.))


def test_two_kinds_forge_only_provenance_and_untouched_kernel(stores):
    conv,lat=stores
    sid=seed(conv)
    seed(conv,agent="eve")
    seed(conv,title="automation:service_crash_watch")
    seed(conv,title="innocuous",source="automation")
    seed(conv,days=8)
    kernel=lat.write_node(agent="kernel",content="Kernel's own retained fact.",node_type="fact",layer="global")
    result=make(stores).tick(now=datetime.now()+timedelta(seconds=1))
    assert result["available_turns"]==2
    assert result["selected_sessions"]==[sid]
    assert {k:v["written"] for k,v in result["kinds"].items()}=={"conclusion":1,"operational_memory":1}
    nodes=lat.iter_nodes(agent="forge")
    assert {n.type for n in nodes}=={"conclusion","operational_memory"}
    assert all(n.layer=="private" for n in nodes)
    lookup=conv_turn_lookup(conv.db_path)
    for n in nodes:
        assert n.provenance["source_agent"]=="forge"
        assert n.provenance["source_sessions"]==[sid]
        assert n.provenance["kind"]==n.type
        for t in n.provenance["source_turns"]:
            sess,idx=t["id"][5:].rsplit(":",1)
            assert lookup(sess,int(idx))==to_ny(t["timestamp"])
    assert lat.get_node(kernel).agent=="kernel"


def test_owner_and_kind_dedupe(stores):
    _,lat=stores
    rec=Conclusion("inductive","tentative","Same note legitimately held by two owners.",("turn:s:0",))
    kw=dict(subject="jon",run_id="r",embed_fn=None,dry_run=False)
    assert write_conclusions(lat,[rec],owner_agent="aetheria",**kw)["written"]==1
    assert write_conclusions(lat,[rec],owner_agent="forge",**kw)["written"]==1
    assert write_conclusions(lat,[rec],owner_agent="forge",node_type="operational_memory",**kw)["written"]==1
    again=write_conclusions(lat,[rec],owner_agent="forge",**kw)
    assert again["written"]==0 and again["skipped_exact"]==1
    near=replace(rec,content="Same note legitimately held by two owners!")
    assert write_conclusions(lat,[near],owner_agent="forge",**kw)["written"]==0


def test_forge_retrieval_own_private_search_and_recent(stores):
    conv,lat=stores;seed(conv)
    make(stores).tick(now=datetime.now()+timedelta(seconds=1))
    own={n.id for n in lat.iter_nodes(agent="forge")}
    assert own
    assert {n.id for n,_ in lat.find_nodes_by_embedding("forge",(1.,0.,0.),limit=10,threshold=0)}==own
    for agent in ("aetheria","eve","kernel"):
        assert not own.intersection(n.id for n,_ in lat.find_nodes_by_embedding(agent,(1.,0.,0.),limit=10,threshold=0))
        assert not any(x in json.dumps(build_recent_tool(store=lat,owner_agent=agent).handler({})) for x in own)
    for nid in own:
        assert nid in json.dumps(build_get_node_tool(store=lat,owner_agent="forge").handler({"node_id":nid}))


@pytest.mark.parametrize("other_agent", ["aetheria", "eve", "kernel"])
def test_private_lookup_must_deny_other_agent_by_known_id(stores, other_agent):
    # Regression: a known UUID must never bypass private-node ownership.
    conv,lat=stores;seed(conv)
    make(stores).tick(now=datetime.now()+timedelta(seconds=1))
    nid=lat.iter_nodes(agent="forge")[0].id
    denied=build_get_node_tool(store=lat,owner_agent=other_agent).handler({"node_id":nid})
    assert denied.get("not_found") is True
    assert nid not in json.dumps(denied)


def test_house_gate_excludes_forge_and_ops(stores):
    conv,lat=stores;seed(conv)
    make(stores).tick(now=datetime.now()+timedelta(seconds=1))
    aid=lat.write_node(agent="aetheria",content="House-only conclusion.",node_type="conclusion",layer="private",provenance={"subject":"jon"})
    assert [r.id for r in load_conclusions(lat.db_path)]==[aid]
    forge=load_conclusions(lat.db_path,owner_agent="forge")
    assert len(forge)==1
    assert lat.get_node(forge[0].id).type=="conclusion"


def test_independent_kind_cursors_and_house_cursor(stores,monkeypatch):
    from soveryn.agents.representation import cognition
    monkeypatch.setattr(cognition.time,"sleep",lambda _:None)
    conv,lat=stores;seed(conv)
    calls=[]
    def ops_down(p,u):
        calls.append(p.startswith("FORGE OPERATIONAL"))
        if p.startswith("FORGE OPERATIONAL"):raise TimeoutError("ops temporarily down")
        return good(p,u)
    f=make(stores,ops_down);now=datetime.now()+timedelta(seconds=1)
    house=RepresentationDaemon(conv_store=conv,lattice_store=lat,chat_fn=good,embed_fn=None,config=RepresentationConfig(min_turns=1))
    first=f.tick(now=now)
    assert first["kinds"]["conclusion"]["written"]==1
    assert first["kinds"]["operational_memory"]["skip_reason"]=="cognition_failure"
    assert f.cursors["conclusion"]==now and f.cursors["operational_memory"] is None
    assert house._last_run_at is None
    f.chat_fn=good
    second=f.tick(now=now+timedelta(seconds=1))
    assert not second["kinds"]["conclusion"]["eligible"]
    assert second["kinds"]["operational_memory"]["written"]==1
    assert calls==[False,True,True]


@pytest.mark.parametrize("reply",[
    "fix | fabricated | [node:fake]",
    "fix | no citations | ",
    "unknown | wrong type | [node:fake]",
    "fix | "+"x"*401+" | [node:fake]",
])
def test_operational_bad_sources_or_format_rejected(stores,reply):
    conv,lat=stores;seed(conv)
    def chat(p,u):return reply if p.startswith("FORGE OPERATIONAL") else ""
    out=make(stores,chat).tick(now=datetime.now()+timedelta(seconds=1))
    assert out["kinds"]["operational_memory"]["written"]==0
    assert not lat.iter_nodes(agent="forge")


def test_jons_two_distinct_premises_required(stores):
    conv,lat=stores;seed(conv)
    def chat(p,u):
        if p.startswith("FORGE OPERATIONAL"):return ""
        tid=ids(p)[0]
        return f"inductive | confident | Repeated one turn does not prove a trait. | [node:{tid}],[node:{tid}]"
    out=make(stores,chat).tick(now=datetime.now()+timedelta(seconds=1))
    assert out["kinds"]["conclusion"]["written"]==0


def test_operational_cannot_cite_prior_not_in_its_prompt(stores):
    conv,lat=stores;seed(conv)
    old=lat.write_node(agent="forge",content="An older trait.",node_type="conclusion",layer="private",provenance={"subject":"jon"})
    def chat(p,u):
        if not p.startswith("FORGE OPERATIONAL"):return ""
        return f"fix | Prior ID was not supplied to ops. | [node:{ids(p)[0]}],[node:{old}]"
    out=make(stores,chat).tick(now=datetime.now()+timedelta(seconds=1))
    assert out["kinds"]["operational_memory"]["written"]==0


def test_bound_four_operational_notes_and_length():
    raw="\n".join(f"gotcha | Unique operational note {i}. | [node:turn:s:{i}]" for i in range(9))
    assert len(parse_operational(raw))==4
    assert all(len(x.content)<=400 for x in parse_operational(raw))


def test_forge_source_requires_forge_session_not_just_turn_agent(stores):
    conv,_=stores
    sid=conv.new_session("eve",title="Eve session")
    conv.save_turn(sid,"forge","assistant","This mixed-agent turn must not become Forge session evidence.")
    assert recent_turns(conv,now=datetime.now()+timedelta(seconds=1),source_agent="forge")==[]


def test_dry_run_and_replay_dedupes(stores):
    conv,lat=stores;seed(conv);now=datetime.now()+timedelta(seconds=1)
    dry=make(stores,dry_run=True).tick(now=now)
    assert dry["dry_run"] and not lat.iter_nodes(agent="forge")
    make(stores).tick(now=now)
    replay=make(stores).tick(now=now)
    assert all(r["written"]==0 and r["writeback"]["skipped_exact"]==1 for r in replay["kinds"].values())


def test_forge_flag_is_opt_in():
    assert not RepresentationConfig().forge_memory_enabled
    assert RepresentationConfig.from_env({"SOVERYN_REPR_FORGE_MEMORY_ENABLED":"true"}).forge_memory_enabled
